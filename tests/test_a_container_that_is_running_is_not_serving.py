# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B440` — the `pantheon` service had no healthcheck, so Docker could not tell
*running* from *serving*.

Measured 2026-09-17 on `docker-compose.yml`: `searxng` carries a healthcheck and
`pantheon` waits on it (`depends_on: condition: service_healthy`), and the
comments around it record two incidents where that mattered — a broken upstream
`searxng:latest` (issue #1414) and the capability set the entrypoint needs
(issue #721). `pantheon` itself had **none**. `docker compose up -d` prints
`Container ... Started` and returns while the app is still importing itself, and
on the deployment host the port answers `Connection refused` for another
35-60 s. A hand-run probe at 25 s reported every route down twice on the day
this was written.

**What the healthcheck has to mean.** "The process is alive" is worthless here —
the process is alive for the whole 35-60 s window. The probe therefore makes an
HTTP request and reads the answer, and the tests below **run the shipped command
string** against a stub server rather than reading it: a login redirect, a 500,
a truncated body and a refused connection each have to fail it, because each of
those is a real way for this app to be up and not serving.

The stub listens on an ephemeral port and the command's `http://127.0.0.1:7000`
is rewritten to it — binding 7000 inside a test run would collide with anything
else that wants it. The shipped netloc is asserted separately, so the pair still
pins both the target and the behaviour.
"""
import json
import re
import shlex
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.gpu-nvidia.yml",
    ROOT / "docker-compose.gpu-amd.yml",
)

# The worst bind measured on the deployment host. `start_period` has to clear
# it or a healthy start reports unhealthy; see the comment in the compose file
# for why the margin above it is cheap and the margin below it is not.
WORST_MEASURED_BIND_SECONDS = 60


def _service(path: Path, name: str = "pantheon") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["services"][name]


def _healthcheck(path: Path) -> dict:
    hc = _service(path).get("healthcheck")
    assert hc, (
        f"{path.name} defines no healthcheck on `pantheon`. Without one Docker "
        f"reports a container that binds nothing as Up, and `docker compose up -d` "
        f"returning tells you nothing about whether the app is serving (`B440`).")
    return hc


def _seconds(value) -> float:
    """Compose duration → seconds. Only the units these files use."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", str(value).strip())
    assert m, f"unparseable duration {value!r}"
    return float(m.group(1)) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600, None: 1}[m.group(2)]


def _shell_command(path: Path) -> str:
    test = _healthcheck(path)["test"]
    assert isinstance(test, list) and test[0] == "CMD-SHELL", (
        f"{path.name}: expected a CMD-SHELL probe, got {test!r}")
    return test[1]


# ── the shipped string ───────────────────────────────────────────────────────

def test_every_compose_file_gives_pantheon_the_same_healthcheck():
    """`Law 13`. Three compose files start this service and a healthcheck in one
    of three is the defect class the standalone GPU files exist to create."""
    shapes = {p.name: _healthcheck(p) for p in COMPOSE_FILES}
    first = next(iter(shapes.values()))
    for name, hc in shapes.items():
        assert hc == first, f"{name}'s healthcheck differs from docker-compose.yml's"


def test_the_probe_asks_this_app_over_http_on_the_port_it_binds():
    cmd = _shell_command(COMPOSE_FILES[0])
    # `B441` moved it from `/api/health` (liveness) to `/api/ready` (readiness).
    assert "http://127.0.0.1:7000/api/ready" in cmd, (
        "the probe must ask the port the app binds. `localhost` is not "
        "interchangeable here: uvicorn binds 0.0.0.0, which is IPv4 only, and "
        "`localhost` can resolve to ::1 first")
    assert cmd.startswith("python "), (
        "the probe runs in the app image, whose base is python:3.14-slim — the "
        "interpreter is the one dependency that is certain to be there")


def test_the_route_it_probes_is_one_the_auth_middleware_exempts():
    """A probe behind the login wall reports the login page, forever.

    Asked of `app.py`'s exemption table rather than of the compose file, because
    the compose file cannot know — and read as the AST reads it, since `B542`
    made each entry a path with the methods it exempts: the probe's GET has to
    be one of them.
    """
    import ast
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    table = next(node.value for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(getattr(t, "id", None) == "AUTH_EXEMPT_EXACT" for t in node.targets))
    exempt = {k.value: {e.value for e in v.elts} for k, v in zip(table.keys, table.values)}
    assert "GET" in exempt.get("/api/ready", set()), (
        "the compose healthcheck GETs /api/ready with no session. It is no longer "
        "auth-exempt for GET, so the probe now reads 401")


