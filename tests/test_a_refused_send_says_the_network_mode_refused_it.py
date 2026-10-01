# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1011` — a UDP send refused by the workstation's network mode is explained.

`B977` reads the TCP refusals (*No route to host*, *Couldn't connect to server*)
and the unresolved names. A UDP send the gate refuses fails with EPERM —
*Operation not permitted* — which a file permission error also says, so it was
not read at all: an agent probing SNMP on the router, or sending an mDNS query,
under *internet only* was told nothing. **Measured 2026-10-01 under the gate's
real rules** (`netrules.ruleset` loaded with nft into a fresh network namespace
with a default route; kernel 6.18, Python 3.11, bash 5.2, OpenBSD netcat 1.226):

* Python quotes the send above `PermissionError: [Errno 1] Operation not
  permitted`, and nothing follows the words — a file operation's EPERM ends with
  the file's name (`os.chown`: `…not permitted: '/path'`). So a send is read
  where the traceback's line is a send and the error names no file;
* bash's `/dev/udp` write prints `write error: Operation not permitted` — exactly
  what a write a file refuses prints — so it is read only when the command
  itself writes to `/dev/udp/`, whose address is the command's;
* **`nc -u` prints nothing and exits 0**, with or without `-v`: nothing in its
  result shows the refusal, so nothing is said (filed; only the gate's own
  counters could tell it).

Driven (`Law 20`): the sentence from each measured output; through the real
dispatcher against the real daemon and a real gate holding the mode (`P20-06`'s
`RunningGate`, as `B977`'s file does — the test daemon runs here under no rules,
so the routed program prints what the measured one printed); the real agent loop;
and, where this machine allows it (root, `unshare`, `nft`, `/dev/net/tun`), the
real programs under the real rules in a fresh network namespace, their output
and command fed to the same function.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import src.agent_tools.workstation_tools as wt
from src.workstation_client import account_for
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _on, people, settings, ws)
from test_the_workstation_network_is_the_one_chosen import RunningGate, _point_at_gate

REPO = Path(__file__).resolve().parent.parent

# What the programs printed under the real rules (the run file's path is the
# daemon's, as `B977`'s are).
RUN = "/home/pw-ann/.cache/pantheon-run/x.py"
PY_SENDTO = ("Traceback (most recent call last):\n"
             f"  File \"{RUN}\", line 3, in <module>\n"
             "    s.sendto(b'x', ('192.168.1.1', 161))\n"
             "PermissionError: [Errno 1] Operation not permitted")
PY_MDNS = ("Traceback (most recent call last):\n"
           f"  File \"{RUN}\", line 3, in <module>\n"
           "    s.sendto(b'x', ('224.0.0.251', 5353))\n"
           "PermissionError: [Errno 1] Operation not permitted")
PY_CONNECT_SEND = ("Traceback (most recent call last):\n"
                   f"  File \"{RUN}\", line 4, in <module>\n"
                   "    s.send(b'x')\n"
                   "PermissionError: [Errno 1] Operation not permitted")
# `n = 1 + s.sendto(…)`: Python 3.11 marks the call under the line it quotes.
PY_CARET = ("Traceback (most recent call last):\n"
            f"  File \"{RUN}\", line 3, in <module>\n"
            "    n = 1 + s.sendto(b'x', ('192.168.1.1', 161))\n"
            "            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
            "PermissionError: [Errno 1] Operation not permitted")
PY_CHOWN = ("Traceback (most recent call last):\n"
            f"  File \"{RUN}\", line 4, in <module>\n"
            "    os.chown('/home/pw-ann/owned', 65534, 65534)\n"
            "PermissionError: [Errno 1] Operation not permitted: '/home/pw-ann/owned'")
BASH_UDP = "bash: line 1: echo: write error: Operation not permitted"
DEV_UDP = "echo hi > /dev/udp/192.168.1.1/161"


def _private(address="192.168.1.1", kind="a private address"):
    return wt.NETWORK_SEND_NOTE.format(address=address, kind=kind)


