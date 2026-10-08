# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B541` — hardware detection, here or over SSH on a host the caller names,
is an admin's act.

`GET /api/hwfit/system`, `/models`, `/profiles` and `/image-models` take
`host` and `ssh_port`, run them through the SSRF validators and hand them to
`detect_system`, which runs its probes over SSH. `AuthMiddleware` was the whole
gate. Measured 2026-10-02 against the real app with `AUTH_ENABLED=true`: a
signed-in non-admin got **200 from all four, and detection ran each time**;
`/profiles` also reached `run_ssh_command` through `_inspect_model_path`. With
no host the same helper runs `bash -lc 'test -d <path>'` on the serving host,
so `/profiles?model_path=…` told any signed-in account whether a directory
exists there. One directory over, `GET /api/cookbook/gpus` asks the same
question behind `require_admin`, and `_require_cookbook_scope` writes the
reason down: cookbook surfaces expose host topology.

**The adversary** (`Law 17`) is a second account on the box steering it at the
operator's other machines — not an SSRF row: the validators constrain the
target, and LAN-to-LAN reach between the operator's own boxes is normal. What
was wrong is who may choose the target.

**Why admin.** It is host topology, and the choice of which box this instance
opens SSH to — the operator's job (`P11-AUTH-MAP.md` § A, `operator`). The
Forge is the only caller in the product and its other reads are admin-only
already. **A single-user owner keeps it**: the first account is the admin, and
with auth off `require_admin` returns — both driven below.

The gate sits on the router, so a fifth `/api/hwfit` route is gated on the
commit that adds it; § E of the auth map holds every route in the tree that
reaches a caller-named host to the same rule.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.hwfit_routes import setup_hwfit_routes
from tests.helpers.gated_app import gated_app_probe

_ROUTES = ("/api/hwfit/system", "/api/hwfit/models",
           "/api/hwfit/profiles", "/api/hwfit/image-models")

_PROBE = r'''
import types
import services.hwfit.hardware as hardware
import routes.hwfit_routes as hwfit

# Nothing really runs. Each stub records that the route got as far as asking —
# which is the event the gate exists to prevent — and answers like a small box.
seen = {"detect": [], "ssh": [], "local": []}

def _detect(host="", ssh_port="", platform="", fresh=False):
    seen["detect"].append(host)
    return {"has_gpu": False, "gpu_name": None, "gpu_vram_gb": 0, "gpu_count": 0,
            "gpus": [], "gpu_groups": [], "total_ram_gb": 16, "available_ram_gb": 12,
            "backend": "cpu_x86"}

def _ssh(host, *args, **kwargs):
    seen["ssh"].append(host)
    return types.SimpleNamespace(returncode=1, stdout="", stderr="")

def _local(argv, *args, **kwargs):
    seen["local"].append(" ".join(argv))
    return types.SimpleNamespace(returncode=1, stdout="", stderr="")

# The handlers import `detect_system` from the module at call time, and
# `_run_model_probe` looks `run_ssh_command` and `subprocess` up in its own
# module's globals — so these are the names the real routes reach.
hardware.detect_system = _detect
hwfit.run_ssh_command = _ssh
hwfit.subprocess = types.SimpleNamespace(run=_local)

ROUTES = %(routes)r
REMOTE = {"host": "alice@10.0.0.5", "ssh_port": "22",
          "model": "Qwen2.5-7B-Instruct", "model_path": "/models/qwen"}

def ask(who, path, params):
    before = {k: len(v) for k, v in seen.items()}
    res = client(who).get(path, params=params, follow_redirects=False)
    try:
        body = res.json()
    except Exception:
        body = res.text[:200]
    return {"status": res.status_code, "body": body,
            "ran": {k: len(v) - before[k] for k, v in seen.items()}}

for label, who in CALLERS:
    RESULT[label] = {path: ask(who, path, REMOTE) for path in ROUTES}

# The local leg: no host, a path on the serving host.
RESULT["member_local_path"] = ask(MEMBER, "/api/hwfit/profiles",
                                  {"model": "x", "model_path": "/etc"})
RESULT["admin_local_path"] = ask(ADMIN, "/api/hwfit/profiles",
                                 {"model": "x", "model_path": "/etc"})
# A malformed query from a refused caller: the gate answers before validation.
RESULT["member_malformed"] = ask(MEMBER, "/api/hwfit/models", {"limit": "lots"})
# An option-shaped host: refused for the member by the gate, and for the admin
# by the SSRF validator that still runs behind it (`FORBIDDEN.md` Part 2).
RESULT["member_option_host"] = ask(MEMBER, "/api/hwfit/system", {"host": "-oProxyCommand=sh"})
RESULT["admin_option_host"] = ask(ADMIN, "/api/hwfit/system", {"host": "-oProxyCommand=sh"})
# The route `B541` names as the reference answer, asked by the same member.
RESULT["member_cookbook_gpus"] = ask(MEMBER, "/api/cookbook/gpus", {"host": "alice@10.0.0.5"})
''' % {"routes": _ROUTES}


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b541"), _PROBE)


