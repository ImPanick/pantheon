# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1634` — a folder a hire names is one folder to the shell, whatever its
name holds.

Measured before the fix: twenty-two runbooks began
`cd $PANTHEON_PROJECTS/<folder> && …`, and the hire's folder input refuses only
a leading `/` and a `..` (`hires.check_inputs`), so a hire for *My Site* ran
`cd $PANTHEON_PROJECTS/My Site` — bash's `cd` refuses two words ("too many
arguments"), and everything after the `&&` was skipped — while a folder named
with a `$(…)` ran it. Photo Organiser's `cd "$PANTHEON_PROJECTS/<folder>"`, and
Roadmap Keeper's, Status Reporter's and Archive Sorter's `cd "<folder>"`, kept
the space but still ran a `$(…)` or a backquote, and broke on a `"`.

Now every runbook's `cd` puts the folder in single quotes, `'` written `'\\''`
— the rule `B1631` gave the hire's lists — and `$PANTHEON_PROJECTS` in double
quotes. The same sweep, everywhere else a hire's words reach a shell
(`Law 14`): Code Reviewer's branch (git lets a branch's name hold `$(…)`, `;`
and `'`), Load Tester's address (`?a=1&b=2` broke the command), Archive
Sorter's file names (a downloaded file is named by whoever served it), and the
six commit messages a model words from the hire's issue, refactor, files or
migration — in double quotes a backquote ran, and a hire's
`destructive: never` refused the commit as unreadable.

Driven, not grepped (`Law 20`): each runbook's own `cd` is taken from its file,
filled the way it says with hostile and spaced names, and run by `bash`; Code
Reviewer's diff and Bug Fixer's commit run against a real git repository, and
Archive Sorter's move moves real files. Each fix has a control — the old form,
on the same names, does not reach the folder or runs the name — and each filled
command is put to the hire's own gate (`B1622`).

The adversary (`Law 17`): whoever names a branch, a file or a folder the person
then hands a hire — a contributor's branch, a downloaded file, a cloned
repository — and a mistake in a name the person typed.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from src.agents.catalogue import catalogue, get_agent
from test_a_name_runs_nothing_on_the_far_side import _q, _runs_under_its_own_hire, _steps

#: Folders a hire might be given: spaced, with a `'`, with what a shell would
#: run, and one nested.
FOLDERS = ["My Site", "Tom's site", "$(touch pwned1)", "x`touch pwned2`", 'say "hi"', "a;touch pwned3",
           "a&touch pwned4", "site/drafts 2"]

#: What a model fills the rest of a command with, when the folder is the point.
OTHER_FILLS = {
    "<the test command>": "pytest -q", "<today's date>": "2026-10-28", "<base>": "main", "<branch>": "fix",
    "<runs>": "3", "<the inventory>": ".venv/bin/pip list --outdated --format=json", "<name>": "merge_csv",
    "<the pages, each in single quotes>": "'https://dash.example/'", "<last folder>": "2026-10-27",
    "<first path>": "/pets", "<second path>": "/pets/1", "<the machines, each in single quotes>": "'web1'",
    "<the repositories, each in single quotes>": "'app'", "<category>": "bills", "<file>": "scan001.pdf",
    "<YYYY-MM>": "2026-10", "<short name>": "power-bill", "<ext>": "pdf", "<video>": "films/trip.mp4",
}
#: A repository's commits here are made by nobody's own git settings.
GIT_IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
#: The placeholders that name the hire's folder.
FOLDER_PLACEHOLDERS = ("<folder>", "<out>", "<the folder>")


def _cd_spans():
    """Every backticked step command in the library that starts with `cd` —
    read from the runbooks, never carried (`Law 6`)."""
    agents, _ = catalogue(None)
    out = []
    for m in sorted(agents, key=lambda m: m.id):
        for span in re.findall(r"`([^`]+)`", _steps(m.runbook)):
            if span.startswith("cd "):
                out.append((m.id, span))
    return out


def _fill_name(text: str, placeholder: str, name: str) -> str:
    """As a model fills it: a placeholder the runbook quotes gets the name in
    single quotes, `'` written `'\\''`; a bare one gets the name as it is."""
    if f"'{placeholder}'" in text:
        return text.replace(f"'{placeholder}'", _q(name))
    return text.replace(placeholder, name)


def _fill(command: str, folder: str) -> str:
    for ph in FOLDER_PLACEHOLDERS:
        command = _fill_name(command, ph, folder)
    command = command.replace("'<base>...<branch>'", _q("main...fix"))
    for ph, value in OTHER_FILLS.items():
        command = command.replace(ph, value)
    assert not re.search(r"<[a-z][^<>]*>", command), command
    return command


