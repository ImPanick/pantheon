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


def _uses(module_path, names):
    """Names actually imported or called in a module, read with `ast`.

    Not a substring scan. The first version of the shell checks below searched
    the file text for `"subprocess"` and failed on `neighbours.py`'s own
    docstring, which says the word while explaining why it does not use one.
    That is `Law 20` — a test that greps a file is testing the file — and it is
    the fifth time in this project that my own prose has tripped one of my own
    tests.
    """
    tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            used |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            used.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Attribute):
            used.add(ast.unparse(node))
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg == "shell":
            used.add("shell=")
    return {n for n in names if n in used}



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
    found = _uses(_PKG / "server.py",
                  {"subprocess", "os.system", "os.popen", "shutil", "Popen", "shell="})
    assert found == set(), f"the agent's surface grew something that writes: {found}"


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
    # The population itself is pinned by
    # `test_every_target_route_is_gated_and_none_was_forgotten`, which owns that
    # question. Two copies of it means one goes stale, and this one did — it
    # said `{"/reach"}` and `P17-03` added `/dns` (`Law 13`).


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
    found = _uses(_PKG / "observe.py", {"subprocess", "os.system", "os.popen", "shell="})
    assert found == set(), f"the agent grew a shell: {found}"


# ── `P17-03`: the owner's original ask ──────────────────────────────────────
#
# "I wanted to make an agent perform and organize an ARP table on my network but
# it's stuck inside the docker sandbox." The container's neighbour table is the
# *bridge's* — three entries — and no flag makes the host's real ones appear in
# it, because they are not the container's neighbours. Topology, not permissions.

from netagent import neighbours as nbr  # noqa: E402

_LINUX_ARP = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.1      0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0
192.168.1.10     0x1         0x2         aa:bb:cc:dd:ee:0a     *        eth0
192.168.1.9      0x1         0x4         aa:bb:cc:dd:ee:09     *        eth0
192.168.1.77     0x1         0x0         00:00:00:00:00:00     *        eth0
10.0.0.5         0x1         0x2         aa:bb:cc:dd:ee:05     *        eth1
garbage line
"""


def _arp_file(tmp_path, body=_LINUX_ARP):
    path = tmp_path / "arp"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_the_neighbour_table_is_parsed(tmp_path):
    rows = nbr._linux_neighbours(_arp_file(tmp_path))
    assert [r["address"] for r in rows] == [
        "192.168.1.1", "192.168.1.10", "192.168.1.9", "10.0.0.5"]
    assert rows[0]["mac"] == "aa:bb:cc:dd:ee:01"
    assert rows[0]["interface"] == "eth0"


def test_an_incomplete_entry_is_not_a_device(tmp_path):
    """Flags `0x0` is an address the kernel asked about and got no answer for.
    Reporting it puts a phantom machine on the operator's list."""
    rows = nbr._linux_neighbours(_arp_file(tmp_path))
    assert "192.168.1.77" not in [r["address"] for r in rows]


def test_a_permanent_entry_is_distinguished_from_a_learned_one(tmp_path):
    rows = {r["address"]: r["type"] for r in nbr._linux_neighbours(_arp_file(tmp_path))}
    assert rows["192.168.1.9"] == "static"
    assert rows["192.168.1.1"] == "dynamic"


def test_the_list_is_in_numeric_address_order(monkeypatch):
    """Lexicographic order on dotted quads is how a device list becomes hard to
    read at exactly the point it gets long enough to matter: `.10` before `.9`.

    Driven through `neighbours()` rather than by calling `_sort_key`, because the
    first version did the latter and a mutation swapping the sort *inside*
    `neighbours()` survived it — the ingredient tested, the recipe not. Fourth
    time in this project.
    """
    scrambled = [{"address": a, "mac": "aa:bb:cc:dd:ee:01", "type": "dynamic"}
                 for a in ("192.168.1.100", "192.168.1.9", "192.168.1.10",
                           "192.168.1.2", "not-an-address")]
    monkeypatch.setattr(nbr.platform, "system", lambda: "Linux")
    monkeypatch.setattr(nbr, "_linux_neighbours", lambda *a, **k: list(scrambled))
    result = nbr.neighbours()
    assert [r["address"] for r in result["neighbours"]] == [
        "192.168.1.2", "192.168.1.9", "192.168.1.10", "192.168.1.100",
        "not-an-address"], "the neighbour list is not in numeric address order"
    assert result["count"] == 5


