# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1631` — a name an agent reads is handed over as a name, never as part of
a command a shell (or a database) runs.

Measured before the fix: Config Drift's one command ran
`ssh "$h" "cat '$f'"` for every file in the person's config repository. ssh
joins the words after the host with spaces and the far side's login shell runs
the result (`$SHELL -c "<words>"`), so a file named `x'; touch pwned; '.conf`
ran `touch pwned` on the machine being checked — and a name with `$(…)` in it
ran too. `B1622`'s reader already called that command unreadable ("the far side
is handed a command made when it runs"); nothing had run it with such a name.

Now each name travels on ssh's standard input and the far side's command is a
constant — `xargs -0 cat --` — so `cat` is handed the name as one argument and
no shell there ever reads it. The same rule, swept across every agent whose
command builds a command from a name (`Law 14`: the one way, everywhere it
applies):

  * **names written into the far side's command** — Log Watcher's service
    names, Incident Scribe's window and Media Library Tidier's library folder;
    a systemd name like `mnt-data\\x2dbackup.mount` lost its backslash, and a
    folder with a `'` or `$(…)` in it broke the quoting or ran. Each now
    reaches the machine on its input;
  * **a machine's name where ssh reads its options** — all sixteen ssh
    commands put the hire's machine there, so a name beginning
    `-oProxyCommand=` ran a command on the workstation. `--` now ends the
    options, and each name goes in single quotes;
  * **a list the hire names, written bare into a loop** — six agents looped
    over pages, targets, certificate names or repositories written unquoted,
    so an address with an `&` in it (`?a=1&b=2`) broke the command and one
    with `$(…)` in it ran. Each name now goes in single quotes;
  * **a name from a listing, made into SQL** — Restore Drill counted each
    restored table with `select count(*) from $x`, `$x` read back from
    `pg_tables`: a table in the dump named
    `o;copy(select 1)to program 'touch …'` ran a program on the workstation as
    the scratch database's superuser. The count now quotes each name as the
    database quotes one (`format('%I')` inside one query; a doubled backtick;
    a doubled `"`).

Driven, not grepped (`Law 20`): each runbook's own command is taken from its
file, filled the way the runbook says, and run by `bash` — against a far side
that behaves as sshd does (a stand-in `ssh` on `PATH` that joins the words and
hands them to `sh -c`, and runs a `ProxyCommand` it is given as ssh does), with
every program that would reach a machine or the network replaced by one that
writes down exactly what it was handed. Restore Drill's count runs against a
real PostgreSQL (where the machine has one) and a real SQLite. Each fix has a
control: the command as it was, against the same stand-ins, runs the name — so
a green result below cannot be a stand-in that runs nothing at all. And each
filled command is put to the hire's own gate (`destructive: never` refuses a
command it cannot read, `B1622`), so the fix is one the run may make.

The adversary (`Law 17`): whoever can name a file in the repository a hire
reads, a table in the database it restores, or a container or service on a
machine it checks — and a mistake in a name the person typed. Not the person
typing their own hire's inputs, who already runs commands on these machines.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.agents import hires as H
from src.agents.catalogue import catalogue, get_agent
from src.tool_capabilities import ToolRunSecurityContext

#: OpenSSH's own rule for the command: every word after the destination,
#: joined by one space, run by the far side's shell. Options that take a value
#: are skipped with it, and a `ProxyCommand` among them is run on this side,
#: as ssh runs it; `--` ends them. The destination is written down.
STAND_IN_SSH = r"""#!/bin/sh
proxy() { case "$1" in ProxyCommand=*) (cd "$NEAR_HOME" && /bin/sh -c "${1#ProxyCommand=}") ;; esac; }
while [ $# -gt 0 ]; do
  case "$1" in
    -o) proxy "$2"; shift 2 ;;
    -o*) proxy "${1#-o}"; shift ;;
    -[bcDEeFIiJLlmOPpQRSWw]) shift 2 ;;
    --) shift; break ;;
    -*) shift ;;
    *) break ;;
  esac
done
printf '%s\n' "$1" >> "$RECORD/ssh.dest"
shift
cd "$FAR_HOME" || exit 255
PATH="$FAR_BIN" exec /bin/sh -c "$*"
"""