@pytest.fixture
def projects(tmp_path):
    """A projects folder whose own path has a space in it, every folder in
    `FOLDERS` made inside it, and a `run` that runs a command there as the
    workstation does: `$PANTHEON_PROJECTS` set, the shell starting in it."""
    root = tmp_path / "My Projects"
    for name in FOLDERS:
        (root / name).mkdir(parents=True)
    env = dict(os.environ, PANTHEON_PROJECTS=str(root), **GIT_IDENTITY)

    class P:
        path = root

        @staticmethod
        def run(command: str, cwd: Path = root) -> subprocess.CompletedProcess:
            return subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True, timeout=60,
                                  cwd=str(cwd))

        @staticmethod
        def marks():
            return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("pwned*"))
    return P


# ── every runbook's `cd` ────────────────────────────────────────────────────

def test_every_cd_in_the_library_names_the_hires_folder():
    """The set this file drives is the set the runbooks hold: each `cd`
    reaches the hire's folder through a placeholder, or the projects folder
    itself — so a new runbook's `cd` is driven below, or this fails."""
    spans = _cd_spans()
    assert len({a for a, _s in spans}) >= 27, spans
    for agent, span in spans:
        head = span.split(" && ", 1)[0]
        assert any(ph in head for ph in FOLDER_PLACEHOLDERS) or head == 'cd "$PANTHEON_PROJECTS"', (agent, head)


@pytest.mark.parametrize("name", FOLDERS)
def test_each_runbooks_cd_lands_in_the_folder_whatever_its_name(projects, name):
    """Each `cd`, as its runbook gives it, filled with `name`: the shell ends
    in that folder and nothing in the name ran."""
    for agent, span in _cd_spans():
        head = span.split(" && ", 1)[0]
        done = projects.run(_fill(head, name) + " && pwd -P")
        want = projects.path if head == 'cd "$PANTHEON_PROJECTS"' else projects.path / name
        assert done.returncode == 0 and done.stdout.strip() == str(want.resolve()), (agent, head, done.stderr)
    assert projects.marks() == []


def test_the_old_cd_did_not_reach_a_spaced_folder_and_ran_a_named_command(projects):
    """The control: the form 22 runbooks had, on the same folders."""
    old = "cd $PANTHEON_PROJECTS/<folder>"
    spaced = projects.run(_fill(old, "My Site") + " && pwd -P")
    assert spaced.returncode != 0 and "My Site" not in spaced.stdout, spaced
    projects.run(_fill(old, "$(touch pwned1)") + " && pwd -P")
    assert projects.marks() == ["My Projects/pwned1"]


@pytest.mark.parametrize("name", ["My Site", "Tom's site", "$(touch pwned1)"])
def test_each_filled_command_is_one_its_own_hire_runs(name):
    """Through the gate a run has: a quoted name leaves the command readable,
    so a hire's `destructive: never` does not refuse it as hidden (`B1622`)."""
    for agent, span in _cd_spans():
        command = _fill(span.replace("&& … && ", "&& ").replace(" … &&", " &&"), name)
        assert _runs_under_its_own_hire(agent, command), (agent, command)


# ── Code Reviewer: a branch's name is a name ────────────────────────────────

BRANCH = "fix$(touch${IFS}pwned5)"