def test_start_period_clears_the_slowest_start_anybody_measured():
    hc = _healthcheck(COMPOSE_FILES[0])
    start = _seconds(hc["start_period"])
    assert start >= WORST_MEASURED_BIND_SECONDS, (
        f"start_period is {start:.0f}s and the slowest measured bind is "
        f"{WORST_MEASURED_BIND_SECONDS}s. Inside start_period a failing probe does "
        f"not count against retries; below it, a healthy start is reported unhealthy")
    # The other direction. Inside start_period a container that never comes up
    # still reads `starting`, so the margin is what an operator waits before
    # Docker will say anything is wrong.
    interval, retries = _seconds(hc["interval"]), int(hc["retries"])
    worst = start + interval * retries
    assert worst <= 300, (
        f"a container that never binds would sit at `starting` for {worst:.0f}s "
        f"before it reads unhealthy — long enough that nobody waits for it")
    assert _seconds(hc["timeout"]) < interval * retries


# ── the shipped string, run ──────────────────────────────────────────────────

class _Stub(BaseHTTPRequestHandler):
    behaviour = "ready"

    def do_GET(self):                                      # noqa: N802
        kind = type(self).behaviour
        if kind == "ready":
            body = json.dumps({"ready": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif kind == "login_redirect":
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        elif kind == "login_page":
            body = b"<!doctype html><title>Sign in</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif kind in ("not_ready", "not_ready_but_200", "liveness_only"):
            # `B441`: 503 is what the app answers when a critical check fails;
            # a 200 that does not say ready, and `/api/health`'s own body,
            # must fail the probe too.
            body = json.dumps({"ready": False} if kind != "liveness_only"
                              else {"status": "healthy"}).encode()
            self.send_response(503 if kind == "not_ready" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *a):                             # keep pytest output clean
        pass


@pytest.fixture
def stub():
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _run_probe(command: str, base: str) -> int:
    """Run the shipped probe against `base` instead of the container's port.

    Only two substitutions: the netloc, and `python` → this interpreter (the
    image has `python`, a dev box usually has `python3`). Everything the check
    actually decides on is the shipped text.
    """
    assert command.startswith("python -c ")
    rewritten = command.replace("http://127.0.0.1:7000", base)
    rewritten = shlex.quote(sys.executable) + rewritten[len("python"):]
    return subprocess.run(rewritten, shell=True, capture_output=True,
                          text=True, timeout=60).returncode


@pytest.mark.parametrize("behaviour,expect_ok", [
    ("ready", True),
    ("login_redirect", False),
    ("login_page", False),
    ("not_ready", False),
    ("not_ready_but_200", False),
    ("liveness_only", False),
    ("error", False),
])
def test_the_probe_passes_only_when_the_app_answered_it(stub, behaviour, expect_ok):
    """Each failing case here is a real way for this container to be up and
    not serving: auth in front of the probe, an error page, a body that parses
    but does not say healthy, a 500 from a half-initialised app."""
    _Stub.behaviour = behaviour
    base = f"http://127.0.0.1:{stub.server_address[1]}"
    rc = _run_probe(_shell_command(COMPOSE_FILES[0]), base)
    assert (rc == 0) is expect_ok, f"behaviour={behaviour} exited {rc}"


def test_the_probe_fails_while_nothing_is_listening():
    """The 35-60 s window itself — the whole reason this healthcheck exists."""
    dead = HTTPServer(("127.0.0.1", 0), _Stub)
    port = dead.server_address[1]
    dead.server_close()
    rc = _run_probe(_shell_command(COMPOSE_FILES[0]), f"http://127.0.0.1:{port}")
    assert rc != 0, "a refused connection must fail the healthcheck"


def test_the_probe_does_not_depend_on_assertions_being_enabled():
    """`python -O` strips `assert`. Nothing sets PYTHONOPTIMIZE in these images,
    but a probe whose verdict lives in an assertion is one env var from always
    passing, and a healthcheck that always passes is worse than none."""
    cmd = _shell_command(COMPOSE_FILES[0])
    assert re.search(r"\bassert\b", cmd) is None, (
        "the probe decides with an assert; use sys.exit so -O cannot disable it")
