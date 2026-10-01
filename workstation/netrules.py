# SPDX-License-Identifier: AGPL-3.0-or-later
"""The network mode as kernel rules — `P20-06`, `D-2026-09-30-03`.

One ruleset, written two ways: by the gate (`workstation/gate.py`) for every
process in the network namespace it owns, and by the Ubuntu daemon
(`UbuntuSystem.set_network`) for workstation accounts only, when it holds
`CAP_NET_ADMIN` itself (a VM, or another machine running `--system ubuntu`).
Standard library only and nothing from Pantheon, like the rest of the package.

WHAT EACH MODE WRITES (an `inet` table, so IPv4 and IPv6 alike)
==============================================================

    full      nothing: the table is removed.
    internet  loopback open; every destination in
              `protocol.INTERNET_EXCLUDED_V4/V6` refused.
    none      loopback open except Docker's own DNS at 127.0.0.11 (which would
              resolve, and carry data, through the host); everything else
              refused.

Three choices in it were measured, not assumed (2026-10-01, this repo's own
image under Docker 29.4.3, kernel 6.18):

* **`reject`, not `drop`.** A TCP connect whose SYN is dropped in the output
  hook waits out its own timeout (measured: 4 s, the probe's limit; a real
  client waits ~2 min). `reject with icmpx admin-prohibited` fails it at once
  (*No route to host*, 0 ms), and a UDP send says *Operation not permitted*.
* **`ct direction reply` first.** The packets that answer a connection made
  *to* the workstation — Pantheon's requests to the daemon — leave by the same
  hook, and Pantheon's address is private. Accepting the reply direction keeps
  them; accepting `established` instead would also keep a connection to the
  LAN that an agent opened before the mode narrowed, and the mode should close
  that at once.
* **DNS still resolves under *internet*.** Docker's resolver is on loopback; a
  resolver this machine was given on the LAN (`/etc/resolv.conf`) is let
  through on port 53 only, because a name that cannot be looked up makes
  *internet only* mean *nothing*.

**The table names the mode in its comment**, and `in_force` reads that back
from the kernel after every write: what the daemon or the gate reports is what
`nft` says is loaded, not what the caller remembers asking for.
"""
from __future__ import annotations

import errno
import ipaddress
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from workstation import protocol as P

#: The gate's table: every process in the namespace, root included.
GATE_TABLE = "pantheon_workstation"
#: The daemon's own table: workstation accounts only.
ACCOUNTS_TABLE = "pantheon_accounts"
COMMENT_PREFIX = "pantheon-workstation network="
#: Docker's embedded DNS, on loopback in every container on a user network.
DOCKER_DNS = "127.0.0.11"
#: Never a real host (RFC 5737), in every excluded set: what the self-test
#: connects to after a narrowing mode is written.
SELF_TEST_ADDRESS = ("192.0.2.1", 9)
CAP_NET_ADMIN = 12

Runner = Callable[[Sequence[str], Optional[str]], Tuple[int, str, str]]


def _run(argv: Sequence[str], stdin: Optional[str] = None) -> Tuple[int, str, str]:
    done = subprocess.run(list(argv), input=stdin, capture_output=True, text=True, timeout=20)
    return done.returncode, done.stdout, done.stderr


