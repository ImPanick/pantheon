# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B543` — one function decides admin.

Measured 2026-09-18 while building `.pantheon/P11-AUTH-MAP.md`: the admin gate
was written four times. `core.middleware.require_admin` was one;
`routes/auth_routes.py` wrote `_get_current_user` + `auth_manager.is_admin` out
by hand at 21 gates — the whole user-administration surface, invisible to any
audit that greps for `require_admin`; `routes/shell_routes.py` kept its own
`_require_admin`, which also refused a bearer token's `api`; and
`owner_is_admin` answered the same question for callers with no
request. The first two are folded into `require_admin` now, which says the
shell's `api` refusal itself.

Driven: the real app booted out of process with an admin, a member and nobody,
asking the user-administration routes and the shell's; and the checker's own
rule C asked about both files.
"""
import importlib.util
from pathlib import Path

import pytest

from tests.helpers.gated_app import gated_app_probe
from tests.helpers.signed_in import ADMIN, MEMBER, PersonRequest, people

ROOT = Path(__file__).resolve().parents[1]

_PROBE = r'''
from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN
import routes.shell_routes as shell_routes

ran = []
async def _exec(cmd, timeout=None, **kw):
    ran.append(cmd)
    return {"stdout": "", "stderr": "", "exit_code": 0}
shell_routes._exec_shell = _exec

def loopback(owner):
    h = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
    if owner:
        h["X-Pantheon-Owner"] = owner
    return TestClient(app_module.app, client=("127.0.0.1", 50000)), h

ASK = (
    ("GET", "/api/auth/users", None),
    ("PUT", "/api/auth/open-signup", {"enabled": False}),
    ("GET", "/api/auth/settings/flag-sources", None),
    ("GET", "/api/auth/integrations", None),
    ("POST", "/api/shell/exec", {"command": "true"}),
)
for label, who in (("anonymous", None), ("member", MEMBER), ("admin", ADMIN)):
    c = client(who)
    RESULT[label] = {f"{m} {p}": c.request(m, p, json=body).status_code for m, p, body in ASK}
c, h = loopback(MEMBER)
RESULT["member's loopback"] = {f"{m} {p}": c.request(m, p, json=body, headers=h).status_code
                               for m, p, body in ASK}
RESULT["ran"] = len(ran)
'''


@pytest.fixture(scope="module")
def answered(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("one-gate"), _PROBE)


def test_nobody_is_asked_to_sign_in(answered):
    assert set(answered["anonymous"].values()) == {401}, answered["anonymous"]


def test_a_member_is_refused_by_every_admin_route(answered):
    assert set(answered["member"].values()) == {403}, answered["member"]


def test_a_members_assistant_is_asked_about_the_member(answered):
    """`B1175`'s rule, now on routes that used to read only the cookie."""
    assert set(answered["member's loopback"].values()) == {403}, answered["member's loopback"]


def test_the_admin_is_answered(answered):
    assert set(answered["admin"].values()) == {200}, answered["admin"]
    # The admin's shell exec reached the (stubbed) shell once; nobody else's did.
    assert answered["ran"] == 1


def test_a_bearer_tokens_api_is_never_an_admin(tmp_path):
    """The refusal `routes/shell_routes.py` kept its own copy of the gate for,
    said by `require_admin` — even against a store that would answer yes."""
    from fastapi import HTTPException
    from core.middleware import require_admin

    manager = people(tmp_path)
    manager.is_admin = lambda name: True   # a store that answers yes to anyone
    with pytest.raises(HTTPException) as err:
        require_admin(PersonRequest("api", manager))
    assert err.value.status_code == 403
    assert require_admin(PersonRequest(ADMIN, manager)) is None


def _checker():
    spec = importlib.util.spec_from_file_location("check_auth_map_b543", ROOT / ".pantheon" / "check-auth-map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_two_files_ask_require_admin_and_nothing_else():
    """Rule C over the two files: the shell's copy is gone, and the one call
    left in `auth_routes.py` is the scrub in `GET /api/auth/settings` — an
    exempt read that answers everybody, not a gate."""
    checker = _checker()
    others = checker.other_admin_gates(ROOT, ["routes/auth_routes.py", "routes/shell_routes.py"])
    assert len(others) == 1 and others[0].startswith("routes/auth_routes.py:"), others
    sites = {(s.file, s.func) for s in checker.require_admin_sites(
        ROOT, ["routes/auth_routes.py", "routes/shell_routes.py"])}
    for func in ("list_users", "admin_create_user", "set_user_admin", "admin_delete_user",
                 "set_settings", "create_integration"):
        assert ("routes/auth_routes.py", func) in sites, func
    for func in ("shell_exec", "shell_stream", "install_system_deps", "rebuild_engine"):
        assert ("routes/shell_routes.py", func) in sites, func
    # `B683`: `set_features` and `list_packages` are the operator tier's, and
    # ask the operator gate — still one gate's answer, never a hand-rolled one.
    operator = {(s.file, s.func) for s in checker.require_operator_sites(
        ROOT, ["routes/auth_routes.py", "routes/shell_routes.py"])}
    assert ("routes/auth_routes.py", "set_features") in operator
    assert ("routes/shell_routes.py", "list_packages") in operator
