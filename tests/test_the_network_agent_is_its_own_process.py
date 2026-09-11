# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-01`. The process that actually has the LAN.

Measured from inside the running container on the owner's machine: `1.1.1.1:53`
reachable, `192.168.1.1:80` TimeoutError. The agent had more reach to the public
internet than to the network it lives on, and for a project whose first law about
dependence is "we drop external dependence" that is exactly backwards.

**The container staying unable to reach the LAN is a feature.** The alternative
is handing LAN reach to a 2.9GB container that runs agent-authored code, which
puts the owner's network inside its blast radius by construction. So the
capability lives in a small process on the host and Pantheon holds a credential
rather than the capability.

These tests drive the real server over a real socket. A handler asserted about
rather than called is how an auth check gets deleted and nothing notices.
"""
import ast
import json
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from netagent import observe
from netagent.server import DEFAULT_BIND, DEFAULT_PORT, Handler, serve
from netagent.tokens import (
    TOKEN_ENTROPY_BYTES,
    TOKEN_PREFIX,
    bearer_credential,
    hash_token,
    load_or_create,
    mint_raw_token,
    token_matches,
)

_PKG = Path(__file__).resolve().parent.parent / "netagent"


# ── package rule 1: it runs on a host, so it carries nothing ────────────────

def test_the_agent_imports_nothing_from_the_application():
    """It runs on the operator's host, outside Docker. A host is not a place to
    install SQLAlchemy and a vector store so a laptop can list its own
    interfaces — and an agent that needs the app installed to run is not a
    separate process, it is the app with an extra port."""
    offenders = []
    for path in sorted(_PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root in {"src", "core", "routes", "services", "mcp_servers", "companion"}:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == [], f"the agent imports the application: {offenders}"


def test_the_agent_carries_no_third_party_dependency():
    """`Law 16` at the sharpest point it reaches: an operator installing this on
    their own machine should need nothing but Python."""
    import sys
    stdlib = set(sys.stdlib_module_names)
    offenders = []
    for path in sorted(_PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [])
            for name in names:
                root = name.split(".")[0]
                if root and root not in stdlib and root not in {"netagent", "__future__"}:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == [], f"the agent needs something installed: {offenders}"


def test_the_token_format_matches_the_applications():
    """Declared in two places on purpose — importing `core.api_tokens` would pull
    `core/__init__` and the whole app onto the host. This is the seam that
    duplication creates, and it is watched rather than hoped about."""
    from core.api_tokens import TOKEN_ENTROPY_BYTES as APP_BYTES
    from core.api_tokens import TOKEN_PREFIX as APP_PREFIX
    assert TOKEN_PREFIX == APP_PREFIX
    assert TOKEN_ENTROPY_BYTES == APP_BYTES


# ── the credential ──────────────────────────────────────────────────────────

def test_a_minted_token_verifies_and_a_different_one_does_not():
    raw = mint_raw_token()
    stored = hash_token(raw)
    assert token_matches(raw, stored)
    assert not token_matches(mint_raw_token(), stored)
    assert not token_matches("", stored)
    assert not token_matches(raw, "")


def test_the_raw_token_is_not_recoverable_from_what_is_stored():
    """The property that makes storing a hash worth doing. If the raw value were
    on disk, the file would be the credential and hashing it would be theatre."""
    state = Path(tempfile.mkdtemp())
    stored, raw = load_or_create(state)
    assert raw and raw.startswith(TOKEN_PREFIX)
    on_disk = (state / "token.json").read_text(encoding="utf-8")
    assert raw not in on_disk
    assert raw[8:] not in on_disk, "more than the display prefix survived"
    assert json.loads(on_disk)["hash"] == stored


def test_a_second_run_reuses_the_token_rather_than_minting_a_new_one():
    """A restart that silently invalidates the operator's pasted token is a
    support ticket that looks like a network fault."""
    state = Path(tempfile.mkdtemp())
    first_hash, first_raw = load_or_create(state)
    second_hash, second_raw = load_or_create(state)
    assert second_hash == first_hash
    assert second_raw is None, "the raw value cannot be re-shown; it is not stored"
    assert token_matches(first_raw, second_hash)


def test_a_corrupt_token_file_mints_rather_than_running_open():
    """Fail closed. A file that will not parse is not a reason to accept every
    caller — it is a reason to make the operator re-paste, which is a visible
    inconvenience rather than an invisible open door."""
    state = Path(tempfile.mkdtemp())
    (state / "token.json").write_text("{not json", encoding="utf-8")
    stored, raw = load_or_create(state)
    assert stored and raw, "a corrupt file left the agent with no credential"
    assert token_matches(raw, stored)


@pytest.mark.parametrize("header,ok", [
    ("Bearer {tok}", True),
    ("bearer {tok}", True),      # case-insensitive scheme; clients differ
    ("BEARER {tok}", True),
    ("Basic {tok}", False),
    ("{tok}", False),
    ("Bearer ", False),
    ("", False),
])
def test_only_a_bearer_credential_is_read(header, ok):
    tok = mint_raw_token()
    got = bearer_credential(header.replace("{tok}", tok))
    assert (got == tok) is ok


def test_an_absurdly_long_credential_is_refused_before_it_is_hashed():
    """Hashing a 4KB "token" on an unauthenticated path is free work for a
    stranger. The app's middleware bounds it the same way."""
    assert bearer_credential("Bearer " + TOKEN_PREFIX + "x" * 4000) is None