def _excluded(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    nets = P.INTERNET_EXCLUDED_V4 if ip.version == 4 else P.INTERNET_EXCLUDED_V6
    return any(ip in ipaddress.ip_network(n) for n in nets)


def lan_resolvers(resolv_conf: Path = Path("/etc/resolv.conf")) -> List[str]:
    """The nameservers this machine was given that *internet* would otherwise
    refuse — LAN addresses, not loopback (loopback is open in every mode)."""
    out: List[str] = []
    try:
        text = Path(resolv_conf).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            addr = parts[1].split("%", 1)[0]
            try:
                if ipaddress.ip_address(addr).is_loopback:
                    continue
            except ValueError:
                continue  # not an address: nothing to let through
            if _excluded(addr) and addr not in out:
                out.append(addr)
    return out


def ruleset(mode: str, *, table: str = GATE_TABLE, uids: Optional[Tuple[int, int]] = None,
            resolvers: Iterable[str] = ()) -> str:
    """The whole `nft -f` input for one mode: the old table replaced in one
    transaction (the kernel applies the file or none of it), so there is no
    moment between two modes with neither in force.

    `uids` scopes every refusal to sockets owned by that uid range (the
    daemon's own layer); without it the rules cover every process."""
    if mode not in P.NETWORK_MODES:
        raise ValueError(f"{mode!r} is not a network mode")
    if not re.fullmatch(r"[a-z_]{1,32}", table):
        raise ValueError(f"{table!r} is not a table name this file writes")
    # `table … {}` then `delete`: declaring it first makes the delete succeed
    # whether or not an older table is there.
    head = [f"table inet {table} {{}}", f"delete table inet {table}"]
    if mode == "full":
        return "\n".join(head) + "\n"
    who = ""
    if uids is not None:
        lo, hi = int(uids[0]), int(uids[1])
        if not 0 < lo <= hi:
            raise ValueError("a uid range is two positive numbers, low to high")
        who = f"meta skuid {lo}-{hi} "
    refuse = "reject with icmpx admin-prohibited"
    rules = ["ct direction reply accept"]
    if mode == "internet":
        dns = sorted({str(ipaddress.ip_address(r)) for r in resolvers})
        v4 = [r for r in dns if ipaddress.ip_address(r).version == 4]
        v6 = [r for r in dns if ipaddress.ip_address(r).version == 6]
        for fam, addrs in (("ip", v4), ("ip6", v6)):
            if addrs:
                rules.append(f"{who}{fam} daddr {{ {', '.join(addrs)} }} "
                             "meta l4proto { tcp, udp } th dport 53 accept")
        rules += [f'{who}oifname "lo" accept',
                  f"{who}ip daddr @excluded4 {refuse}",
                  f"{who}ip6 daddr @excluded6 {refuse}"]
    else:  # none
        rules += [f"{who}ip daddr {DOCKER_DNS} {refuse}",
                  f'{who}oifname "lo" accept',
                  f"{who}{refuse}"]
    body = [f"table inet {table} {{",
            f'  comment "{COMMENT_PREFIX}{mode}"',
            "  set excluded4 { type ipv4_addr; flags interval; elements = { "
            + ", ".join(P.INTERNET_EXCLUDED_V4) + " } }",
            "  set excluded6 { type ipv6_addr; flags interval; elements = { "
            + ", ".join(P.INTERNET_EXCLUDED_V6) + " } }",
            "  chain output {",
            "    type filter hook output priority filter; policy accept;",
            *[f"    {r}" for r in rules],
            "  }",
            "}"]
    return "\n".join(head + body) + "\n"


class RulesError(Exception):
    """`nft` refused, or is not there. The sentence is for a person."""


def nft_path() -> Optional[str]:
    return shutil.which("nft")


def apply(text: str, *, run: Runner = _run, nft: Optional[str] = None) -> None:
    binary = nft or nft_path()
    if not binary:
        raise RulesError("nft is not installed here, so no network mode can be enforced.")
    code, _out, err = run([binary, "-f", "-"], text)
    if code != 0:
        raise RulesError(f"nft refused the rules: {(err or '').strip().splitlines()[-1:] or code}")


def in_force(table: str, *, run: Runner = _run, nft: Optional[str] = None) -> Optional[str]:
    """The mode the kernel has loaded for `table`, read back from it: the mode
    named in the table's comment, `"full"` when there is no table, or None
    when nft cannot be asked."""
    binary = nft or nft_path()
    if not binary:
        return None
    code, out, err = run([binary, "-j", "list", "table", "inet", table], None)
    if code != 0:
        if "No such file or directory" in (err or ""):
            return "full"
        return None
    try:
        items = json.loads(out).get("nftables", [])
    except (ValueError, AttributeError):
        return None
    for item in items:
        t = item.get("table") if isinstance(item, dict) else None
        if isinstance(t, dict) and t.get("name") == table:
            comment = str(t.get("comment") or "")
            if comment.startswith(COMMENT_PREFIX):
                mode = comment[len(COMMENT_PREFIX):]
                return mode if mode in P.NETWORK_MODES else None
            return None
    return None


def self_test(*, address: Tuple[str, int] = SELF_TEST_ADDRESS, timeout: float = 1.0,
              connect: Optional[Callable[[Tuple[str, int], float], int]] = None) -> str:
    """Connect to an address every narrowing mode refuses and say whether the
    rules just written refused it: `"refused"`, or `RulesError`. Run by the
    gate, whose rules cover its own sockets exactly as they cover the
    workstation's. Never aimed at a real host (RFC 5737)."""
    def _connect(addr: Tuple[str, int], limit: float) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(limit)
            try:
                return s.connect_ex(addr)
            except socket.timeout:
                return errno.ETIMEDOUT
    code = (connect or _connect)(address, timeout)
    if code in (errno.EHOSTUNREACH, errno.EPERM, errno.EACCES):
        return "refused"
    raise RulesError(f"the rules were written but a test connection to {address[0]} was not "
                     f"refused by them ({errno.errorcode.get(code, code)})")


def capability(bit: int, field: str = "CapEff", status: Path = Path("/proc/self/status")) -> bool:
    """Whether this process has capability `bit` in `field` (CapEff, CapBnd)."""
    # No /proc (not Linux) or a line we cannot read: say "no", which is what
    # makes the daemon hold nothing and report `none`.
    return bool((capabilities(field, status) or 0) >> bit & 1)


def capabilities(field: str = "CapEff",
                 status: Path = Path("/proc/self/status")) -> Optional[int]:
    """This process's whole capability set `field` as a bit mask, or None when
    it cannot be read — not 0, which is a set with nothing in it (`Law 10`).
    `B976`: `workstation/netraw.py` needs the bounding set, not one bit of it."""
    try:
        for line in Path(status).read_text(encoding="utf-8").splitlines():
            if line.startswith(field + ":"):
                return int(line.split()[1], 16)
    except (OSError, ValueError, IndexError):
        # No /proc (not Linux) or a line we cannot read: None, "unknown" —
        # `capability` reads it as "no", `netraw` as "change nothing".
        pass
    return None


__all__ = ["ACCOUNTS_TABLE", "CAP_NET_ADMIN", "COMMENT_PREFIX", "DOCKER_DNS", "GATE_TABLE",
           "RulesError", "SELF_TEST_ADDRESS", "apply", "capability", "in_force", "lan_resolvers",
           "nft_path", "ruleset", "self_test",
           "capabilities"]  # `B976`, added