def test_the_probe_is_gated_and_the_accounts_are_what_they_say(probe):
    assert probe["premise"] == {
        "auth_enabled": True, "localhost_bypass": False,
        "admin_is_admin": True, "member_is_admin": False,
    }, probe["premise"]


def test_a_non_admin_cannot_point_the_instance_at_a_host(probe):
    """`B541`'s premise, per route. Fails on the tree before the fix with 200
    from all four and detection run every time."""
    for path in _ROUTES:
        row = probe["member"][path]
        assert row["status"] == 403, (path, row)
        assert row["ran"] == {"detect": 0, "ssh": 0, "local": 0}, (path, row)


def test_the_four_answer_a_non_admin_the_way_cookbook_gpus_does(probe):
    """`B541`'s `Verify:`, word for word: the same status and the same body as
    the admin-only route that asks the same question."""
    reference = probe["member_cookbook_gpus"]
    assert reference["status"] == 403, reference
    for path in _ROUTES:
        row = probe["member"][path]
        assert (row["status"], row["body"]) == (reference["status"], reference["body"]), path


def test_the_serving_host_is_not_a_directory_oracle_for_a_non_admin(probe):
    """The leg the row does not name. `/profiles?model_path=/etc` with no host
    answered a non-admin whether `/etc` exists on the serving host — "config.json
    not found" for a directory, "not visible" for nothing there — by running
    `bash -lc 'test -d …'` locally."""
    row = probe["member_local_path"]
    assert row["status"] == 403, row
    assert row["ran"] == {"detect": 0, "ssh": 0, "local": 0}, row


def test_a_caller_with_no_session_is_stopped_before_the_route(probe):
    for path in _ROUTES:
        row = probe["anonymous"][path]
        assert row["status"] == 401, (path, row)
        assert row["ran"] == {"detect": 0, "ssh": 0, "local": 0}, (path, row)


def test_the_admin_still_probes_a_named_host(probe):
    """`Law 1`. The Forge's Fit tab and serve profiles work exactly as before for
    the operator — detection asked once per route, of the host named."""
    for path in _ROUTES:
        row = probe["admin"][path]
        assert row["status"] == 200, (path, row)
        assert row["ran"]["detect"] == 1, (path, row)
    # `/profiles` also inspected the model folder over SSH on the named host.
    assert probe["admin"]["/api/hwfit/profiles"]["ran"]["ssh"] >= 1
    assert probe["admin_local_path"]["status"] == 200
    assert probe["admin_local_path"]["ran"]["local"] >= 1


def test_the_gate_answers_before_the_query_is_read(probe):
    """A dependency on the router is resolved before FastAPI validates the
    query, so a refused caller cannot use parameter errors to learn the route's
    shape, and reaches no validator."""
    assert probe["member_malformed"]["status"] == 403, probe["member_malformed"]
    assert probe["member_option_host"]["status"] == 403, probe["member_option_host"]


def test_the_ssrf_validators_still_stand_behind_the_gate(probe):
    """`FORBIDDEN.md` Part 2: the gate is added in front of the validators,
    never instead of them. An admin naming an option-shaped host is refused
    and nothing is run."""
    row = probe["admin_option_host"]
    assert row["status"] == 400, row
    assert row["ran"] == {"detect": 0, "ssh": 0, "local": 0}, row


def _detect(host="", ssh_port="", platform="", fresh=False):
    return {"has_gpu": False, "gpus": [], "gpu_groups": [], "total_ram_gb": 8,
            "available_ram_gb": 8, "backend": "cpu_x86"}


def test_a_single_user_install_still_reads_its_hardware(monkeypatch, tmp_path):
    """A single-user install's owner — its first account, the admin, signed in —
    still sees the box the Forge runs on. Before `D-2026-10-07-02` §2 this was
    `AUTH_ENABLED=false`, nobody and no middleware; with the variable still set,
    nobody is refused now."""
    import services.hwfit.hardware as hardware
    from tests.helpers.signed_in import ADMIN, as_person, people
    monkeypatch.setattr(hardware, "detect_system", _detect)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    manager = people(tmp_path / "auth", members=())
    app = as_person(FastAPI(), ADMIN, auth_manager=manager)
    app.include_router(setup_hwfit_routes())
    res = TestClient(app).get("/api/hwfit/system")
    assert res.status_code == 200, res.text
    assert res.json()["total_ram_gb"] == 8
    nobody = as_person(FastAPI(), None, auth_manager=manager)
    nobody.include_router(setup_hwfit_routes())
    assert TestClient(nobody).get("/api/hwfit/system").status_code == 403


def test_the_gate_is_the_router_s_own_and_not_only_the_middleware_s(monkeypatch):
    """With auth on and nothing in front of the router, it refuses by itself."""
    import services.hwfit.hardware as hardware
    asked = []
    monkeypatch.setattr(hardware, "detect_system",
                        lambda **kw: asked.append(kw) or _detect())
    monkeypatch.setenv("AUTH_ENABLED", "true")
    app = FastAPI()
    app.include_router(setup_hwfit_routes())
    client = TestClient(app)
    for path in _ROUTES:
        res = client.get(path, params={"host": "alice@10.0.0.5"})
        assert res.status_code == 403, (path, res.text)
    assert asked == []