#: A program that writes down each argument it was handed, one per line,
#: then fails — as `systemctl cat` and `docker logs` do for a name the
#: machine does not have, and as a browser does for a page it cannot load.
RECORDER = r"""#!/bin/sh
for a in "$@"; do printf '%s\n' "$a"; done >> "$RECORD/${0##*/}.args"
exit 1
"""

#: What the far side may run for real: reading and moving text, and `touch` —
#: what a name that runs leaves its mark with. Every other
#: program a command names there is a recorder, so nothing reads this machine.
FAR_REAL = ("cat", "xargs", "find", "sort", "tr", "head", "tail", "grep", "awk", "sed", "touch")
FAR_RECORDED = ("systemctl", "journalctl", "docker", "getent", "lastlog", "df", "du", "ss", "sudo", "nft",
                "ufw", "zpool", "btrfs", "lsblk", "smartctl", "ip", "arp", "uptime", "nproc", "free", "apt",
                "apt-get", "dnf", "hostname", "trivy")
#: This side: what would reach a machine or the network, or is not installed.
NEAR_RECORDED = ("curl", "nc", "openssl", "whois", "chromium", "img2pdf", "compare", "identify", "gitleaks")

THE_ROWS_COMMAND = ("""cd $PANTHEON_PROJECTS/infra && for h in web1; do echo "== $h"; """
                    """[ -d "$h" ] || { echo "NO FOLDER"; continue; }; """
                    """(cd "$h" && find . -type f | sed 's#^\\.##') | while read f; do echo "-- $f"; """
                    """ssh -n -o BatchMode=yes -o ConnectTimeout=8 "$h" "cat '$f'" 2>&1 """
                    """| diff -u "$h$f" - | head -20; done; done""")


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def far(tmp_path):
    """The workstation's `PATH` with the stand-ins first, the far machine's
    home (where a command run there by mistake leaves its mark) and its
    programs, and the folder every recorder writes to."""
    near_bin, far_bin = tmp_path / "near-bin", tmp_path / "far-bin"
    home, near_home, record = tmp_path / "far-home", tmp_path / "near-home", tmp_path / "record"
    for d in (near_bin, far_bin, home, near_home, record, tmp_path / "projects"):
        d.mkdir()
    _executable(near_bin / "ssh", STAND_IN_SSH)
    for prog in NEAR_RECORDED:
        _executable(near_bin / prog, RECORDER)
    for prog in FAR_RECORDED:
        _executable(far_bin / prog, RECORDER)
    for prog in FAR_REAL:
        real = shutil.which(prog)
        assert real, prog
        os.symlink(real, far_bin / prog)
    env = dict(os.environ, PATH=f"{near_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
               FAR_HOME=str(home), FAR_BIN=str(far_bin), NEAR_HOME=str(near_home), RECORD=str(record),
               PANTHEON_PROJECTS=str(tmp_path / "projects"))

    class Far:
        root = tmp_path

        @staticmethod
        def run(command: str) -> str:
            done = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True,
                                  timeout=60, cwd=str(near_home))
            return done.stdout + done.stderr

        @staticmethod
        def marks():
            """Every file a command run by mistake made anywhere in the world."""
            return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("pwned*"))

        @staticmethod
        def handed(prog: str):
            """What `prog` was handed, an argument a line; `ssh.dest` is the
            destination each ssh was given."""
            f = record / (prog if prog.endswith(".dest") else f"{prog}.args")
            return f.read_text(encoding="utf-8").split("\n")[:-1] if f.exists() else []

        @staticmethod
        def forget():
            for f in record.iterdir():
                f.unlink()
    return Far


def _steps(runbook: str) -> str:
    return runbook.split("## Steps", 1)[-1].split("\n## ", 1)[0]


