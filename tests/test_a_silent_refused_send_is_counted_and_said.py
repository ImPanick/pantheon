# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1021` — a send the network mode refuses is said even when the program says
nothing.

`B1011` reads a refused send out of what a program prints. **OpenBSD netcat
1.226 (Ubuntu's) prints nothing and exits 0** when its `nc -u` datagram is
refused — the kernel's EPERM is swallowed — so an agent waiting on an SNMP or
syslog reply read silence as "nothing answered". Re-measured here, under the
gate's real *internet* rules in a fresh network namespace: no output, exit 0,
and the counter now on the rule that refused it went 0 → 1. So the rules count
(`netrules.ruleset` puts `counter` on every reject), the gate and the daemon
report the count (`refused` / `network_refused`), and a routed command whose
output shows no refusal while the count rose carries the sentence — which says
that another command in flight counts too, because it does.

Driven (`Law 20`): the real rules and the real `nc` in a namespace where this
machine can make one; the real gate (`RunningGate`) reporting a count; and the
real dispatcher against the real test daemon, the count rising during the
routed command and not otherwise.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import src.agent_tools.workstation_tools as wt
from workstation import netrules as N
from test_the_agents_hands_are_in_the_workstation import (  # noqa: F401 — fixtures
    _call, _on, people, settings, ws)
from test_the_workstation_network_is_the_one_chosen import FakeNft, RunningGate, _point_at_gate

REPO = Path(__file__).resolve().parent.parent


# ── the rules count ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["internet", "none"])
def test_every_reject_rule_carries_a_counter(mode):
    text = N.ruleset(mode)
    rejects = [line for line in text.splitlines() if "reject" in line]
    assert rejects and all("counter reject" in line for line in rejects), rejects


def test_the_count_is_read_from_the_kernels_own_answer():
    listing = {"nftables": [
        {"table": {"family": "inet", "name": N.GATE_TABLE}},
        {"rule": {"expr": [{"match": {}}, {"counter": {"packets": 3, "bytes": 90}},
                           {"reject": {"type": "icmpx"}}]}},
        {"rule": {"expr": [{"counter": {"packets": 2, "bytes": 60}}, {"reject": {}}]}},
        {"rule": {"expr": [{"counter": {"packets": 99, "bytes": 1}}, {"accept": None}]}},
    ]}
    run = lambda argv, stdin=None: (0, json.dumps(listing), "")  # noqa: E731
    assert N.refused(N.GATE_TABLE, run=run, nft="nft") == 5
    gone = lambda argv, stdin=None: (1, "", "Error: No such file or directory")  # noqa: E731
    assert N.refused(N.GATE_TABLE, run=gone, nft="nft") == 0     # full: nothing to refuse
    broken = lambda argv, stdin=None: (1, "", "Error: Operation not permitted")  # noqa: E731
    assert N.refused(N.GATE_TABLE, run=broken, nft="nft") is None


# ── the real program, under the real rules ──────────────────────────────────

_NETNS = textwrap.dedent(r'''
    import os, subprocess, sys
    sys.path.insert(0, os.environ["REPO"])
    from workstation import netrules as N
    def sh(*a):
        subprocess.run(a, check=True, capture_output=True)
    sh("ip", "link", "set", "lo", "up")
    sh("ip", "link", "add", "d0", "type", "veth", "peer", "name", "d1")
    sh("ip", "link", "set", "d1", "up")
    sh("ip", "addr", "add", "10.9.9.2/24", "dev", "d0")
    sh("ip", "link", "set", "d0", "up")
    sh("ip", "route", "add", "default", "via", "10.9.9.1")
    N.apply(N.ruleset("internet"))
    before = N.refused(N.GATE_TABLE)
    nc = subprocess.run("echo hi | nc -u -w1 192.168.1.1 161", shell=True,
                        capture_output=True, text=True)
    after = N.refused(N.GATE_TABLE)
    print(json.dumps({"before": before, "after": after, "code": nc.returncode,
                      "out": nc.stdout + nc.stderr, "mode": N.in_force(N.GATE_TABLE)}))
''').replace("import os, subprocess, sys", "import json, os, subprocess, sys")


def _can_make_a_namespace() -> bool:
    if os.name != "posix" or not (shutil.which("unshare") and shutil.which("nft")
                                  and shutil.which("nc") and shutil.which("ip")):
        return False
    return subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _can_make_a_namespace(),
                    reason="needs unshare, nft, ip and nc to make a network namespace")
