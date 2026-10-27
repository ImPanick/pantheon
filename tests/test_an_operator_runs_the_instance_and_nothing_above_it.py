# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B683` — a role can carry the operator's job, and only the operator's.

`.pantheon/P11-AUTH-MAP.md` tiered every `require_admin` site, and its
`operator` tier — models and endpoints, the Forge's serving, diagnostics and
logs, webhooks, the embeddings, the personal index, the workstation's machines
— is the work of keeping the box up. `P11-02` built roles as overlays on
`DEFAULT_PRIVILEGES`, and no key in it meant *may run the instance*, so a role
named `operator` was a name no gate read: all 66 sites asked `is_admin`.

`can_run_instance` is that key now (declared `False`; an admin holds it by
`B532`'s rule), and `core.middleware.require_operator` is the one gate that
reads it — `require_admin` asked first, unchanged, then the person's resolved
privileges. Every site of the tier moved onto it and § A of the map lost them;
the checker's rule G holds them to § G as rule A holds § A.

`Verify:` driven through the real app, out of process: a person holding the
`operator` role passes the gate in front of **every** route the map tiers
`operator` and the gate in front of **none** it tiers `superuser`. Each gate is
wrapped before the app is imported so that a route which passes its gate
stops there (418) instead of doing its work — a model download, a webhook
delivery, a shell — and a refusal is the real gate's 403. The populations are
derived from the map and the source by the checker's own functions, never
listed here, so a site added to either tier is asked on the commit that adds
it. A body-taking route is sent a body shaped from its own signature, because
FastAPI validates before a handler runs and a 422 proves nothing about a gate.

The `power-user` tier went with it: `GET /api/model-endpoints` and its models
answer anyone signed in — the endpoints they may use, with only the models
`allowed_models` lets them use.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from tests.helpers.gated_app import gated_app_probe
from tests.helpers.signed_in import ADMIN, MEMBER, PASSWORD, PersonRequest, people

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = "olive"


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_auth_map_b683", ROOT / ".pantheon" / "check-auth-map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _operator_install(tmp_path):
    """ada the admin, bob a member, olive a member holding the `operator` role."""
    manager = people(tmp_path, members=(MEMBER, OPERATOR))
    manager.define_role("operator", {"can_run_instance": True})
    manager.set_user_role(OPERATOR, "operator")
    return manager


# ── the gate, in process ─────────────────────────────────────────────────────

def test_the_key_is_declared_off_and_an_admin_holds_it():
    from core.auth import ADMIN_PRIVILEGES, DEFAULT_PRIVILEGES, OPERATOR_PRIVILEGE
    assert OPERATOR_PRIVILEGE == "can_run_instance"
    assert DEFAULT_PRIVILEGES[OPERATOR_PRIVILEGE] is False, "off until an admin grants it"
    assert ADMIN_PRIVILEGES[OPERATOR_PRIVILEGE] is True


def test_the_operator_role_passes_the_operator_gate_and_never_the_admin_one(tmp_path):
    from core.middleware import require_admin, require_operator

    manager = _operator_install(tmp_path)
    assert require_operator(PersonRequest(OPERATOR, manager)) is None
    assert require_operator(PersonRequest(ADMIN, manager)) is None
    with pytest.raises(HTTPException) as refused:
        require_admin(PersonRequest(OPERATOR, manager))
    assert refused.value.status_code == 403


def test_a_person_nobody_granted_it_is_told_who_may_and_where_the_switch_is(tmp_path):
    from core.middleware import OPERATOR_REFUSAL, require_operator

    manager = _operator_install(tmp_path)
    with pytest.raises(HTTPException) as refused:
        require_operator(PersonRequest(MEMBER, manager))
    assert refused.value.status_code == 403
    assert refused.value.detail == OPERATOR_REFUSAL
    assert "Settings" in OPERATOR_REFUSAL and "Run this instance" in OPERATOR_REFUSAL


def test_a_grant_to_one_person_works_and_taking_the_role_away_takes_it(tmp_path):
    from core.middleware import require_operator

    manager = _operator_install(tmp_path)
    assert manager.set_privileges(MEMBER, {"can_run_instance": True})
    assert require_operator(PersonRequest(MEMBER, manager)) is None
    manager.set_user_role(OPERATOR, None)
    with pytest.raises(HTTPException) as refused:
        require_operator(PersonRequest(OPERATOR, manager))
    assert refused.value.status_code == 403


def test_the_assistant_is_the_person_it_acts_for(tmp_path):
    """`B1175`'s rule at the new gate: a loopback naming a person is that
    person; a loopback naming nobody is Pantheon itself."""
    from core.middleware import INTERNAL_TOOL_HEADER, INTERNAL_TOOL_TOKEN, require_operator

    manager = _operator_install(tmp_path)

    def loopback(owner):
        request = PersonRequest(None, manager)
        request.headers = {INTERNAL_TOOL_HEADER: INTERNAL_TOOL_TOKEN}
        if owner:
            request.headers["X-Pantheon-Owner"] = owner
        return request

    assert require_operator(loopback(OPERATOR)) is None
    assert require_operator(loopback(None)) is None
    with pytest.raises(HTTPException) as refused:
        require_operator(loopback(MEMBER))
    assert refused.value.status_code == 403


def test_a_bearer_token_or_nobody_is_never_an_operator(tmp_path):
    from core.middleware import require_operator

    manager = _operator_install(tmp_path)
    manager.get_privileges = lambda name: {"can_run_instance": True}  # a store that says yes
    for who in ("api", None):
        with pytest.raises(HTTPException) as refused:
            require_operator(PersonRequest(who, manager))
        assert refused.value.status_code == 403, who


def test_a_store_that_cannot_be_read_refuses_the_member_and_keeps_the_admin_in(tmp_path):
    """`B531`, `D-2026-10-26-01` §1: refused, never granted — and the admin's
    way in does not go through the privilege store at all."""
    from core.middleware import require_operator

    manager = _operator_install(tmp_path)

    def broken(name):
        raise OSError("auth.json is unreadable")
    manager.get_privileges = broken
    with pytest.raises(HTTPException) as refused:
        require_operator(PersonRequest(OPERATOR, manager))
    assert refused.value.status_code == 503
    assert require_operator(PersonRequest(ADMIN, manager)) is None


# ── every site, through the real app ─────────────────────────────────────────

def _populations():
    """`(operator routes, superuser routes)` as `(file, handler)` pairs.

    Operator: every route in a § G file whose handler reaches
    `require_operator` — directly, through a helper in its module, or as a
    router- or route-level `Depends` (the checker's `route_reach`, the same
    closure rule E uses). Superuser: every § A row tiered `superuser` that is a
    route. Read out of the map and the source, never listed here."""
    cam = _checker()
    parsed = cam.parse_map((ROOT / ".pantheon" / "P11-AUTH-MAP.md").read_text(encoding="utf-8"))
    operator = set()
    for rel in sorted({key[0] for key in parsed.operator_sites}):
        tree = cam._parse(ROOT, rel)
        gate = cam.gate_aliases(tree, cam.OPERATOR_GATE)
        for node, _method, _path, reach in cam.route_reach(tree):
            if reach & gate:
                operator.add((rel, node.name))
    superuser = {key for key, row in parsed.sites.items()
                 if row["tier"] == "superuser" and row["route"] != "—"}
    return sorted(operator), sorted(superuser)


_PRELUDE = r'''
from fastapi import HTTPException, Request
import core.middleware as _mw

# Each gate, wrapped before any route module binds it: the real gate decides,
# and a caller it lets through is stopped here rather than handed the route.
_real_admin, _real_operator = _mw.require_admin, _mw.require_operator

def _admin_then_stop(request: Request):
    _real_admin(request)
    raise HTTPException(418, "passed require_admin")

def _operator_then_stop(request: Request):
    _real_operator(request)
    raise HTTPException(418, "passed require_operator")

_mw.require_admin = _admin_then_stop
_mw.require_operator = _operator_then_stop
'''

_PROBE = r'''
import re, typing
from fastapi.routing import APIRoute
from fastapi import params as fparams
from pydantic import BaseModel
from starlette.routing import Mount

_auth.create_user(OPERATOR, PASSWORD)
_auth.define_role("operator", {"can_run_instance": True})
_auth.set_user_role(OPERATOR, "operator")
_tokens[OPERATOR] = _auth.create_session_trusted(OPERATOR)

def every_route(node, prefix, seen):
    # This FastAPI keeps an included router nested (`_IncludedRouter`); walk it
    # as `.pantheon/check-unreachable.py` does, carrying the include prefix.
    for route in getattr(node, "routes", None) or []:
        if id(route) in seen or isinstance(route, Mount):
            continue
        seen.add(id(route))
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            ctx = getattr(route, "include_context", None)
            yield from every_route(inner, prefix + (getattr(ctx, "prefix", "") or ""), seen)

def sample(tp, metadata=()):
    """A value of type `tp` that also meets the length bounds a field declares."""
    origin = typing.get_origin(tp)
    if origin is typing.Annotated:
        return sample(typing.get_args(tp)[0], tuple(metadata) + typing.get_args(tp)[1:])
    if origin is typing.Union or type(tp).__name__ == "UnionType":
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return sample(args[0]) if args else None
    if origin in (list, tuple, set, frozenset):
        return []
    if origin is dict or tp is dict:
        return {}
    if origin is typing.Literal:
        return typing.get_args(tp)[0]
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return {name: sample(f.annotation, f.metadata) for name, f in tp.model_fields.items()
                if f.is_required()}
    if tp is bool:
        return False
    if tp in (int, float):
        return 1
    least = max([getattr(m, "min_length", 0) or 0 for m in metadata] or [0])
    return "x" * max(1, least)

def flat(dependant, kind):
    """Every `kind` parameter of a route and of each dependency under it."""
    out = list(getattr(dependant, kind))
    for sub in dependant.dependencies:
        out += flat(sub, kind)
    return out

def shaped(route):
    """A request this route's own signature accepts, so validation passes and
    the handler — and its gate — is reached."""
    kw = {}
    query = {f.alias: sample(f.field_info.annotation, f.field_info.metadata)
             for f in flat(route.dependant, "query_params")
             if f.field_info.is_required()}
    if query:
        kw["params"] = query
    params = flat(route.dependant, "body_params")
    body = [f for f in params if f.field_info.is_required()]
    forms = [f for f in params if isinstance(f.field_info, (fparams.Form, fparams.File))]
    if forms:
        data, files = {}, {}
        for f in forms:
            if isinstance(f.field_info, fparams.File):
                files[f.alias] = ("x.woff2", b"wOF2", "font/woff2")
            elif f.field_info.is_required():
                data[f.alias] = "x"
        kw["data"] = data
        if files:
            kw["files"] = files
    elif len(body) == 1 and not getattr(body[0].field_info, "embed", False):
        kw["json"] = sample(body[0].field_info.annotation, body[0].field_info.metadata)
    elif body:
        kw["json"] = {f.alias: sample(f.field_info.annotation, f.field_info.metadata) for f in body}
    return kw

def concrete(path):
    return re.sub(r"\{([^}:]+)(:[^}]*)?\}",
                  lambda m: "x.woff2" if m.group(1) == "filename" else "x", path)

POP = POPULATIONS
asked, matched = {}, {kind: set() for kind in POP}
for path, route in every_route(app_module.app, "", set()):
    code = getattr(route.endpoint, "__code__", None)
    if code is None:
        continue
    for kind, pairs in POP.items():
        for rel, func in pairs:
            if route.endpoint.__name__ == func and code.co_filename.endswith(rel):
                matched[kind].add(f"{rel}:{func}")
                kw = shaped(route)
                for method in sorted(route.methods - {"HEAD"}):
                    asked[f"{kind} {method} {path}"] = {
                        who: client(who).request(method, concrete(path), follow_redirects=False,
                                                 **kw).status_code
                        for who in (OPERATOR, MEMBER, ADMIN)}
RESULT["asked"] = asked
RESULT["unmatched"] = {kind: sorted(set(f"{r}:{f}" for r, f in POP[kind]) - matched[kind])
                       for kind in POP}
'''


@pytest.fixture(scope="module")
def answered(tmp_path_factory):
    operator, superuser = _populations()
    body = (f"OPERATOR, PASSWORD = {OPERATOR!r}, {PASSWORD!r}\n"
            f"POPULATIONS = {json.dumps({'operator': operator, 'superuser': superuser})}\n"
            + _PROBE)
    # `/metrics` is off by default and says 404 before any gate; on, it is the
    # operator's like the rest of diagnostics.
    return gated_app_probe(tmp_path_factory.mktemp("operator-gate"), body,
                           {"PANTHEON_METRICS_ENABLED": "1"}, prelude=_PRELUDE)


def _of(answered, kind):
    return {k.split(" ", 1)[1]: v for k, v in answered["asked"].items() if k.startswith(kind + " ")}


def test_every_route_of_both_tiers_was_found_in_the_app_and_asked(answered):
    """Not vacuous: each population is the map's, every pair is a live route,
    and the sizes are what the tiers hold — 66 operator sites, of which three
    are router-level or helper gates in front of several routes each."""
    assert answered["premise"]["auth_enabled"] is True
    assert answered["unmatched"] == {"operator": [], "superuser": []}, answered["unmatched"]
    assert len(_of(answered, "operator")) >= 67, len(_of(answered, "operator"))
    # `B1573` took the five integration routes out of the superuser tier (a
    # member owns their own connection now): 69 -> 64 sites in the map.
    assert len(_of(answered, "superuser")) >= 64, len(_of(answered, "superuser"))


def test_the_operator_role_reaches_every_site_the_map_tiers_operator(answered):
    """418 is the wrapped gate saying *passed*; anything else is a refusal or
    a route the gate never saw. The workstation's status is open to anyone
    signed in (its operator site only adds a view) and answers 200."""
    routes = _of(answered, "operator")
    status_route = "GET /api/workstation/status"
    assert routes.pop(status_route) == {OPERATOR: 200, MEMBER: 200, ADMIN: 200}
    wrong = {k: v for k, v in routes.items() if v != {OPERATOR: 418, MEMBER: 403, ADMIN: 418}}
    assert wrong == {}, wrong


#: The one superuser site whose gate *decides which* rather than refuses — the
#: map's own words (`B1130`): an admin dismisses a sent build, its sender
#: withdraws it. It asks `require_admin` inside a `try`, so the wrapped gate's
#: 418 reads there as "not an admin" for everyone and the route answers 404
#: (nothing was sent). What matters is the same: the operator gets the
#: member's answer.
_DECIDES_WHICH = {"DELETE /api/mcp/builds-sent/{sent_id}"}


def test_the_operator_role_reaches_none_the_map_tiers_superuser(answered):
    """The operator is answered exactly as a member is at every superuser
    route — refused by the real `require_admin` — and the admin passes."""
    routes = _of(answered, "superuser")
    assert _DECIDES_WHICH <= set(routes)
    wrong = {k: v for k, v in routes.items()
             if v[OPERATOR] != v[MEMBER]
             or (k not in _DECIDES_WHICH and v != {OPERATOR: 403, MEMBER: 403, ADMIN: 418})}
    assert wrong == {}, wrong


# ── the power-user tier: the endpoint list, per person ───────────────────────

_ENDPOINTS = r'''
import json as _json
from core.database import SessionLocal, ModelEndpoint
from src.auth_helpers import PRIVILEGE_STORE_SENTENCE  # noqa: F401  (imported: the module loads)

_auth.create_user(OPERATOR, PASSWORD)
_auth.define_role("operator", {"can_run_instance": True})
_auth.set_user_role(OPERATOR, "operator")
_tokens[OPERATOR] = _auth.create_session_trusted(OPERATOR)
assert _auth.set_privileges(MEMBER, {"allowed_models": ["m1"], "allowed_models_restricted": True})

db = SessionLocal()
db.add(ModelEndpoint(id="shared", name="Shared box", base_url="http://127.0.0.1:9/v1",
                     api_key="sk-shared-secret", is_enabled=True, owner=None,
                     cached_models=_json.dumps(["m1", "m2"])))
db.add(ModelEndpoint(id="adas", name="Ada's own", base_url="http://127.0.0.1:8/v1",
                     is_enabled=True, owner=ADMIN, cached_models=_json.dumps(["m1"])))
db.add(ModelEndpoint(id="other", name="Only m2", base_url="http://127.0.0.1:7/v1",
                     is_enabled=True, owner=None, cached_models=_json.dumps(["m2"])))
db.commit()
db.close()

def answer(who, path):
    r = client(who).get(path)
    return {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}

RESULT["list"] = {who: answer(who, "/api/model-endpoints") for who in (MEMBER, OPERATOR, ADMIN)}
RESULT["models"] = {who: answer(who, "/api/model-endpoints/shared/models") for who in (MEMBER, OPERATOR)}
RESULT["private"] = answer(MEMBER, "/api/model-endpoints/adas/models")
RESULT["status"] = {who: sorted(client(who).get("/api/workstation/status").json())
                    for who in (MEMBER, OPERATOR, ADMIN)}
'''


@pytest.fixture(scope="module")
def endpoints(tmp_path_factory):
    body = f"OPERATOR, PASSWORD = {OPERATOR!r}, {PASSWORD!r}\n" + _ENDPOINTS
    return gated_app_probe(tmp_path_factory.mktemp("endpoint-list"), body)


def test_a_person_sees_the_endpoints_and_models_they_may_use(endpoints):
    mine = endpoints["list"][MEMBER]
    assert mine["status"] == 200, mine
    by_id = {ep["id"]: ep for ep in mine["body"]}
    assert set(by_id) == {"shared"}, "not ada's own, not one with nothing bob may use"
    assert by_id["shared"]["models"] == ["m1"]
    assert "api_key_fingerprint" not in by_id["shared"] and "has_key" not in by_id["shared"]
    assert endpoints["models"][MEMBER]["status"] == 200
    assert [m["id"] for m in endpoints["models"][MEMBER]["body"]] == ["m1"]
    assert endpoints["private"]["status"] == 404


def test_whoever_runs_the_instance_sees_every_endpoint_as_before(endpoints):
    for who in (OPERATOR, ADMIN):
        answer = endpoints["list"][who]
        assert answer["status"] == 200, (who, answer)
        assert {ep["id"] for ep in answer["body"]} == {"shared", "adas", "other"}, who
        assert all("api_key_fingerprint" in ep for ep in answer["body"]), who
    assert [m["id"] for m in endpoints["models"][OPERATOR]["body"]] == ["m1", "m2"]


def test_the_workstation_status_shows_the_operator_the_admins_view(endpoints):
    status = endpoints["status"]
    assert "settings" in status[ADMIN] and "settings" in status[OPERATOR], status
    assert "settings" not in status[MEMBER], status