def _step_command(agent_id: str, pattern: str) -> str:
    """The runbook's own step command — the one backticked span in
    `## Steps` matching `pattern` — exactly as the model is told to run it."""
    spans = [s for s in re.findall(r"`([^`]+)`", _steps(get_agent(None, agent_id).runbook))
             if re.search(pattern, s)]
    assert len(spans) == 1, (agent_id, spans)
    return spans[0]


def _ssh_command(agent_id: str) -> str:
    return _step_command(agent_id, r"\bssh -")


def _loop_command(agent_id: str) -> str:
    return _step_command(agent_id, r"for [a-z] in <")


def _q(text: str) -> str:
    """A value in single quotes, a `'` in it written `'\\''` — the quoting
    each runbook asks of the model."""
    return "'" + text.replace("'", "'\\''") + "'"


def _fill(command: str, fills: dict) -> str:
    for placeholder, value in fills.items():
        assert placeholder in command, (placeholder, command)
        command = command.replace(placeholder, value)
    assert not re.search(r"<[a-z][^<>]*>", command), command
    return command


def _runs_under_its_own_hire(agent_id: str, command: str) -> bool:
    """Whether the hire's own table lets this command run in a clean run —
    its `never`s and `ask`s, as the gate reads them (`B1622`) — or, for an
    agent whose one command removes its own scratch (Screenshot Reporter),
    asks for that deletion and nothing else: a name that made the command
    unreadable would be named on the card instead.

    `B1652`: or, for an agent whose hire asks before reaching the network
    (Network Mapper), asks for its `ssh` and nothing else — the card names
    the `ssh`, where an unreadable name would be named instead."""
    table = H.effective_effects(get_agent(None, agent_id), {})
    run = ToolRunSecurityContext(hire_ask_effects=frozenset(e for e, r in table.items() if r == "ask"),
                                 hire_never_effects=frozenset(e for e, r in table.items() if r == "never"))
    # A `bash` block carries its command as its content (`tool_parsing`).
    decision = run.decision_for("bash", command)
    return decision.allowed or decision.reason in (
        "This agent's hire asks before destructive: 'bash' waits for your yes (rm deletes files).",
        "This agent's hire asks before network_egress: 'bash' waits for your yes (ssh reaches the network).")


HOSTILE = ["x'; touch pwned1; '.conf", "$(touch pwned2).conf", "`touch pwned3`.conf",
           'x"; touch pwned4; ".conf', "x\ntouch pwned5\n.conf", "-n.conf"]

#: Machines' names a hire might be given — or mistype.
MACHINES = ["web1", "-oProxyCommand=touch pwned-p", "db1;touch pwned-q", "x$(touch pwned-r)", "it's"]


def _machines(names) -> dict:
    return {"<the machines, each in single quotes>": " ".join(map(_q, names))}


def _config_repository(far, live: Path):
    """`infra/web1/<live>/…` recorded; the live copies at `<live>/…` (the
    far machine's absolute paths, which here are this test's own)."""
    recorded = far.root / "projects" / "infra" / "web1" / str(live).lstrip("/")
    recorded.mkdir(parents=True)
    live.mkdir(parents=True)
    for name in HOSTILE:
        (recorded / name).write_text("listen 80;\n", encoding="utf-8")
        (live / name).write_text("listen 80;\n", encoding="utf-8")
    (recorded / "nginx.conf").write_text("worker_connections 1024;\n", encoding="utf-8")
    (live / "nginx.conf").write_text("worker_connections 4096;\n", encoding="utf-8")


def _config_drift() -> str:
    return _fill(_ssh_command("config-drift"), {"<folder>": "infra", **_machines(["web1"])})


# ── Config Drift, the row ───────────────────────────────────────────────────

def test_the_stand_in_runs_a_hostile_name_as_a_real_far_side_would(far):
    """The control: the command the row quotes, against the same far side,
    runs the names — so the far side below is not one that runs nothing."""
    _config_repository(far, far.root / "live" / "etc")
    far.run(THE_ROWS_COMMAND)
    assert "far-home/pwned1" in far.marks()