def test_nc_says_nothing_and_the_counter_is_the_witness(tmp_path):
    script = tmp_path / "netns.py"
    script.write_text(_NETNS)
    done = subprocess.run(["unshare", "-rn", sys.executable, str(script)], capture_output=True,
                          text=True, timeout=120, env={**os.environ, "REPO": str(REPO)})
    assert done.returncode == 0, done.stdout + done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["mode"] == "internet"
    # The measurement the row stands on: silent, and successful.
    assert (got["code"], got["out"]) == (0, "")
    assert wt.network_refusal_note("internet", got["out"],
                                   command="echo hi | nc -u -w1 192.168.1.1 161") is None
    # And what the rules saw.
    assert got["after"] == got["before"] + 1, got
    said = wt.silent_refusal_note("internet", got["before"], got["after"])
    assert said.startswith("Nothing in this command's output says so")
    assert "refused 1 send or connection" in said and "nc -u" in said
    assert "Another command running on this workstation at the same time counts too" in said


# ── what is said, and when nothing is ──────────────────────────────────────

@pytest.mark.parametrize("mode,before,after", [
    ("full", 0, 4), (None, 0, 4), ("internet", None, 4), ("internet", 4, None),
    ("internet", 4, 4), ("internet", 9, 2),   # reloaded meanwhile: the count started again
])
def test_no_rise_or_no_mode_says_nothing(mode, before, after):
    assert wt.silent_refusal_note(mode, before, after) is None


def test_under_none_it_names_the_none_mode():
    said = wt.silent_refusal_note("none", 0, 3)
    assert "refused 3 sends or connections" in said and "mode is none" in said


def test_the_count_is_taken_from_whoever_holds_the_mode():
    assert wt.refusals_from({"network_gate": {"mode": "internet", "refused": 7}}) == (7, "gate")
    assert wt.refusals_from({"network_enforcement": "accounts", "network_refused": 2}) == (2, "accounts")
    assert wt.refusals_from({"network_enforcement": "none"}) == (None, None)
    assert wt.refusals_from(None) == (None, None)


# ── through the real gate and the real dispatcher ──────────────────────────

class CountingNft(FakeNft):
    """`FakeNft`, whose reject counter is whatever `count` holds — a file the
    routed command writes to, standing in for a packet the rules refused (the
    test daemon itself runs under no rules)."""

    def __init__(self, count: Path):
        super().__init__()
        self.count = count

    def __call__(self, argv, stdin=None):
        code, out, err = super().__call__(argv, stdin)
        if argv[1:4] == ["-j", "list", "table"] and code == 0:
            listing = json.loads(out)
            try:
                n = int(self.count.read_text() or 0)
            except (OSError, ValueError):
                n = 0
            listing["nftables"].append({"rule": {"expr": [
                {"counter": {"packets": n, "bytes": 0}}, {"reject": {"type": "icmpx"}}]}})
            out = json.dumps(listing)
        return code, out, err


@pytest.fixture
def counting_gate(tmp_path, monkeypatch):
    count = tmp_path / "refused-count"
    count.write_text("0")
    g = RunningGate(tmp_path, nft=CountingNft(count))
    try:
        _point_at_gate(monkeypatch, tmp_path, g)
        yield g, count
    finally:
        g.close()


def test_the_gate_reports_its_count(counting_gate):
    g, count = counting_gate
    count.write_text("12")
    assert g.gate.health()["refused"] == 12


def test_a_silent_routed_command_whose_sends_were_refused_carries_the_sentence(
        ws, settings, people, counting_gate):
    """The row's `Verify:`, short of a real turn on a deployed workstation:
    under *internet*, a routed `bash` that prints nothing and succeeds, during
    which the rules' count rose, carries the sentence."""
    g, count = counting_gate
    _on(settings, ws, workstation_network="internet")
    _, r = _call("bash", f"echo 1 > {count}", "ann")
    assert r["ran_in"] == "workstation" and r["exit_code"] == 0, r
    assert g.nft.loaded == "internet", "the gate does not hold the mode"
    assert r["stdout"] == "" and r.get("stderr", "") == ""
    assert "refused 1 send or connection while it ran" in r["note"], r


def test_a_silent_command_the_rules_did_not_touch_carries_nothing(ws, settings, people,
                                                                   counting_gate):
    _g, count = counting_gate
    _on(settings, ws, workstation_network="internet")
    _, r = _call("bash", "true", "ann")
    assert r["exit_code"] == 0 and "note" not in r, r


def test_under_full_nothing_is_counted_or_said(ws, settings, people, counting_gate):
    _g, count = counting_gate
    _on(settings, ws, workstation_network="full")
    _, r = _call("bash", f"echo 1 > {count}", "ann")
    assert "note" not in r, r