def test_an_unreadable_table_is_an_empty_list_not_a_crash():
    assert nbr._linux_neighbours("/nonexistent/arp") == []


def test_an_unsupported_platform_says_so_rather_than_returning_nothing(monkeypatch):
    """"No neighbours" and "I cannot see neighbours here" are completely
    different answers, and an operator reading a bare `[]` would take the first
    for the second."""
    monkeypatch.setattr(nbr.platform, "system", lambda: "Plan9")
    result = nbr.neighbours()
    assert result["supported"] is False
    assert result["neighbours"] == []
    assert "Plan9" in result["detail"]


def test_the_reader_uses_no_subprocess():
    """`arp -a` would be a shell and, on Windows, a localised human table.
    `GetIpNetTable` is the API `arp.exe` itself calls and returns a struct."""
    found = _uses(_PKG / "neighbours.py",
                  {"subprocess", "os.system", "os.popen", "shell="})
    assert found == set(), f"the neighbour reader grew a shell: {found}"
    code = (_PKG / "neighbours.py").read_text(encoding="utf-8")
    assert "GetIpNetTable" in code, "the Windows path no longer uses the Win32 API"
    assert "/proc/net/arp" in code, "the Linux path no longer reads the kernel's table"


def test_what_may_be_reported_is_the_allowlists(tmp_path):
    rows = nbr._linux_neighbours(_arp_file(tmp_path))
    allow = Allowlist(["192.168.1.0/24"])
    kept = nbr.filter_to(rows, allow.allows)
    assert [r["address"] for r in kept] == ["192.168.1.1", "192.168.1.10", "192.168.1.9"]
    assert "10.0.0.5" not in [r["address"] for r in kept]


def test_the_neighbour_route_says_what_it_withheld(gated):
    """A filtered list that looks complete is worse than a short one: an operator
    who allowed the wrong CIDR would conclude their network is empty rather than
    that their allowlist is wrong."""
    status, body = gated("/neighbours")
    assert status == 200
    for key in ("count", "seen_total", "withheld", "allowlist", "supported"):
        assert key in body, f"the neighbour answer does not report {key}"
    assert body["withheld"] == body["seen_total"] - body["count"]


def test_nothing_outside_the_allowlist_is_in_the_neighbour_answer(gated):
    status, body = gated("/neighbours")
    allow = Allowlist(["127.0.0.0/8"], ["nas.local"])
    for row in body["neighbours"]:
        assert allow.allows(row["address"]), f"{row['address']} leaked past the gate"


def test_a_reverse_lookup_of_an_allowed_address_works(gated):
    status, body = gated("/dns?target=127.0.0.1")
    assert status == 200
    assert body["direction"] == "reverse"


def test_a_forward_lookup_is_gated_because_it_is_an_outbound_channel(gated):
    """Resolving `<secret>.attacker.example.com` puts the secret in somebody's
    DNS logs without a single packet reaching the "target". So names go through
    the same gate as addresses."""
    status, body = gated("/dns?target=secret.attacker.example.com")
    assert status == 403
    assert "not in this agent's allowlist" in body["error"]


def test_a_missing_reverse_record_is_an_answer_not_a_failure():
    """Most home-network addresses have no PTR, and calling that an error would
    make the normal case look broken."""
    result = observe.resolve("192.0.2.123")
    assert result["direction"] == "reverse"
    assert result["name"] is None
    assert "no reverse record" in result["detail"]


def test_every_target_route_is_gated_and_none_was_forgotten():
    """The population, so a seventh route cannot quietly join without a target
    check. `TARGET_ROUTES` is the only way a route receives one."""
    from netagent import server as srv
    assert set(srv.TARGET_ROUTES) == {"/reach", "/dns"}
    plain = set(srv._routes(Allowlist()))
    assert plain == {"/health", "/whoami", "/networks", "/neighbours"}
    assert plain.isdisjoint(srv.TARGET_ROUTES), "a route is in both tables"