def test_config_drift_hands_each_name_to_cat_and_nothing_runs(far):
    live = far.root / "live" / "etc"
    _config_repository(far, live)
    command = _config_drift()
    out = far.run(command)
    assert far.marks() == [], f"a name ran on the far side:\n{out}"
    # Each hostile file was read by name and matches its recorded copy: no
    # diff follows its line. The one real drift is still found.
    for name in HOSTILE:
        assert f"-- {live}/{name}\n" in out, (name, out)
    assert f"--- web1{live}/nginx.conf" in out
    assert "-worker_connections 1024;" in out and "+worker_connections 4096;" in out
    assert "No such file" not in out, out


def test_a_missing_live_file_is_still_said_by_cat(far):
    live = far.root / "live" / "etc"
    _config_repository(far, live)
    (live / "$(touch pwned2).conf").unlink()
    out = far.run(_config_drift())
    assert far.marks() == []
    assert "No such file or directory" in out and "+cat: " in out


def test_config_drifts_own_hire_refuses_the_rows_command_and_runs_the_new_one():
    """Through the gate the run itself has: its `destructive: never`
    (`B1629`) refuses a command whose far side is made when it runs (`B1622`),
    so the old command does not come back by a model remembering it."""
    assert not _runs_under_its_own_hire("config-drift", THE_ROWS_COMMAND)
    assert _runs_under_its_own_hire("config-drift", _config_drift())


# ── Every ssh in the library ────────────────────────────────────────────────

#: Each ssh command that loops over the hire's machines, and its other
#: placeholders, filled as its runbook says.
SSH_FILLS = {
    "access-reviewer": {}, "container-keeper": {}, "firewall-auditor": {}, "login-watcher": {},
    "update-planner": {}, "vulnerability-scanner": {}, "server-health": {},
    "disk-janitor": {"<the line>": "80"},
    "config-drift": {"<folder>": "infra"},
    "incident-scribe": {"'<start>'": _q("2026-10-28 13:30:00"), "'<end>'": _q("2026-10-28 15:00:00")},
    "log-watcher": {"<the services, each in single quotes>": " ".join(map(_q, ["nginx", "it's.service"]))},
}
#: The ones that reach one machine, named by the hire.
ONE_MACHINE = {"nas-health": "'<the NAS>'", "network-mapper": "'<the host>'",
               "media-library-tidier": "'<the server>'"}


def test_every_agent_that_runs_ssh_is_one_driven_here():
    """Read from the runbooks, not carried (`Law 6`): a new agent that runs
    ssh is added above, or this fails."""
    agents, _ = catalogue(None)
    runs = {m.id for m in agents if any(re.search(r"\bssh -", s)
                                        for s in re.findall(r"`([^`]+)`", _steps(m.runbook)))}
    assert runs == set(SSH_FILLS) | set(ONE_MACHINE)


def test_ssh_reads_a_name_before_the_command_as_its_option(far):
    """The control: with no `--`, a machine named `-oProxyCommand=…` is an
    option to ssh, and ssh runs it here — on the workstation."""
    far.run(f"""for h in {_q(MACHINES[1])}; do ssh -n -o BatchMode=yes -o ConnectTimeout=8 "$h" 'true'; done""")
    assert far.marks() == ["near-home/pwned-p"]


@pytest.mark.parametrize("agent", sorted(SSH_FILLS))
def test_each_machine_is_handed_to_ssh_whole_and_runs_nothing(far, agent):
    machines = MACHINES
    if agent == "config-drift":
        # A machine is checked only when the repository has a folder for it,
        # and no folder's name starts with `-`.
        machines = [m for m in MACHINES if not m.startswith("-")]
        for name in machines:
            (far.root / "projects" / "infra" / name / "etc").mkdir(parents=True)
            (far.root / "projects" / "infra" / name / "etc" / "hosts").write_text("x\n", encoding="utf-8")
    command = _fill(_ssh_command(agent), {**SSH_FILLS[agent], **_machines(MACHINES)})
    out = far.run(command)
    assert far.marks() == [], out
    assert far.handed("ssh.dest") == machines, out
    for name in MACHINES:
        assert f"== {name}\n" in out, (name, out)
    assert _runs_under_its_own_hire(agent, command), command