# ── the sentence, from the output ────────────────────────────────────────────


def test_pythons_refused_sendto_is_said_to_be_the_mode():
    """The row's `Verify:`, from what the program printed."""
    note = wt.network_refusal_note("internet", "", PY_SENDTO)
    assert note == _private()
    assert note.startswith("192.168.1.1 is a private address, and this workstation's network "
                           "mode is internet only (an admin's setting)")
    assert "not a file permission" in note


def test_the_line_python_marks_under_the_send_is_read_past():
    assert wt.network_refusal_note("internet", PY_CARET) == _private()


def test_a_send_in_an_output_whose_connection_was_somebody_elses_is_still_read():
    """A refused connection to a public address is not the mode's; a refused
    send to a private one in the same output is."""
    public_curl = ("curl: (7) Failed to connect to 1.1.1.1 port 80 after 0 ms: "
                   "Couldn't connect to server")
    assert wt.network_refusal_note("internet", public_curl) is None
    assert wt.network_refusal_note("internet", public_curl + "\n" + PY_SENDTO) == _private()


def test_a_send_that_names_its_address_beats_a_connection_that_names_none():
    urllib = "urllib.error.URLError: <urlopen error [Errno 113] No route to host>"
    assert wt.network_refusal_note("internet", urllib) == wt.NETWORK_INTERNET_NOTE
    assert wt.network_refusal_note("internet", urllib + "\n" + BASH_UDP,
                                   command="python3 fetch.py\n" + DEV_UDP) == _private()


def test_an_mdns_query_is_said_to_go_to_a_multicast_address():
    assert wt.network_refusal_note("internet", PY_MDNS) == _private("224.0.0.251",
                                                                     "a multicast address")


def test_a_send_whose_line_names_no_address_says_what_the_mode_refuses_and_no_more():
    # `s.connect(addr)` then `s.send(…)`: the traceback quotes the send only.
    assert wt.network_refusal_note("internet", PY_CONNECT_SEND) == wt.NETWORK_SEND_INTERNET_NOTE


def test_bashs_dev_udp_write_is_read_with_its_command():
    assert wt.network_refusal_note("internet", BASH_UDP, command=DEV_UDP) == _private()
    # A name: where it went is not known here.
    assert (wt.network_refusal_note("internet", BASH_UDP,
                                    command="echo hi > /dev/udp/router.lan/161")
            == wt.NETWORK_SEND_INTERNET_NOTE)


@pytest.mark.parametrize("output, command", [
    (PY_CHOWN, ""),                                   # a file's EPERM names the file
    ("Traceback (most recent call last):\n"
     f"  File \"{RUN}\", line 2, in <module>\n"
     "    os.kill(1, 9)\n"
     "PermissionError: [Errno 1] Operation not permitted", ""),   # no file, not a send
    ("Traceback (most recent call last):\n"
     f"  File \"{RUN}\", line 2, in <module>\n"
     "    spool.send(message)\n"
     "PermissionError: [Errno 1] Operation not permitted: '/var/spool/x'", ""),  # names a file
    (BASH_UDP, "echo 1 > /proc/sys/net/ipv4/ip_forward"),         # a file refused the write
    ("PermissionError: [Errno 1] Operation not permitted", ""),
    ("", "echo hi | nc -u -w1 192.168.1.1 161"),       # nc -u: silent, exit 0 (measured)
], ids=["chown", "kill", "send-named-file", "file-write", "bare", "nc-silent"])
def test_an_eperm_that_is_not_a_send_says_nothing(output, command):
    assert wt.network_refusal_note("internet", output, command=command) is None
    assert wt.network_refusal_note("none", output, command=command) is None


def test_a_refused_send_to_a_public_address_was_not_the_modes():
    public = PY_SENDTO.replace("192.168.1.1", "1.1.1.1")
    assert wt.network_refusal_note("internet", public) is None
    assert wt.network_refusal_note(
        "internet", BASH_UDP, command="echo hi > /dev/udp/1.1.1.1/161") is None


