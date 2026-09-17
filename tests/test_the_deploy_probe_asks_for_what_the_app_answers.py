# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B441` — the deploy probe's route table, re-measured against the real app.

`scripts/pantheon-deploy`'s `ROUTES` says what each path answered when it was
measured on 2026-09-17 with the compose defaults (`AUTH_ENABLED=true`,
`LOCALHOST_BYPASS=false`). A table of expectations written down once is a table
that goes stale, and the way it goes stale is the worst way: the deploy fails at
2am on a route contract somebody changed on purpose three weeks earlier.

So this boots the real application out of process — the same shape
`tests/helpers/served_pages.py` uses, and for the same reason: importing `app`
pulls the whole thing up — and asks for exactly the paths the probe asks for.
If a route starts answering something else, this fails here, in the suite,
rather than there.

It also records the finding the table carries a comment about. **`/api/ready`
answers 401.** `src/readiness.py`'s own docstring says it is "suitable for an
orchestrator readiness probe (200 only when every critical check passes)", and
`app.py`'s `AUTH_EXEMPT_EXACT` does not list it, so with the shipped defaults an
orchestrator gets 401 and never sees either 200 or 503. That is why the compose
healthcheck probes `/api/health` — liveness — rather than the endpoint written
for the job. The row is `B441`; this test pins the measurement it rests on.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from tests.helpers.cli_loader import load_script  # noqa: E402

pytest.importorskip("fastapi")
pytest.importorskip("starlette.testclient")

_PROBE = r'''
import json, sys
import app as app_module
from fastapi.testclient import TestClient

client = TestClient(app_module.app)
out = {}
for path in json.loads(sys.argv[1]):
    res = client.get(path, follow_redirects=False)
    out[path] = {"status": res.status_code,
                 "location": res.headers.get("location"),
                 "body": res.text[:400]}
print("RESULT=" + json.dumps(out, sort_keys=True))
'''


@pytest.fixture(scope="module")
def routes():
    return load_script("pantheon-deploy").ROUTES


@pytest.fixture(scope="module")
def answered(tmp_path_factory, routes):
    """Ask the real app, with auth on, for every path the probe asks for."""
    tmp = tmp_path_factory.mktemp("deployprobe")
    env = os.environ.copy()
    env.update({
        # The compose defaults, which is the configuration the probe runs under.
        "AUTH_ENABLED": "true",
        "LOCALHOST_BYPASS": "false",
        "CHROMADB_CONNECT_TIMEOUT": "0.01",
        "CHROMADB_HOST": "127.0.0.1",
        "CHROMADB_PORT": "9",
        "DATABASE_URL": f"sqlite:///{tmp / 'app.db'}",
        "PANTHEON_DATA_DIR": str(tmp),
        "PANTHEON_DISABLE_MCP": "1",
        "PYTHONPATH": str(ROOT),
        "PYTHON_DOTENV_DISABLED": "1",
    })
    paths = json.dumps([p for p, _, _ in routes])
    result = subprocess.run([sys.executable, "-c", _PROBE, paths], cwd=str(ROOT),
                            env=env, capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stderr[-4000:]
    line = next((l for l in result.stdout.splitlines() if l.startswith("RESULT=")), None)
    assert line is not None, result.stdout[-4000:]
    return json.loads(line.removeprefix("RESULT="))


def test_the_probe_asks_for_something(routes):
    assert len(routes) >= 6, "a route check with no routes passes by finding nothing"


def test_every_route_the_probe_asks_for_exists(answered, routes):
    """404 means the path moved. The probe would report it as a failed deploy
    forever, which is the same thing as not checking."""
    gone = [p for p, _, _ in routes if answered[p]["status"] == 404]
    assert not gone, f"{gone} answer 404 — the probe is asking for paths this app does not serve"


def test_every_route_answers_what_the_probe_expects(answered, routes):
    wrong = [(p, answered[p]["status"], expected)
             for p, expected, _ in routes if answered[p]["status"] not in expected]
    assert not wrong, (
        "the deploy probe's table disagrees with the app:\n  "
        + "\n  ".join(f"{p} answered {got}, table says {'/'.join(map(str, want))}"
                      for p, got, want in wrong)
        + "\nUpdate `ROUTES` in scripts/pantheon-deploy — on purpose.")


def test_the_healthcheck_route_answers_without_a_session(answered):
    """The compose healthcheck depends on this and cannot log in.

    Driven rather than read off `AUTH_EXEMPT_EXACT`: the exemption set is one
    of three things that decide this (the set, `_is_auth_exempt`'s prefix and
    pattern arms, and the middleware order), and only the answer settles it.
    """
    health = answered["/api/health"]
    assert health["status"] == 200, (
        f"/api/health answered {health['status']} with AUTH_ENABLED=true. The "
        f"compose healthcheck probes it; behind the login wall it reports the "
        f"login page as a healthy container")
    assert json.loads(health["body"])["status"] == "healthy", (
        "the healthcheck parses this body and requires `status == healthy`")


def test_the_gated_routes_are_still_gated(answered):
    """The probe accepts 200 *or* 302 on `/` and `/docs` because auth can be
    off. That must not quietly become "this app serves its shell to anyone":
    with auth on, they redirect."""
    for path in ("/", "/docs"):
        assert answered[path]["status"] == 302, f"{path} answered {answered[path]['status']}"
        assert answered[path]["location"] == "/login"


def test_the_readiness_endpoint_is_behind_auth(answered):
    """`B441`, measured. Written to be an orchestrator's readiness probe and
    unreachable by one. Asserted rather than merely noted so that the day it is
    fixed, this fails and the row gets closed instead of forgotten."""
    assert answered["/api/ready"]["status"] == 401, (
        "/api/ready no longer answers 401 — if it is now exempt, the compose "
        "healthcheck can move from /api/health (liveness) to /api/ready "
        "(readiness), which is what B441 asks for")