@pytest.mark.parametrize("agent", sorted(ONE_MACHINE))
def test_the_one_machine_is_handed_to_ssh_whole_and_runs_nothing(far, agent):
    for name in MACHINES:
        far.forget()
        fills = {ONE_MACHINE[agent]: _q(name)}
        if agent == "media-library-tidier":
            fills["'<the path>'"] = _q("/srv/media")
        command = _fill(_ssh_command(agent), fills)
        out = far.run(command)
        assert far.marks() == [], out
        assert far.handed("ssh.dest") == [name], out
        assert _runs_under_its_own_hire(agent, command), command


def test_log_watcher_hands_each_service_name_over_whole(far):
    names = ["nginx", "a$(touch pwned6).service", "mnt-data\\x2dbackup.mount", "it's.service"]
    command = _fill(_ssh_command("log-watcher"), {**_machines(["web1"]),
                    "<the services, each in single quotes>": " ".join(_q(n) for n in names)})
    out = far.run(command)
    assert far.marks() == [], out
    for n in names:
        assert f"-- {n}\n" in out, (n, out)
    # `systemctl cat -- <name>` was handed each name exactly as written: the
    # backslash of a systemd escape arrives, where the far shell ate it before.
    assert far.handed("systemctl") == [a for n in names for a in ("cat", "--", n)]
    assert [a for a in far.handed("docker") if a in names] == names


def test_incident_scribe_hands_the_window_over_as_two_lines(far):
    # The far machine runs one container, `api`, whose logs are asked for too.
    _executable(far.root / "far-bin" / "docker",
                '#!/bin/sh\n[ "$1" = ps ] && { echo api; exit 0; }\n' + RECORDER.split("\n", 1)[1])
    start, end = "2026-10-28 13:30:00", "2026-10-28 15:00:00$(touch pwned7)"
    command = _fill(_ssh_command("incident-scribe"),
                    {**_machines(["web1"]), "'<start>'": _q(start), "'<end>'": _q(end)})
    far.run(command)
    assert far.marks() == []
    assert far.handed("journalctl")[:4] == ["--since", start, "--until", end]
    # Docker reads a date and time joined by `T` (a space is a `T` to it), and
    # is handed exactly that — nothing in it run.
    assert far.handed("docker") == ["logs", "--since", "2026-10-28T13:30:00",
                                    "--until", end.replace(" ", "T"), "api"]


def test_media_library_tidier_lists_a_folder_whatever_its_name(far):
    library = far.root / "media" / "Kids' Films $(touch pwned8)"
    (library / "Films" / "Up (2009)").mkdir(parents=True)
    (library / "Films" / "Up (2009)" / "Up (2009).mkv").write_text("x", encoding="utf-8")
    command = _fill(_ssh_command("media-library-tidier"),
                    {"'<the server>'": _q("nas"), "'<the path>'": _q(str(library))})
    out = far.run(command)
    assert far.marks() == [], out
    assert out.strip() == "./Films/Up (2009)/Up (2009).mkv", out


# ── Loops over a list the hire names, on the workstation ────────────────────

ADDRESSES = ["https://shop.example/?a=1&b=2", "https://x.example/$(touch pwned-u)",
             "https://x.example/'; touch pwned-v; '", "https://x.example/a;touch pwned-w"]


def _handed_whole(prog):
    return lambda far, out, name: name in far.handed(prog)


def _said(prefix):
    return lambda far, out, name: f"{prefix}{name}\n" in out