@pytest.mark.parametrize("output, command", [
    (PY_SENDTO, ""), (PY_SENDTO.replace("192.168.1.1", "1.1.1.1"), ""), (BASH_UDP, DEV_UDP),
])
def test_under_none_every_refused_send_is_the_mode(output, command):
    assert wt.network_refusal_note("none", output, command=command) == wt.NETWORK_NONE_NOTE


@pytest.mark.parametrize("mode", [None, "full"])
def test_without_a_narrowing_mode_held_nothing_is_said(mode):
    assert wt.network_refusal_note(mode, PY_SENDTO) is None
    assert wt.network_refusal_note(mode, BASH_UDP, command=DEV_UDP) is None


# ── through the dispatcher, against the real daemon and gate ────────────────


@pytest.fixture
def gate(tmp_path, monkeypatch):
    g = RunningGate(tmp_path)
    try:
        _point_at_gate(monkeypatch, tmp_path, g)
        yield g
    finally:
        g.close()


def _printing_python(text: str) -> str:
    return "import sys\nsys.stderr.write(" + json.dumps(text + "\n") + ")\nsys.exit(1)"


def test_a_routed_python_sendto_refused_under_internet_carries_the_sentence(ws, settings, people,
                                                                           gate):
    _on(settings, ws, workstation_network="internet")
    _, r = _call("python", _printing_python(PY_SENDTO), "ann")
    assert r["ran_in"] == "workstation" and r["exit_code"] != 0, r
    assert gate.nft.loaded == "internet", "the gate does not hold the mode"
    assert _private() in r["note"], r
    assert "Operation not permitted" in r["stderr"]          # the program's, untouched


def test_a_routed_bash_dev_udp_write_carries_it_from_its_command(ws, settings, people, gate):
    _on(settings, ws, workstation_network="internet")
    # `true ||`: the write is the command's, not sent from this machine (the
    # test daemon runs under no rules); the error is what bash printed under them.
    command = f"true || {DEV_UDP}\nprintf '%s\\n' {json.dumps(BASH_UDP)} >&2\nexit 1"
    _, r = _call("bash", command, "ann")
    assert r["ran_in"] == "workstation" and _private() in r["note"], r


def test_under_none_it_is_the_none_sentence(ws, settings, people, gate):
    _on(settings, ws, workstation_network="none")
    _, r = _call("python", _printing_python(PY_SENDTO), "ann")
    assert r["note"] == wt.NETWORK_NONE_NOTE


def test_a_file_permission_error_carries_nothing(ws, settings, people, gate):
    _on(settings, ws, workstation_network="internet")
    _, r = _call("python", _printing_python(PY_CHOWN), "ann")
    assert r["exit_code"] != 0 and "note" not in r, r


def test_the_agent_reads_it_on_a_real_turn(ws, settings, people, gate, monkeypatch):
    """The model's `python` block runs routed, and its next round is sent the
    sentence. (A real model's wording of its answer is not measured here.)"""
    import src.agent_loop as agent_loop
    _on(settings, ws, workstation_network="internet")
    monkeypatch.setattr(agent_loop, "get_mcp_manager", lambda: None, raising=False)
    monkeypatch.setattr(agent_loop, "estimate_tokens", lambda *a, **k: 10, raising=False)
    replies, sent = iter(["```python\n" + _printing_python(PY_SENDTO) + "\n```"]), []

    async def fake_stream(*a, **k):
        sent.append(json.dumps(a[1] if len(a) > 1 else k.get("messages"), default=str))
        yield f"data: {json.dumps({'delta': next(replies, 'Done.')})}\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(agent_loop, "stream_llm_with_fallback", fake_stream, raising=False)

    async def drain():
        return [c async for c in agent_loop.stream_agent_loop(
            "http://local.test/v1", "small-local-model",
            [{"role": "user", "content": "does the router answer SNMP? send to 192.168.1.1:161"}],
            max_rounds=2, owner="ann", session_id="s1", workspace=None,
            relevant_tools={"python"})]

    events = [json.loads(c[6:]) for c in asyncio.run(drain()) if c.startswith("data: {")]
    out = next(e for e in events if e.get("type") == "tool_output")
    assert (out["ran_in"], out["ran_as"]) == ("workstation", account_for("ann"))
    assert len(sent) == 2, "the model was not asked again with the result"
    assert "192.168.1.1 is a private address" in sent[1] and "not a file permission" in sent[1]
    assert "not a file permission" not in sent[0]