def _git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, **GIT_IDENTITY)
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(projects):
    """`My Site`, a repository with `main` and a branch whose name git
    accepts and a shell would run (`git check-ref-format` passes it)."""
    if not shutil.which("git"):
        pytest.skip("no git here")
    path = projects.path / "My Site"
    _git(path, "init", "-q", "-b", "main")
    (path / "cart.py").write_text("def total(items):\n    return sum(items)\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "first")
    _git(path, "checkout", "-q", "-b", BRANCH)
    (path / "cart.py").write_text("def total(items):\n    return sum(items) * 0.9\n", encoding="utf-8")
    _git(path, "commit", "-q", "-am", "discount")
    return path


def _code_review(branch: str) -> str:
    span = next(s for a, s in _cd_spans() if a == "code-reviewer")
    command = _fill_name(span, "<folder>", "My Site")
    return command.replace("'<base>...<branch>'", _q(f"main...{branch}"))


def test_code_reviewer_diffs_a_branch_named_like_a_command_and_runs_nothing(projects, repo):
    done = projects.run(_code_review(BRANCH))
    assert done.returncode == 0, done.stderr
    assert "cart.py | 2 +-" in done.stdout and "+    return sum(items) * 0.9" in done.stdout, done.stdout
    assert projects.marks() == []
    assert _runs_under_its_own_hire("code-reviewer", _code_review(BRANCH))


def test_the_old_range_ran_the_branchs_name(projects, repo):
    """The control: the range written bare, as it was."""
    old = (f"cd {_q(str(repo))} && git diff --stat main...{BRANCH} && git diff -U5 main...{BRANCH}")
    projects.run(old)
    assert projects.marks() == ["My Projects/My Site/pwned5"]


# ── a commit message the model words ────────────────────────────────────────

#: Each agent whose runbook commits with a message it words, and the
#: placeholder that message is made from.
COMMITS = {"bug-fixer": "<the issue in a few words>", "refactorer": "<the refactor in a few words>",
           "test-writer": "<files>", "dependency-watch": "<packages>", "migration-runner": "<the step>",
           "repo-doctor": "<tests>"}
WORDS = "`items[0]` fails on an empty basket; it's $(touch pwned6) now"


def _commit_span(agent: str) -> str:
    spans = [s for s in re.findall(r"`([^`]+)`", _steps(get_agent(None, agent).runbook)) if "git commit" in s]
    assert len(spans) == 1, (agent, spans)
    return spans[0]


def test_every_runbook_that_commits_words_is_driven_here():
    agents, _ = catalogue(None)
    words = {m.id for m in agents
             if any(re.search(r"git commit -a?m '[^']*<", s) or re.search(r'git commit -a?m "[^"]*<', s)
                    for s in re.findall(r"`([^`]+)`", _steps(m.runbook)))}
    assert words == set(COMMITS)


@pytest.mark.parametrize("agent", sorted(COMMITS))
def test_a_commit_message_keeps_its_words_and_runs_none(projects, repo, agent):
    span = _commit_span(agent)
    # The words sit inside the message's single quotes, so each `'` in them
    # is written `'\\''`, as the runbook says.
    assert re.search(r"-a?m '[^']*" + re.escape(COMMITS[agent]), span), span
    command = span.replace(COMMITS[agent], WORDS.replace("'", "'\\''")).replace("<the test command>", "true")
    assert not re.search(r"<[a-z][^<>]*>", command), command
    (repo / "cart.py").write_text("def total(items):\n    return sum(items or [0])\n", encoding="utf-8")
    done = projects.run(command, cwd=repo)
    assert done.returncode == 0, done.stderr
    subject = _git(repo, "log", "-1", "--format=%s").strip()
    assert WORDS in subject, subject
    assert projects.marks() == []
    assert _runs_under_its_own_hire(agent, command), command


def test_a_double_quoted_message_ran_its_backquotes_and_its_hire_refused_it(projects, repo):
    """The control: Bug Fixer's commit as it was. A backquote in the words
    ran, and its hire's `destructive: never` cannot read such a command, so
    the run's commit never happened."""
    old = 'true 2>&1 | tail -3 && git add -A && git commit -m "Fix: <the issue in a few words> (bug-fixer)"'
    command = old.replace("<the issue in a few words>", WORDS)
    assert not _runs_under_its_own_hire("bug-fixer", command)
    (repo / "cart.py").write_text("x = 1\n", encoding="utf-8")
    projects.run(command, cwd=repo)
    assert projects.marks() == ["My Projects/My Site/pwned6"]
    assert "items[0]" not in _git(repo, "log", "-1", "--format=%s")


# ── Archive Sorter: a file's name is a name ─────────────────────────────────

def test_archive_sorter_moves_a_file_named_like_a_command(projects):
    dump = projects.path / "Dump 2026"
    dump.mkdir()
    hostile = ["$(touch pwned7).pdf", "-n bill.pdf", "it's `touch pwned8`.pdf"]
    for name in hostile:
        (dump / name).write_text("x", encoding="utf-8")
    span = next(s for a, s in _cd_spans() if a == "archive-sorter")
    move = span.split(" && ")[2]
    assert move.startswith("mv -n -- '<file>' "), move
    moves = " && ".join(_fill_name(_fill_name(move, "<file>", n), "sorted/<category>/<YYYY-MM>-<short name>.<ext>",
                                   f"sorted/bills/2026-10-{i}.pdf") for i, n in enumerate(hostile))
    command = (_fill_name(span.split(" && ")[0], "<folder>", "Dump 2026") + " && "
               + _fill_name(span.split(" && ")[1].replace(" …", ""), "sorted/<category>", "sorted/bills") + " && "
               + moves + " && ls -R sorted")
    done = projects.run(command)
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in (dump / "sorted" / "bills").iterdir()) == [f"2026-10-{i}.pdf" for i in range(3)]
    assert projects.marks() == []
    assert _runs_under_its_own_hire("archive-sorter", command)


# ── Load Tester: an address is one word ─────────────────────────────────────

def test_load_tester_hands_hey_an_address_with_an_ampersand_whole(projects, tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    record = tmp_path / "hey.args"
    hey = bin_ / "hey"
    hey.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done >> {_q(str(record))}\n', encoding="utf-8")
    hey.chmod(hey.stat().st_mode | stat.S_IXUSR)
    span = next(s for s in re.findall(r"`([^`]+)`", _steps(get_agent(None, "load-tester").runbook))
                if s.startswith("for c in"))
    target = "https://staging.example/cart?a=1&b=2;touch pwned9"
    command = _fill_name(span, "<target>", target).replace("<users>", "20")
    projects.run(f"PATH={_q(str(bin_))}:$PATH; {command}")
    handed = record.read_text(encoding="utf-8").split("\n")[:-1]
    assert handed.count(target) == 4, handed
    assert projects.marks() == []