def test_the_comparison_is_constant_time():
    """Entropy makes brute force pointless; it does not make a timing oracle
    acceptable, and `==` on a hex digest is one."""
    src = (_PKG / "tokens.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "hmac.compare_digest" in code
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "token_matches")
    assert any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "compare_digest"
               for n in ast.walk(fn)), "token_matches does not compare in constant time"


# ── the server, driven over a socket ────────────────────────────────────────

@pytest.fixture
def agent():
    state = Path(tempfile.mkdtemp())
    _stored, raw = load_or_create(state)
    httpd = serve(bind="127.0.0.1", port=0, state_dir=state, serve_forever=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]

    def call(path, token=raw, method="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                     data=b"" if method == "POST" else None)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    yield call, raw
    httpd.shutdown()
    httpd.server_close()


def test_pantheon_reaches_the_agent(agent):
    """The first clause of the row's Verify."""
    call, _ = agent
    status, body = call("/health")
    assert status == 200
    assert body["agent"] == "pantheon-netagent"
    assert body["ok"] is True


def test_the_agent_reports_the_host_it_runs_on(agent):
    """The second clause. Whatever this returns, it is *this process's* view —
    which from a container is the bridge and from a host is the real segments.
    The same call, two answers, and only one of them useful."""
    call, _ = agent
    status, body = call("/whoami")
    assert status == 200
    assert body["hostname"] == socket.gethostname()
    kinds = {a.get("kind") for a in body["addresses"]}
    assert kinds, "the agent found no addresses at all"
    assert "unparseable" not in kinds


def test_every_route_needs_the_credential(agent):
    call, _ = agent
    for path in ("/health", "/whoami", "/networks"):
        assert call(path, token=None)[0] == 401, f"{path} answered without a token"
        assert call(path, token=mint_raw_token())[0] == 401, f"{path} took any token"


def test_an_unauthenticated_caller_cannot_map_the_routes(agent):
    """401 before the route lookup. Otherwise comparing 401 against 404 tells a
    stranger exactly which paths exist."""
    call, _ = agent
    assert call("/nope", token=None)[0] == 401
    assert call("/health", token=None)[0] == 401
    assert call("/nope")[0] == 404, "an authenticated caller should still get 404"


def test_the_agent_has_no_writer(agent):
    """`P17-05`: configuration is a separate risk class and does not ride in on
    observation. Bundling it here would mean the thing that describes your
    network can also break it."""
    call, _ = agent
    status, body = call("/health", method="POST")
    assert status == 405
    assert "read-only" in body["error"]


def test_the_route_table_holds_no_writer():
    """The test above proves POST is refused. This one proves nobody added a
    mutating GET — `Law 20`: the refusal is not the rule, the absence is."""
    src = (_PKG / "server.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    for smell in ("subprocess", "os.system", "shutil.rmtree", "open(", "Popen"):
        assert smell not in code, f"the agent's surface grew something that writes: {smell!r}"


def test_it_listens_on_loopback_unless_told_otherwise():
    """`Law 16`. Nothing listens beyond this machine unless a person said so —
    and on Docker Desktop making the container reach it is a deliberate act,
    not a default somebody inherits."""
    assert DEFAULT_BIND == "127.0.0.1"
    assert isinstance(DEFAULT_PORT, int) and DEFAULT_PORT > 1024


def test_the_server_does_not_advertise_its_python_version():
    assert Handler.sys_version == ""


# ── what it can see ─────────────────────────────────────────────────────────

def test_an_address_is_classified_so_a_reader_can_tell_a_lan_from_a_bridge():
    assert observe._classify("127.0.0.1")["kind"] == "loopback"
    assert observe._classify("192.168.1.71")["kind"] == "private"
    assert observe._classify("169.254.1.1")["kind"] == "link-local"
    assert observe._classify("8.8.8.8")["kind"] == "global"
    assert observe._classify("not-an-address")["kind"] == "unparseable"


def test_a_private_address_offers_the_network_an_operator_would_recognise():
    """So the Networks panel can say "here is what I can see; which of these do
    you mean" rather than "declare your networks" (`Law 15`)."""
    assert observe._classify("192.168.1.71")["assumed_network"] == "192.168.1.0/24"
    assert "assumed_network" not in observe._classify("8.8.8.8")
    assert "assumed_network" not in observe._classify("127.0.0.1")


def test_missing_ipv6_is_not_a_failure(monkeypatch):
    """`socket()` itself raises `EAFNOSUPPORT` when the family is unavailable —
    before any connect — so the guard has to wrap construction, not the call that
    looks risky. Found by running this in the very container it exists to
    differ from."""
    real = socket.socket

    def only_v4(family, *a, **kw):
        if family == socket.AF_INET6:
            raise OSError(97, "Address family not supported by protocol")
        return real(family, *a, **kw)

    monkeypatch.setattr(socket, "socket", only_v4)
    result = observe.whoami()
    assert result["hostname"]
    assert isinstance(result["addresses"], list)


# ── `P17-02`: the bound the gated party cannot widen ────────────────────────
#
# The allowlist lives HERE, not in Pantheon's settings, because Pantheon is the
# gated party and a gate the gated party can widen is not a gate. These drive the
# real server, because a gate asserted about rather than driven is a gate that
# gets refactored around.

from netagent.allowlist import Allowlist  # noqa: E402


@pytest.fixture
def gated():
    state = Path(tempfile.mkdtemp())
    _stored, raw = load_or_create(state)
    allow = Allowlist(["127.0.0.0/8"], ["nas.local"])
    httpd = serve(bind="127.0.0.1", port=0, state_dir=state,
                  serve_forever=False, allowlist=allow)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        req.add_header("Authorization", f"Bearer {raw}")
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    yield call
    httpd.shutdown()
    httpd.server_close()


def test_an_empty_allowlist_refuses_everything():
    """The shipped state, and it is not "allow all until configured". The whole
    argument of `P17-02` is that a target is refused *because it was never
    named*, and a list that starts open has no such answer to give."""
    empty = Allowlist()
    assert empty.is_empty()
    for target in ("127.0.0.1", "192.168.1.1", "8.8.8.8", "nas.local"):
        assert empty.allows(target) is False
    assert "no allowlist" in empty.refusal("127.0.0.1")
    assert "--allow" in empty.refusal("127.0.0.1"), "the refusal does not say what to do"


def test_a_target_outside_the_list_is_refused_at_the_agent(gated):
    """The row's first Verify clause: refused *at the agent*, not merely
    unasked-for."""
    status, body = gated("/reach?target=192.168.1.1")
    assert status == 403
    assert "not in this agent's allowlist" in body["error"]
    assert "cannot be changed from Pantheon" in body["error"]


@pytest.mark.parametrize("target", [
    "169.254.169.254",       # cloud metadata
    "10.0.0.1",
    "8.8.8.8",
    "evil.example.com",      # a name, and names match only by exact listing
    "192.168.1.255",
])
def test_nothing_outside_the_list_gets_through_however_it_is_phrased(gated, target):
    assert gated(f"/reach?target={target}")[0] == 403


def test_what_is_inside_the_list_works(gated):
    status, body = gated("/reach?target=127.0.0.1")
    assert status == 200
    assert body["target"] == "127.0.0.1"
    assert body["method"] == "tcp-connect"


def test_a_listed_name_works_and_is_case_insensitive():
    allow = Allowlist([], ["nas.local"])
    assert allow.allows("nas.local")
    assert allow.allows("NAS.LOCAL")
    assert not allow.allows("other.local")


def test_a_name_is_never_resolved_to_decide_membership():
    """`src/networks.py` gives the reason and it holds here: resolving would make
    membership depend on DNS answered by whichever network we happen to be on,
    which is the ambiguity an allowlist exists to remove."""
    allow = Allowlist(["127.0.0.0/8"])
    assert allow.allows("127.0.0.1")
    assert not allow.allows("localhost"), (
        "a name resolved to an allowed address — membership now depends on DNS")


def test_a_target_route_cannot_be_added_without_arriving_at_the_gate():
    """The dispatcher decides a route needs a target by its membership in
    `TARGET_ROUTES`, so a target route that forgot to check is not a shape this
    file has. Read structurally: the check must be in the branch that serves
    them."""
    from netagent import server as srv
    src = (_PKG / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "do_GET")
    branch = next((n for n in ast.walk(fn)
                   if isinstance(n, ast.If) and "TARGET_ROUTES" in ast.unparse(n.test)), None)
    assert branch is not None, "the dispatcher no longer routes targets through one branch"
    body = ast.unparse(branch)
    assert "allowlist.allows" in body, "the target branch does not consult the allowlist"
    assert "403" in body, "the target branch does not refuse"
    assert set(srv.TARGET_ROUTES) == {"/reach"}


def test_a_target_route_without_a_target_is_a_400_not_a_crash(gated):
    status, body = gated("/reach")
    assert status == 400
    assert "needs a ?target=" in body["error"]


def test_the_allowlist_is_readable_and_there_is_no_route_that_sets_it(gated):
    """Readable so the operator can see the boundary without guessing. Writable
    by nothing, which is `P17-02` in one sentence."""
    status, body = gated("/health")
    assert status == 200
    assert body["allowlist"]["cidrs"] == ["127.0.0.0/8"]
    src = (_PKG / "server.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "self.allowlist =" not in code, "something assigns the allowlist at request time"
    assert "do_PUT" not in code and "do_PATCH" not in code and "do_DELETE" not in code


def test_an_unparseable_cidr_is_recorded_rather_than_silently_dropped():
    """A typo in a security boundary that silently narrows it is the kindest
    possible failure and still the wrong one: the operator believes they named a
    network and nothing tells them otherwise. `P17-09`'s lesson, one layer over."""
    allow = Allowlist(["192.168.1.0/24", "10.9.0.0/48", "not-a-cidr"])
    assert [str(c) for c in allow.cidrs] == ["192.168.1.0/24"]
    assert allow.rejected == ["10.9.0.0/48", "not-a-cidr"]
    assert allow.as_dict()["rejected"] == ["10.9.0.0/48", "not-a-cidr"]


def test_the_command_line_beats_the_environment(monkeypatch):
    monkeypatch.setenv("PANTHEON_NETAGENT_ALLOW", "10.0.0.0/8")
    from_args = Allowlist.from_env_and_args(["192.168.1.0/24"])
    assert [str(c) for c in from_args.cidrs] == ["192.168.1.0/24"]
    from_env = Allowlist.from_env_and_args()
    assert [str(c) for c in from_env.cidrs] == ["10.0.0.0/8"]


def test_refused_is_a_live_host_and_is_not_collapsed_into_down():
    """The most common way a reachability check lies. "Connection refused" is a
    machine saying no; "timed out" is nothing there at all."""
    result = observe.reach("127.0.0.1", [1], timeout=0.4)
    verdicts = {p["result"] for p in result["ports"]}
    assert verdicts <= {"refused", "timeout", "open"} or any(
        v.startswith("error:") for v in verdicts)
    if "refused" in verdicts:
        assert result["alive"] is True, "a refusing host was reported as down"


def test_reachability_uses_no_shell():
    """`ping` would need a raw socket or a subprocess, and this package has
    neither a privilege story nor a shell — shelling out is one argument-quoting
    bug away from being one."""
    src = (_PKG / "observe.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    for smell in ("subprocess", "os.system", "os.popen", "shell=True"):
        assert smell not in code, f"the agent grew a shell: {smell!r}"