# ── the real programs, under the real rules, in a fresh network namespace ────
#
# Runs where this machine can make one (root, `unshare`, `nft`, `/dev/net/tun`)
# and skips elsewhere. The script refuses to load a rule unless the namespace it
# is in has nothing but `lo` — the host's own rules are never touched.

_NETNS = textwrap.dedent(r'''
    import fcntl, os, socket, struct, subprocess, sys
    sys.path.insert(0, os.environ["REPO"])
    from workstation import netrules as N
    assert [n for _, n in socket.if_nameindex()] == ["lo"], "not a fresh network namespace"
    ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    def up(name):
        ifr = struct.pack("16sH14x", name.encode(), 0)
        flags = struct.unpack("16sH14x", fcntl.ioctl(ctl, 0x8913, ifr))[1]
        fcntl.ioctl(ctl, 0x8914, struct.pack("16sH14x", name.encode(), flags | 0x41))
    def addr(name, ip, req):
        sin = struct.pack("HH4s8x", socket.AF_INET, 0, socket.inet_aton(ip))
        fcntl.ioctl(ctl, req, struct.pack("16s16s", name.encode(), sin))
    up("lo")
    tun = os.open("/dev/net/tun", os.O_RDWR)
    fcntl.ioctl(tun, 0x400454CA, struct.pack("16sH14x", b"tun0", 0x1001))
    addr("tun0", "10.99.0.2", 0x8916)
    addr("tun0", "255.255.255.0", 0x891C)
    up("tun0")
    # A default route out of tun0 (SIOCADDRT; struct rtentry, 64-bit).
    import ctypes
    class SA(ctypes.Structure):
        _fields_ = [("f", ctypes.c_ushort), ("d", ctypes.c_char * 14)]
    class RT(ctypes.Structure):
        _fields_ = [("p1", ctypes.c_ulong), ("dst", SA), ("gw", SA), ("mask", SA),
                    ("flags", ctypes.c_ushort), ("p2", ctypes.c_short), ("p3", ctypes.c_ulong),
                    ("p4", ctypes.c_void_p), ("metric", ctypes.c_short), ("dev", ctypes.c_char_p),
                    ("mtu", ctypes.c_ulong), ("win", ctypes.c_ulong), ("irtt", ctypes.c_ushort)]
    rt = RT(); rt.dst.f = rt.mask.f = socket.AF_INET; rt.flags = 1
    dev = ctypes.create_string_buffer(b"tun0"); rt.dev = ctypes.cast(dev, ctypes.c_char_p)
    fcntl.ioctl(ctl, 0x890B, bytes(rt))
    mode = os.environ["MODE"]
    N.apply(N.ruleset(mode, table=N.GATE_TABLE))
    assert N.in_force(N.GATE_TABLE) == mode
    # The file `chown` is refused on sits where uid 65534 can reach it, so the
    # error is the operation's (EPERM), not the path's (EACCES).
    import shutil, tempfile
    shared = tempfile.mkdtemp(prefix="b1011-")
    os.chmod(shared, 0o755)
    def probe(name, argv, command=""):
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        print("<<<" + name + "\t" + str(r.returncode) + "\t" + command)
        print((r.stdout + r.stderr).rstrip())
        print(">>>")
    files = {
        "sendto": "import socket\ns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
                  "s.sendto(b'x', ('192.168.1.1', 161))\n",
        "caret": "import socket\ns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
                 "n = 1 + s.sendto(b'x', ('192.168.1.1', 161))\n",
        "mdns": "import socket\ns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
                "s.sendto(b'x', ('224.0.0.251', 5353))\n",
        "public": "import socket\ns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
                  "s.sendto(b'x', ('1.1.1.1', 161))\nprint('sent')\n",
        "chown": "import os\nopen(%r, 'w').close()\nos.setuid(65534)\nos.chown(%r, 0, 0)\n"
                 % (shared + "/owned", shared + "/owned"),
    }
    for name, src in files.items():
        path = os.path.join(shared, name + ".py")
        open(path, "w").write(src)
        os.chmod(path, 0o644)
        probe(name, [sys.executable, path])
    shutil.rmtree(shared)
    probe("dev_udp", ["bash", "-c", "echo hi > /dev/udp/192.168.1.1/161"],
          "echo hi > /dev/udp/192.168.1.1/161")
    if subprocess.run(["sh", "-c", "command -v nc"], capture_output=True).returncode == 0:
        probe("nc", ["sh", "-c", "echo hi | nc -u -w1 192.168.1.1 161"],
              "echo hi | nc -u -w1 192.168.1.1 161")
''')