#: Each loop's list, its other placeholders, and where a name is seen whole:
#: the program it was handed to, or the line the command prints for it.
LOOP_FILLS = {
    "accessibility-auditor": ("<the pages, each in single quotes>", ADDRESSES, {}, _said("== ")),
    "screenshot-reporter": ("<the pages, each in single quotes>", ADDRESSES, {"<folder>": "reports"},
                            _handed_whole("chromium")),
    "visual-regression": ("<the pages, each in single quotes>", ADDRESSES,
                          {"<folder>": "shots", "<last folder>": "2026-10-27"}, _handed_whole("chromium")),
    "uptime-pinger": ("<the targets, each in single quotes>", ADDRESSES, {}, _handed_whole("curl")),
    "certificate-watch": ("<the names, each in single quotes>",
                          ["example.com", "$(touch pwned-c).example", "it's.example"], {}, _handed_whole("whois")),
    "secret-sniffer": ("<the repositories, each in single quotes>",
                       ["app", "my app", "$(touch pwned-g)", "it's"], {}, _handed_whole("gitleaks")),
}


def test_every_loop_over_a_hired_list_is_one_driven_here():
    agents, _ = catalogue(None)
    loops = {m.id for m in agents if re.search(r"for [a-z] in <", _steps(m.runbook))}
    assert loops == set(LOOP_FILLS) | set(SSH_FILLS)


def test_a_bare_list_breaks_on_an_ampersand_and_runs_a_substitution(far):
    """The control: the list written bare, as the runbooks said before."""
    placeholder, _names, fills, _seen = LOOP_FILLS["accessibility-auditor"]
    out = far.run(_fill(_loop_command("accessibility-auditor"), {**fills, placeholder: ADDRESSES[0]}))
    assert f"== {ADDRESSES[0]}\n" not in out
    far.run(_fill(_loop_command("accessibility-auditor"), {**fills, placeholder: ADDRESSES[1]}))
    assert far.marks() == ["near-home/pwned-u"]


@pytest.mark.parametrize("agent", sorted(LOOP_FILLS))
def test_each_name_in_a_hired_list_is_one_word_and_runs_nothing(far, agent):
    placeholder, names, fills, seen = LOOP_FILLS[agent]
    for folder in ("reports", "shots"):
        (far.root / "projects" / folder).mkdir()
    command = _fill(_loop_command(agent), {**fills, placeholder: " ".join(map(_q, names))})
    out = far.run(command)
    assert far.marks() == [], out
    for name in names:
        assert seen(far, out, name), (name, out)
    assert _runs_under_its_own_hire(agent, command), command


def test_a_host_and_port_target_is_split_on_this_side_only(far):
    placeholder, _names, fills, _seen = LOOP_FILLS["uptime-pinger"]
    out = far.run(_fill(_loop_command("uptime-pinger"), {placeholder: _q("db1:5432")}))
    assert far.handed("nc")[-2:] == ["db1", "5432"] and "db1:5432 closed" in out


# ── Restore Drill: a table's name, made into SQL ────────────────────────────

#: Restore Drill's counts as they were, for the controls.
OLD_POSTGRES_COUNT = ('''psql -h "$t" -U drill -At drill -c "select schemaname||'.'||tablename from pg_tables '''
                      '''where schemaname not in ('pg_catalog','information_schema')" | while read x; do '''
                      '''echo "count $x $(psql -h "$t" -U drill -At drill -c "select count(*) from $x")"; done''')
OLD_SQLITE_COUNT = '''c.execute(f"select count(*) from \\"{n}\\"").fetchone()[0]'''
NEW_SQLITE_COUNT = '''c.execute("select count(*) from \\"" + n.replace("\\"", "\\"\\"") + "\\"").fetchone()[0]'''