def _can_make_a_namespace() -> bool:
    if os.name != "posix" or os.geteuid() != 0:
        return False
    if not (shutil.which("unshare") and shutil.which("nft") and os.path.exists("/dev/net/tun")):
        return False
    return subprocess.run(["unshare", "-n", "true"], capture_output=True).returncode == 0


def _probe(tmp_path, mode):
    script = tmp_path / "netns.py"
    script.write_text(_NETNS)
    done = subprocess.run(["unshare", "-n", sys.executable, str(script)], capture_output=True,
                          text=True, timeout=120,
                          env={**os.environ, "MODE": mode, "REPO": str(REPO)})
    assert done.returncode == 0, done.stdout + done.stderr
    got, name = {}, None
    for line in done.stdout.splitlines():
        if line.startswith("<<<"):
            name, code, command = line[3:].split("\t")
            got[name] = {"code": int(code), "command": command, "out": []}
        elif line == ">>>":
            name = None
        elif name:
            got[name]["out"].append(line)
    for v in got.values():
        v["out"] = "\n".join(v["out"])
    return got


@pytest.mark.skipif(not _can_make_a_namespace(),
                    reason="needs root, unshare, nft and /dev/net/tun to make a network namespace")
def test_what_the_real_programs_print_under_the_real_internet_rules_is_recognised(tmp_path):
    got = _probe(tmp_path, "internet")

    def note(name):
        return wt.network_refusal_note("internet", got[name]["out"], command=got[name]["command"])

    assert "Operation not permitted" in got["sendto"]["out"], got["sendto"]
    assert note("sendto") == _private()
    assert note("caret") == _private()
    assert note("mdns") == _private("224.0.0.251", "a multicast address")
    assert note("dev_udp") == _private()
    assert got["public"]["out"] == "sent" and note("public") is None
    assert "Operation not permitted: '" in got["chown"]["out"] and note("chown") is None
    if "nc" in got:   # measured: silent, exit 0 — nothing to read, nothing said
        assert (got["nc"]["code"], got["nc"]["out"], note("nc")) == (0, "", None)


@pytest.mark.skipif(not _can_make_a_namespace(),
                    reason="needs root, unshare, nft and /dev/net/tun to make a network namespace")
def test_and_under_the_real_none_rules(tmp_path):
    got = _probe(tmp_path, "none")
    for name in ("sendto", "mdns", "public", "dev_udp"):
        assert wt.network_refusal_note("none", got[name]["out"],
                                       command=got[name]["command"]) == wt.NETWORK_NONE_NOTE, name
    assert wt.network_refusal_note("none", got["chown"]["out"]) is None