def _restore_drill(engine: str, dump: str) -> str:
    """Step 1 as the runbook gives it, for `engine`, on `dump`."""
    lines = get_agent(None, "restore-drill").runbook.split("\n")
    step = next(ln for ln in lines if ln.startswith("1. One `bash` command"))
    count = next(ln for ln in lines if ln.startswith(f"   - {engine}: `"))
    return _fill(step.split("`")[3], {"'<dump>'": _q(dump),
                                      "<restore and count>": count.split("`", 1)[1].rsplit("`", 1)[0]})


def test_restore_drill_counts_a_sqlite_table_whatever_its_name(tmp_path):
    dump = tmp_path / "backups" / "shop's db" / "shop.sqlite"
    dump.parent.mkdir(parents=True)
    db = sqlite3.connect(dump)
    db.executescript('create table orders(id int); insert into orders values (1),(2),(3);'
                     'create table "say ""hi"""(x int); insert into "say ""hi""" values (1),(2);'
                     'create table zeta(x int); insert into zeta values (1);')
    db.commit()
    db.close()
    command = _restore_drill("sqlite", str(dump.parent))
    env = dict(os.environ, TMPDIR=str(tmp_path))
    out = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True, timeout=60).stdout
    assert f"dump {dump} " in out and "restore exit 0 ok" in out, out
    assert [ln for ln in out.split("\n") if ln.startswith("count ")] == [
        "count orders 3", 'count say "hi" 2', "count zeta 1"], out
    # The control: as it was, the odd name ended the counting there.
    old = command.replace(NEW_SQLITE_COUNT, OLD_SQLITE_COUNT)
    assert old != command
    out = subprocess.run(["bash", "-c", old], env=env, capture_output=True, text=True, timeout=60).stdout
    assert "OperationalError" in out and "count zeta 1" not in out, out


def _postgres_bin():
    found = sorted(glob.glob("/usr/lib/postgresql/*/bin/initdb"))
    return os.path.dirname(found[-1]) if found else None


def _as_someone_else():
    """initdb refuses root: as root, the command runs as `nobody`."""
    if os.geteuid() != 0:
        return []
    runuser = shutil.which("runuser")
    return [runuser, "-u", "nobody", "--"] if runuser else None


@pytest.mark.skipif(_postgres_bin() is None or _as_someone_else() is None,
                    reason="no PostgreSQL server here to restore into")
def test_restore_drill_counts_a_postgres_table_named_like_sql_and_runs_nothing():
    # Short (a socket is made in it), and one `nobody` can enter when root runs this.
    work = Path(tempfile.mkdtemp(prefix="rd-", dir="/tmp" if os.geteuid() == 0 else None))
    try:
        work.chmod(0o777)
        dump = work / "shop.sql"
        # pg_dump quotes every name, so a table named like this restores as
        # one table; `../../pwned` is the work folder, seen from the data dir.
        hostile = "\"o;copy(select 1)to program 'touch ../../pwned'\""
        dump.write_text("create table orders(id int); insert into orders values (1),(2),(3);\n"
                        "create table o(x int);\n"
                        f"create table {hostile}(x int); insert into {hostile} values (1);\n", encoding="utf-8")
        dump.chmod(0o644)

        def run(command: str) -> str:
            argv = _as_someone_else() + ["env", f"TMPDIR={work}", f"HOME={work}", "bash", "-c", command]
            done = subprocess.run(argv, capture_output=True, text=True, timeout=120, cwd=str(work))
            return done.stdout + done.stderr

        command = _restore_drill("postgres", str(dump))
        out = run(command)
        assert "restore exit 0" in out, out
        assert not (work / "pwned").exists(), out
        assert sorted(ln for ln in out.split("\n") if ln.startswith("count ")) == sorted([
            "count public.orders 3", "count public.o 0", f"count public.{hostile} 1"]), out
        # The control: the count as it was ran the table's name as SQL.
        start = command.index('psql -h "$t" -U drill -At -F')
        old = command[:start] + OLD_POSTGRES_COUNT + command[command.index("; pg_ctl -D", start):]
        run(old)
        assert (work / "pwned").exists()
    finally:
        shutil.rmtree(work, ignore_errors=True)
