# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1622` · What a command's words say it does to what is already there.

`_is_destructive_call('bash', 'rm -rf x')` was `False`: `bash` is registered
`execute_code` and nothing else, and no table looked inside the command. So
Disk Janitor's and File Converter's `destructive: ask` did nothing by itself,
Auto's one exception (`B1341`, *"Auto runs everything without asking, except
what cannot be undone"*) let a shell `rm -rf` through, and every agent's
`destructive: never` on a shell was a promise nothing checked.

This module reads a command the way a person reading it would, and answers one
question for `tool_capabilities.capabilities_for_action`: **does this call carry
`destructive`?** Yes when:

  * **it deletes or overwrites, by a program that does that** — `rm`, `rmdir`,
    `unlink`, `shred`, `truncate`, `dd of=`, `mkfs`, a partition tool, `kill`,
    `find -delete` (or `-exec rm`), `rsync --delete`, `ln -f`, removing a
    package, `dropdb`, a `DROP`/`DELETE`/`TRUNCATE` handed to a database
    client; `mv` unless it is told never to overwrite (`-n`, `--no-clobber`,
    `--backup`), because it replaces whatever had the new name; git's `push
    --force` (and `--mirror`, `--delete`, a `+refspec`), `reset --hard`,
    `clean`, `checkout -f`/`-- paths`, `restore`, `branch -D`, `stash drop`;
    Docker's `rm`, `rmi`, `kill` and every `prune`; `kubectl delete`; a
    redirection that only empties a file (`: > log`) or writes over a disk
    (`> /dev/sda`) — at any depth: after `sudo`, `env`, `xargs`, `timeout`,
    `nohup`, inside `$(…)`, `` `…` ``, `<(…)`, `sh -c '…'`, `ssh host '…'`
    and `docker exec`;
  * **or it cannot be read** — which program runs is decided only when it runs
    (`$cmd`, `$(…)`, a glob or `{a,b}` as the command word), `eval`, a shell or
    a language runtime handed its program in the command or on its standard
    input (`sh -c "$x"`, `curl … | sh`, `perl -e`, `node -e`, a here-document
    into `bash`, `source <(…)`), `awk` that runs commands, or text this reader
    cannot split (a quote left open). **A command whose effect cannot be read
    is never called safe**: it asks where a deletion would.

Python — the `python` tool's code, and `python -c` — is read by
`python_findings` the same way: a call to a deleting function (`os.remove`,
`shutil.rmtree`, a `.unlink()`), a deleting SQL string handed to `execute`, a
command handed to `os.system` or `subprocess` (read by the shell reader), and
`exec`/`eval`/`__import__`, or code that does not parse, as unreadable.

**`B1652` · and whether it reaches another machine.** The same reading answers
a second question: **does this call carry `network_egress`?** Yes when a
program whose use is reaching another machine runs — fetching (`curl`, `wget`,
`scp`, `rsync host:…`), connecting (`ssh`, `nc`, `telnet`), resolving or
measuring one (`dig`, `ping`, `traceroute`, `nmap`, a load generator) — or a
package manager or a version-control command does what fetches or publishes
(`pip install`, `npm ci`, `apt-get install`, `docker pull`, `git clone`,
`fetch`, `pull`, `push`), at the same depths as above; Python calling into a
network library (`requests`, `urllib.request`, `socket.create_connection`…)
or handed an address (`"https://…"`); **or the command cannot be read**: a
command whose network reach cannot be read is never called local. Before this,
Environment Setter's `pip install` was `execute_code` alone, so its hire's
`network_egress: ask` — *reach other sites and machines — asks you first* —
never asked.

**The adversary (`Law 17`), and where this stops.** What this holds against is
**a mistake** — the model reaching for `rm`, `mv` or `push --force` on its own
reading of a job, or with words copied from its notebook or a file's name — and
**a naive injection** that asks for one by name or hides it in the usual
wrappers (base64 into a shell, a fetched script piped to `sh`). It is *not* a
boundary against someone who controls the command: they write a script and
run it by name, and no reading of words stops that. A program run by name — a
script, `make`, a build, `python3 tool.py`, `npm test`, `cargo build` — does
what that program does; its command is read, the program is not, so a build
that fetches its dependencies is not read as reaching the network, and neither
is a library this module does not name. What holds against that adversary is
the post-external gate, which asks before **every** shell command once outside
content has entered the run (`FORBIDDEN.md` Part 2) and is untouched here:
this module only ever adds `destructive` or `network_egress` to a call, so it
can make Pantheon ask more, and never less.

**`B1669` · and what files it writes over.** A third answer, which this module
cannot give alone: `bash 'echo x > notes.md'` replaces `notes.md` if it was
there before the run began, and is a new file if not (`D-2026-10-29-02` §1,
*"Only pre-existing files"*, the ruling `write_file`'s `B1660` is built to).
So the reader names **what the command writes over** — a `writes` finding —
and leaves *whether it was there* to the run (`src/run_files.py`), which knows
where the command starts and what the run has already looked at:

  * a `>`, `>|` or `&>` redirection (and `>& file`), not `>>`, and not a
    device — `/dev/null`, `/dev/stderr`, `>&2` are not files;
  * `tee` without `-a`/`--append`;
  * `cp` and `install` onto a path: the destination, or each source's name
    inside it when it is a folder (`-t`, or a folder that is there), unless it
    is told never to overwrite (`-n`, `--no-clobber`, `--update=none`) or to
    keep what it replaces (`-b`, `--backup`), as `mv`'s rule reads them;

and **where the command goes** — a `chdir` finding — for each `cd`, `pushd`,
`env -C`, `sudo -D`, a Python `os.chdir` or a subprocess `cwd=`, so a relative
target is looked for wherever the command could be when it writes. A target or
a `cd` filled in when it runs (`> "$out"`, `cd "$dir"`) is marked not
`known`, and one inside a command run on another machine or in a container
(`ssh host '…'`, `docker exec`) is marked `far`: the run cannot know whether
either was there, so either is destructive — the cautious reading the ruling
names. Python's own `open(path, "w")` is **not** read: whether a mode string
writes, appends or reads is a property of the running program (a variable, a
`Path.write_text`, a library call), and this reader reads the words of a call,
not the program, so it stays what it was; its `subprocess` commands are read
as any shell command is.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
from dataclasses import dataclass, field, replace
from typing import Iterable, List, Optional, Sequence, Tuple

#: Longer than any command a person or a runbook writes; past it the reader
#: does not try (`B17`'s rule for a model-chosen size): unreadable.
MAX_COMMAND_CHARS = 64 * 1024
#: Substitutions inside `sh -c` inside `ssh` inside `sudo`…: past this depth
#: the command is unreadable rather than half-read.
MAX_DEPTH = 8

DESTROYS = "destroys"
UNREADABLE = "unreadable"
REACHES = "reaches"     # `B1652`: it reaches another machine
WRITES = "writes"       # `B1669`: it writes over a path, if one is there
CHDIR = "chdir"         # `B1669`: it moves to another folder before what follows


class _Unreadable(Exception):
    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class Finding:
    """One thing the reader found: `kind` is `destroys`, `reaches`,
    `unreadable`, `writes` or `chdir`.

    `B1669`. A `writes` finding's `why` is what writes (`a > redirect`, `tee`,
    `cp`, `install`) and `path` the path it names, as written; a `chdir`'s
    `path` is the folder. `known` is False when the path is filled in when the
    command runs; `far` when the command runs on another machine or in a
    container. `sources` are a copy's sources, `(path, known)`, and `into`
    whether its destination is a folder (`folder`, from `-t`), a file
    (`file`, from `-T`), or whichever is there (empty); `parents` is
    `cp --parents`, which keeps each source's whole path inside it."""
    kind: str
    why: str
    path: str = ""
    known: bool = True
    far: bool = False
    sources: Tuple[Tuple[str, bool], ...] = ()
    into: str = ""
    parents: bool = False


@dataclass
class _Word:
    text: str = ""           # the word after quote removal
    expanded: bool = False   # holds an expansion the shell fills in when it runs
    globbed: bool = False    # an unquoted * ? or [..] — names chosen when it runs
    braced: bool = False     # an unquoted {a,b} or {1..3} — one word that becomes several
    quoted: bool = False     # some part of it was quoted or escaped
    lead: str = ""           # what it starts with, up to its first quote or expansion
    body: Optional[str] = None  # a here-document's text, on its delimiter's word
    strip_tabs: bool = False    # `<<-`: its body's leading tabs are dropped

    def assignment(self) -> bool:
        """`NAME=value` — whatever the value is made of."""
        return bool(_ASSIGN_RE.match(self.lead))

    def plain(self) -> bool:
        return not (self.expanded or self.globbed or self.braced)

    def keyword(self, *names: str) -> bool:
        return self.plain() and not self.quoted and self.text in names


@dataclass
class _Simple:
    words: List[_Word] = field(default_factory=list)
    redirects: List[Tuple[str, _Word]] = field(default_factory=list)
    ended_by: str = ""


# ── Reading the words ───────────────────────────────────────────────────────

_OPS = ("&&", "||", ";;&", ";;", ";&", "|&", ";", "|", "&", "(", ")", "\n")
_REDIRS = ("<<<", "<<-", "<<", "<>", "<&", "&>>", "&>", ">>", ">|", ">&", "<", ">")
_STOP = " \t\r\n;&|()<>"
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
_BRACE_RE = re.compile(r"\{[^{}\s]*(,|\.\.)[^{}\s]*\}")
_GLOB_RE = re.compile(r"[*?]|\[[^\]]+\]")
_FILLED_IN = re.compile(r"[$`*?\[\]{}]")


def _word_is_plain_text(text: str) -> bool:
    """No expansion, glob or brace left in it."""
    return bool(text) and not _FILLED_IN.search(text)


class _Lexer:
    """Splits a command into words, operators and redirections, reading every
    substitution it meets as a command of its own."""

    def __init__(self, depth: int, findings: List[Finding], far: bool = False):
        if depth > MAX_DEPTH:
            raise _Unreadable("it nests commands deeper than this reader follows")
        self.depth = depth
        self.findings = findings
        # `B1669`: reading a command another machine or a container runs.
        self.far = far

    def sub(self, text: str) -> None:
        read_shell(text, depth=self.depth + 1, findings=self.findings, far=self.far)

    # Finding the end of a group, over quotes and nesting.
    def _closing(self, s: str, i: int, open_: str, close: str) -> int:
        depth = 1
        while i < len(s):
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                j = s.find("'", i + 1)
                if j < 0:
                    raise _Unreadable("a quote is left open")
                i = j + 1
                continue
            if ch == '"':
                i = self._dq_close(s, i + 1) + 1
                continue
            if ch == "`":
                i = self._bq_close(s, i + 1) + 1
                continue
            if ch == open_:
                depth += 1
            elif ch == close:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        raise _Unreadable(f"a “{open_}” is never closed")

    def _dq_close(self, s: str, i: int) -> int:
        while i < len(s):
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                return i
            if s.startswith("$(", i):
                i = self._closing(s, i + 2, "(", ")") + 1
                continue
            if ch == "`":
                i = self._bq_close(s, i + 1) + 1
                continue
            i += 1
        raise _Unreadable("a quote is left open")

    def _bq_close(self, s: str, i: int) -> int:
        while i < len(s):
            if s[i] == "\\":
                i += 2
                continue
            if s[i] == "`":
                return i
            i += 1
        raise _Unreadable("a backquote is left open")

    def substitutions_in(self, text: str) -> None:
        """Commands inside `${…}`, `$((…))` or an unquoted here-document."""
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if text.startswith("$(", i) and not text.startswith("$((", i):
                end = self._closing(text, i + 2, "(", ")")
                self.sub(text[i + 2:end])
                i = end + 1
                continue
            if ch == "`":
                end = self._bq_close(text, i + 1)
                self.sub(text[i + 1:end].replace("\\`", "`"))
                i = end + 1
                continue
            i += 1

    def _dollar(self, s: str, i: int, word: _Word, out: List[str]) -> int:
        """`s[i]` is `$`: an expansion, whose commands are read."""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if nxt == "'":
            # `$'…'` is decoded as it is read, and its escapes can spell any
            # word (`$'\x72\x6d'` is `rm`): a word that uses them is not read.
            j = i + 2
            while j < len(s) and s[j] != "'":
                if s[j] == "\\":
                    word.expanded = True
                    j += 1
                j += 1
            if j >= len(s):
                raise _Unreadable("a quote is left open")
            out.append(s[i + 2:j])
            word.quoted = True
            return j + 1
        if nxt == '"':
            return i + 1            # `$"…"`: a translated string, read as "…"
        if s.startswith("$((", i):
            end = self._closing(s, i + 3, "(", ")")
            if s.startswith(")", end + 1):
                word.expanded = True
                self.substitutions_in(s[i + 3:end])
                out.append(s[i:end + 2])
                return end + 2
        if nxt == "(":
            end = self._closing(s, i + 2, "(", ")")
            self.sub(s[i + 2:end])
            word.expanded = True
            out.append(s[i:end + 1])
            return end + 1
        if nxt == "{":
            end = self._closing(s, i + 2, "{", "}")
            self.substitutions_in(s[i + 2:end])
            word.expanded = True
            out.append(s[i:end + 1])
            return end + 1
        m = _NAME_RE.match(s, i + 1)
        if m:
            word.expanded = True
            out.append(s[i:m.end()])
            return m.end()
        if nxt and (nxt.isdigit() or nxt in "@*#?$!-"):
            word.expanded = True
            out.append(s[i:i + 2])
            return i + 2
        out.append("$")             # a dollar sign and nothing after it
        return i + 1

    def _word(self, s: str, i: int) -> Tuple[_Word, int]:
        word = _Word()
        out: List[str] = []
        unquoted: List[str] = []    # what the shell globs and brace-expands
        while i < len(s) and s[i] not in _STOP:
            ch = s[i]
            if ch == "\\":
                if i + 1 < len(s) and s[i + 1] != "\n":
                    out.append(s[i + 1])
                    word.quoted = True
                    unquoted.append(" ")
                i += 2
                continue
            if ch == "'":
                j = s.find("'", i + 1)
                if j < 0:
                    raise _Unreadable("a quote is left open")
                out.append(s[i + 1:j])
                word.quoted = True
                unquoted.append(" ")
                i = j + 1
                continue
            if ch == '"':
                word.quoted = True
                unquoted.append(" ")
                i = self._dq_word(s, i + 1, word, out)
                continue
            if ch == "$":
                i = self._dollar(s, i, word, out)
                unquoted.append(" ")
                continue
            if ch == "`":
                end = self._bq_close(s, i + 1)
                self.sub(s[i + 1:end].replace("\\`", "`"))
                word.expanded = True
                out.append(s[i:end + 1])
                unquoted.append(" ")
                i = end + 1
                continue
            out.append(ch)
            unquoted.append(ch)
            i += 1
        word.text = "".join(out)
        bare = "".join(unquoted)
        word.lead = bare.split(" ", 1)[0]
        word.globbed = bool(_GLOB_RE.search(bare))
        word.braced = bool(_BRACE_RE.search(bare))
        return word, i

    def _dq_word(self, s: str, i: int, word: _Word, out: List[str]) -> int:
        while i < len(s):
            ch = s[i]
            if ch == "\\" and i + 1 < len(s):
                if s[i + 1] in '$`"\\':
                    out.append(s[i + 1])
                elif s[i + 1] != "\n":
                    out.append(s[i:i + 2])
                i += 2
                continue
            if ch == '"':
                return i + 1
            if ch == "$":
                i = self._dollar(s, i, word, out)
                continue
            if ch == "`":
                end = self._bq_close(s, i + 1)
                self.sub(s[i + 1:end].replace("\\`", "`"))
                word.expanded = True
                out.append(s[i:end + 1])
                i = end + 1
                continue
            out.append(ch)
            i += 1
        raise _Unreadable("a quote is left open")

    def tokens(self, s: str) -> List[tuple]:
        """`("w", _Word)`, `("op", str)` and `("r", op, _Word)`, in order."""
        toks: List[tuple] = []
        heredocs: List[_Word] = []      # each delimiter's word, its body still to come
        redirect: Optional[str] = None
        i = 0
        while i < len(s):
            ch = s[i]
            if ch == "\\" and s.startswith("\n", i + 1):
                i += 2
                continue
            if ch in " \t\r":
                i += 1
                continue
            if ch == "#" and (i == 0 or s[i - 1] in " \t\n;&|()"):
                j = s.find("\n", i)
                i = len(s) if j < 0 else j
                continue
            if ch in "<>" and s.startswith("(", i + 1):
                end = self._closing(s, i + 2, "(", ")")
                self.sub(s[i + 2:end])
                word = _Word(text=s[i:end + 1], expanded=True)
                toks.append(("r", redirect, word) if redirect else ("w", word))
                redirect = None
                i = end + 1
                continue
            if redirect is None:
                op = next((o for o in _REDIRS if s.startswith(o, i)), None)
                if op is not None:
                    redirect = op
                    i += len(op)
                    continue
            op = next((o for o in _OPS if s.startswith(o, i)), None)
            if op is not None:
                if redirect is not None:
                    raise _Unreadable(f"a “{redirect}” has nothing after it")
                toks.append(("op", op))
                i += len(op)
                if op == "\n" and heredocs:
                    i = self._heredoc_bodies(s, i, heredocs)
                    heredocs = []
                continue
            word, i = self._word(s, i)
            if (redirect is None and i < len(s) and s[i] in "<>" and not word.quoted
                    and (word.text.isdigit() or re.fullmatch(r"\{[A-Za-z_]\w*\}", word.text))):
                continue            # `2>`, `{fd}>`: the descriptor of what follows
            if redirect is not None:
                toks.append(("r", redirect, word))
                if redirect in ("<<", "<<-"):
                    word.strip_tabs = redirect == "<<-"
                    heredocs.append(word)
                redirect = None
                continue
            toks.append(("w", word))
        if redirect is not None:
            raise _Unreadable(f"a “{redirect}” has nothing after it")
        return toks

    def _heredoc_bodies(self, s: str, i: int, heredocs: List[_Word]) -> int:
        for word in heredocs:
            strip = word.strip_tabs
            body = []
            while i < len(s):
                j = s.find("\n", i)
                line = s[i:] if j < 0 else s[i:j]
                i = len(s) if j < 0 else j + 1
                if (line.lstrip("\t") if strip else line) == word.text:
                    break
                body.append(line.lstrip("\t") if strip else line)
            word.body = "\n".join(body)
            if not word.quoted:
                # An unquoted delimiter: `$(…)` in the body runs, and `$x` is
                # filled in, so a program read from it is not the one written.
                self.substitutions_in(word.body)
                if "$" in word.body or "`" in word.body:
                    word.expanded = True
        return i


# ── Splitting into simple commands ──────────────────────────────────────────

_SKIP = ("!", "{", "}", "then", "else", "elif", "do", "if", "while", "until", "fi", "done",
         "coproc")
_NOT_A_COMMAND = ("for", "select", "function", "[[", "((")
_ARM_ENDS = (";;", ";&", ";;&")


def _simple_commands(tokens: Sequence[tuple]) -> List[_Simple]:
    """Simple commands, each with its own words and redirections. A `case`
    arm's pattern (`docx|odt)`) and a `[[ … ]]` test are not commands."""
    raw: List[_Simple] = []
    cur = _Simple()
    in_test = False
    for tok in tokens:
        if tok[0] == "op":
            if in_test and tok[1] in ("&&", "||", "(", ")"):
                continue
            cur.ended_by = tok[1]
            raw.append(cur)
            cur = _Simple()
        elif tok[0] == "r":
            cur.redirects.append((tok[1], tok[2]))
        else:
            word = tok[1]
            if not cur.words and word.keyword("[["):
                in_test = True
            elif in_test and word.keyword("]]"):
                in_test = False
            cur.words.append(word)
    raw.append(cur)

    out: List[_Simple] = []
    cases = 0
    expect_pattern = False
    for simple in raw:
        lead = next((w for w in simple.words if not w.keyword(*_SKIP)), None)
        if lead is not None and lead.keyword("case"):
            cases += 1
            # `case x in` alone on its line, or with its first pattern after it.
            expect_pattern = simple.ended_by != ")"
            continue
        if cases and lead is not None and lead.keyword("esac"):
            cases -= 1
            expect_pattern = False
            continue
        if cases and expect_pattern:
            # A pattern, or one of several (`docx|odt)`), or a blank line.
            if not simple.words or simple.ended_by in (")", "(", "|", "\n"):
                if simple.ended_by == ")":
                    expect_pattern = False
                continue
        if cases and simple.ended_by in _ARM_ENDS:
            expect_pattern = True
        out.append(simple)
    return out


# ── What each program does ──────────────────────────────────────────────────

#: Programs whose whole purpose is to delete, overwrite or end something.
_DELETERS = {
    "rm": "rm deletes files", "rmdir": "rmdir deletes folders", "unlink": "unlink deletes a file",
    "shred": "shred overwrites a file", "srm": "srm deletes files", "wipe": "wipe deletes files",
    "truncate": "truncate cuts a file short", "wipefs": "wipefs erases a disk's signatures",
    "blkdiscard": "blkdiscard discards a disk", "mkswap": "mkswap writes over a disk",
    "mke2fs": "mke2fs makes a filesystem over a disk", "fdisk": "fdisk rewrites a partition table",
    "sfdisk": "sfdisk rewrites a partition table", "cfdisk": "cfdisk rewrites a partition table",
    "parted": "parted rewrites a partition table", "sgdisk": "sgdisk rewrites a partition table",
    "gdisk": "gdisk rewrites a partition table", "pkill": "pkill ends processes",
    "killall": "killall ends processes", "xkill": "xkill ends a program",
    "dropdb": "dropdb deletes a database", "dropuser": "dropuser deletes a database user",
    "lvremove": "lvremove deletes a volume", "vgremove": "vgremove deletes a volume group",
    "pvremove": "pvremove wipes a volume",
}
#: A subcommand anywhere among the plain words removes what was installed.
_REMOVERS = {
    "apt": {"remove", "purge", "autoremove"}, "apt-get": {"remove", "purge", "autoremove"},
    "aptitude": {"remove", "purge"}, "yum": {"remove", "erase", "autoremove"},
    "dnf": {"remove", "erase", "autoremove"}, "zypper": {"remove", "rm"}, "apk": {"del"},
    "brew": {"uninstall", "remove", "rm"}, "snap": {"remove"}, "flatpak": {"uninstall"},
    "pip": {"uninstall"}, "pip3": {"uninstall"}, "npm": {"uninstall", "remove", "rm", "un", "r"},
    "pnpm": {"remove", "rm", "uninstall", "un"}, "yarn": {"remove"}, "gem": {"uninstall"},
    "cargo": {"uninstall"}, "conda": {"remove", "uninstall"}, "helm": {"uninstall", "delete"},
    "kubectl": {"delete"}, "zfs": {"destroy"}, "zpool": {"destroy"}, "virsh": {"undefine"},
}
#: Wrappers that run the rest of their words, and their options that take a value.
_WRAPPERS = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group",
             "--host", "--prompt", "--chdir", "--close-from", "--role", "--type",
             "--other-user", "--command-timeout"},
    "doas": {"-u", "-C"}, "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p", "-t"},
    "stdbuf": {"-i", "-o", "-e"}, "flock": {"-w", "-E", "--timeout", "--conflict-exit-code"},
    "strace": {"-o", "-e", "-p", "-s"}, "ltrace": {"-o", "-e"}, "nohup": set(), "time": {"-f", "-o"},
    "setsid": set(), "unbuffer": set(), "caffeinate": set(), "torsocks": set(),
    "proxychains": set(), "proxychains4": set(), "firejail": set(), "nocorrect": set(),
    "noglob": set(), "command": set(), "builtin": set(), "exec": {"-a"},
    "runuser": {"-u", "--user", "-g", "--group"}, "systemd-run": {"-u", "--unit", "-p", "--property"},
    "env": {"-u", "--unset", "-C", "--chdir"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "xargs": {"-I", "-i", "-n", "-P", "-L", "-l", "-s", "-d", "-E", "-e", "-a", "--arg-file",
              "--delimiter", "--max-args", "--max-procs", "--max-lines", "--max-chars",
              "--replace", "--eof", "--process-slot-var"},
    "watch": {"-n", "--interval", "-d"}, "taskset": set(), "chrt": set(),
}
#: Wrappers whose first plain word is theirs, not the command's.
_WRAPPER_TAKES_ONE = ("timeout", "taskset", "chrt", "flock")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "ash", "fish", "csh", "tcsh"})
#: Language runtimes, and the options that hand one its program inline.
_INLINE = {
    "perl": {"-e", "-E"}, "ruby": {"-e"}, "node": {"-e", "-p", "--eval", "--print"},
    "nodejs": {"-e", "-p", "--eval", "--print"}, "deno": {"eval"}, "bun": {"-e", "--eval"},
    "php": {"-r"}, "lua": {"-e"}, "luajit": {"-e"}, "rscript": {"-e"}, "osascript": {"-e"},
    "pwsh": {"-c", "-command", "-encodedcommand", "-e", "-ec"},
    "powershell": {"-c", "-command", "-encodedcommand", "-e", "-ec"}, "groovy": {"-e"},
}
_PROBES = {"--version", "-v", "-V", "--help", "-h", "-version", "-help"}
_AWKS = frozenset({"awk", "gawk", "mawk", "nawk"})
_PYTHON_RE = re.compile(r"^(python|pypy)(\d+(\.\d+)?)?$")
_DB_CLIENTS = {"psql": {"-c", "--command"}, "mysql": {"-e", "--execute"},
               "mariadb": {"-e", "--execute"}, "sqlite3": set(),
               "clickhouse-client": {"-q", "--query"}, "mongo": {"--eval"}, "mongosh": {"--eval"}}
_SQL_DESTROYS = re.compile(r"\b(drop\s+(table|database|schema|index|view|user|role)\b|delete\s+from\b|"
                           r"truncate\b|alter\s+table\b[^;]*\bdrop\b)|\.(drop|dropdatabase|"
                           r"deletemany|deleteone|remove)\s*\(", re.I)
_REDIS_DESTROYS = frozenset({"flushall", "flushdb", "del", "unlink", "getdel"})
_DEVICE_RE = re.compile(r"^/dev/(sd|hd|vd|xvd|nvme|mmcblk|disk|dm-|md|loop|mapper/)")

# ── `B1652` · what reaches another machine ──────────────────────────────────

#: Programs whose use is reaching another machine: fetching from it,
#: connecting to it, resolving, probing or loading it, or a cloud's own client.
_REACHERS = frozenset({
    "curl", "curlie", "wget", "wget2", "aria2c", "axel", "http", "https", "xh", "httpie",
    "lynx", "links", "elinks", "w3m", "nc", "ncat", "netcat", "socat", "telnet", "ftp", "lftp",
    "tftp", "sftp", "scp", "ssh", "mosh", "rsh", "rlogin", "rcp", "ping", "ping6", "fping",
    "hping3", "arping", "traceroute", "traceroute6", "tracepath", "mtr", "tcptraceroute", "dig",
    "nslookup", "host", "drill", "kdig", "whois", "nmap", "masscan", "zmap", "arp-scan",
    "iperf", "iperf3", "speedtest", "speedtest-cli", "ab", "wrk", "hey", "siege", "k6", "vegeta",
    "ntpdate", "sntp", "gh", "glab", "hub", "aws", "gcloud", "gsutil", "az", "doctl", "flyctl",
    "heroku", "vercel", "netlify", "wrangler", "rclone", "s3cmd", "yt-dlp", "youtube-dl",
    "gallery-dl", "certbot", "testssl", "testssl.sh", "sslscan", "sslyze", "nikto", "lighthouse",
    "pa11y", "sendmail", "msmtp", "swaks", "smbclient", "showmount", "snmpwalk", "snmpget",
    "grpcurl", "websocat", "wscat", "ldapsearch", "ansible", "ansible-playbook", "twine",
    "npx", "pnpx", "bunx", "uvx", "linkchecker", "lychee", "muffet", "httrack", "nuclei", "ffuf",
    "gobuster", "whatweb", "wpscan", "sqlmap",
})
#: Programs that reach another machine when one of their first plain words
#: is one of these: what installs, fetches, publishes or signs in.
_PIP_REACH = {"install", "download", "wheel", "index", "search"}
_CONDA_REACH = {"install", "create", "update", "upgrade", "search"}
_APT_REACH = {"install", "update", "upgrade", "full-upgrade", "dist-upgrade", "download", "source",
              "build-dep", "reinstall", "safe-upgrade"}
_RPM_REACH = {"install", "update", "upgrade", "makecache", "download", "check-update", "search",
              "reinstall", "groupinstall"}
_IMAGE_REACH = {"pull", "push", "login", "search"}
_REACH_SUBCOMMANDS = {
    "pip": _PIP_REACH, "pip3": _PIP_REACH,
    "pipx": {"install", "run", "upgrade", "upgrade-all", "inject", "reinstall", "reinstall-all"},
    "poetry": {"install", "add", "update", "lock", "publish", "search", "self"},
    "pipenv": {"install", "update", "lock", "sync", "upgrade"},
    "conda": _CONDA_REACH, "mamba": _CONDA_REACH, "micromamba": _CONDA_REACH,
    "npm": {"install", "i", "ci", "add", "update", "up", "upgrade", "publish", "unpublish", "view",
            "info", "show", "audit", "outdated", "search", "login", "adduser", "exec", "x", "init",
            "create", "dist-tag", "install-test", "it", "install-ci-test", "cit", "ping", "doctor",
            "whoami", "deprecate"},
    "pnpm": {"install", "i", "add", "update", "up", "upgrade", "dlx", "publish", "fetch", "outdated",
             "audit", "create"},
    "yarn": {"install", "add", "upgrade", "up", "dlx", "npm", "publish", "info", "outdated", "audit",
             "create", "set"},
    "bun": {"install", "i", "add", "a", "update", "x", "create", "c", "publish", "outdated", "upgrade"},
    "deno": {"install", "add", "upgrade", "cache"},
    "cargo": {"install", "fetch", "update", "add", "publish", "search", "login"},
    "go": {"get", "install"},
    "gem": {"install", "i", "update", "fetch", "push", "search"},
    "bundle": {"install", "update", "add", "lock", "outdated", "cache", "package"},
    "bundler": {"install", "update", "add", "lock", "outdated", "cache", "package"},
    "composer": {"install", "require", "update", "upgrade", "create-project", "global", "outdated",
                 "search"},
    "apt": _APT_REACH, "apt-get": _APT_REACH, "aptitude": _APT_REACH,
    "yum": _RPM_REACH, "dnf": _RPM_REACH, "microdnf": _RPM_REACH,
    "apk": {"add", "update", "upgrade", "fetch"},
    "zypper": {"install", "in", "refresh", "ref", "update", "up", "dup", "dist-upgrade",
               "source-install", "si", "download"},
    "brew": {"install", "update", "upgrade", "fetch", "tap", "search", "reinstall", "bundle"},
    "port": {"install", "selfupdate", "sync", "upgrade"},
    "snap": {"install", "refresh", "download"},
    "flatpak": {"install", "update", "remote-add", "search"},
    "docker": _IMAGE_REACH, "podman": _IMAGE_REACH, "nerdctl": _IMAGE_REACH,
    "helm": {"install", "upgrade", "pull", "push", "repo", "search", "dependency", "dep", "fetch",
             "registry"},
    "terraform": {"init", "plan", "apply", "destroy", "import", "refresh", "get", "providers",
                  "login"},
    "tofu": {"init", "plan", "apply", "destroy", "import", "refresh", "get", "providers", "login"},
    "ollama": {"pull", "push"},
    "huggingface-cli": {"download", "upload", "login", "repo"},
    "hf": {"download", "upload", "login", "repo"},
    "openssl": {"s_client", "s_time", "ocsp"},
}
#: A Python module run with `-m` that is one of the programs above.
_PY_MODULE_PROGRAMS = {"pip": "pip", "pipx": "pipx", "poetry": "poetry", "twine": "twine",
                       "uv": "uv", "pipenv": "pipenv"}
#: `git` subcommands that talk to a remote.
_GIT_REACH = {"clone", "fetch", "pull", "push", "ls-remote", "send-email", "request-pull"}
#: Options that keep a package manager or a package runner off the network.
_OFFLINE = {"--offline", "--no-install", "--no-index"}
#: `user@host:path`, `host:path`, `rsync://` or `host::module` — a remote end,
#: and not a Windows drive (`C:\`).
_REMOTE_PATH_RE = re.compile(r"^(?:rsync://|[^/:\s]+::|[^/:\s\\]{2,}:)")
#: Web clients whose every address may be this machine's own: a site served
#: here and fetched to test it (`curl http://localhost:8080/`) reaches no other
#: machine. Any other client, an address filled in when it runs, or an option
#: that sends the request somewhere else (a proxy, `--connect-to`, a list of
#: addresses read from a file) is read as reaching the network.
_WEB_CLIENTS = frozenset({"curl", "curlie", "wget", "wget2", "http", "https", "xh", "httpie", "ab",
                          "hey", "wrk", "siege", "lighthouse", "pa11y"})
_ELSEWHERE_OPTIONS = ("-x", "--proxy", "--preproxy", "--socks", "--connect-to", "--resolve",
                      "--doh-url", "-K", "--config", "--input-file", "--execute",
                      "--unix-socket", "--abstract-unix-socket")
#: `wget`'s short spellings of a list of addresses and a command to obey.
_WGET_ELSEWHERE = ("-i", "-e")
_ADDRESS_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:[^@/\s]*@)?"
                         r"(?P<host>\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._-]+)(?P<port>:\d+)?(?:[/?#]\S*)?$")
_LOOPBACK_RE = re.compile(r"^(?:localhost|[a-z0-9-]+\.localhost|ip6-localhost|127(?:\.\d{1,3}){3}|"
                          r"\[?::1\]?|0\.0\.0\.0)$", re.I)


#: Browsers and page renderers run from a command: they reach whatever address
#: they are handed (`chromium --headless --screenshot=… "$u"`).
_BROWSERS = frozenset({"chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                       "chrome", "firefox", "wkhtmltopdf", "wkhtmltoimage", "shot-scraper"})
_SCHEME_RE = re.compile(r"(?:^|=)(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>\S*)")


def _browser_reach(args: Sequence[_Word]) -> bool:
    """`B1652`. Whether a browser is handed an address on another machine, or
    one filled in when it runs."""
    for w in args:
        if not w.text.startswith("-") and not w.plain():
            return True
        m = _SCHEME_RE.search(w.text)
        if m and m["scheme"].lower() != "file":
            host = _ADDRESS_RE.match(f"{m['scheme']}://{m['rest']}")
            if not host or not _LOOPBACK_RE.match(host["host"]):
                return True
    return False


def _only_this_machine(name: str, args: Sequence[_Word]) -> bool:
    """`B1652`. Whether a web client's every address is this machine's own."""
    elsewhere = _ELSEWHERE_OPTIONS + (_WGET_ELSEWHERE if name.startswith("wget") else ())
    if any(w.text == o or w.text.startswith(o + "=") or (o.startswith("--") and w.text.startswith(o))
           for w in args for o in elsewhere):
        return False
    hosts = []
    for w in args:
        t = w.text
        if t.startswith("-") or t.startswith("/") or not t:
            continue
        m = _ADDRESS_RE.match(t)
        if not m or not ("://" in t or m["port"] or "." in m["host"] or _LOOPBACK_RE.match(m["host"])):
            continue
        if not w.plain():
            return False
        hosts.append(m["host"])
    return bool(hosts) and all(_LOOPBACK_RE.match(h) for h in hosts)


def _reach_of(name: str, args: Sequence[_Word]) -> Optional[str]:
    """`B1652`. Why running `name` with `args` reaches another machine, or
    `None`. A probe of the program itself (`--version`, `--help`) and a
    program named with nothing to do reach nothing."""
    texts = [w.text for w in args]
    if not texts or all(t in _PROBES for t in texts):
        return None
    flags = _flags(args)
    plain = [p.lower() for p in _plain_words(args)]
    if name in _REACHERS:
        if name in ("npx", "pnpx", "bunx", "uvx") and set(flags) & _OFFLINE:
            return None
        if name in _WEB_CLIENTS and _only_this_machine(name, args):
            return None
        return f"{name} reaches the network"
    if name in _BROWSERS:
        return f"{name} opens an address on the network" if _browser_reach(args) else None
    if name == "rsync":
        if any(_REMOTE_PATH_RE.match(t) for t in texts if not t.startswith("-")):
            return "rsync copies to or from another machine"
        return None
    if name == "git":
        return _git_reach(args)
    if name == "uv":
        if plain[:1] in (["add"], ["sync"], ["lock"], ["run"], ["tool"], ["python"]) or (
                plain[:1] == ["pip"] and plain[1:2] and plain[1] in _PIP_REACH | {"compile", "sync"}):
            return None if set(flags) & _OFFLINE else f"uv {' '.join(plain[:2])} fetches packages"
        return None
    if name == "go" and plain[:1] == ["mod"] and plain[1:2] and plain[1] in ("download", "tidy", "vendor"):
        return f"go mod {plain[1]} fetches modules"
    if name == "yarn" and not plain:
        return None if set(flags) & _OFFLINE else "yarn installs packages from the network"
    if name in ("docker", "podman", "nerdctl", "docker-compose"):
        return _image_reach(name, plain, flags)
    if name == "kubectl":
        if not plain or plain[0] in ("config", "completion", "kustomize", "plugin", "options") or (
                plain[0] == "version" and "--client" in flags):
            return None
        return "kubectl talks to a cluster"
    words = _REACH_SUBCOMMANDS.get(name)
    if words:
        hit = next((p for p in plain[:2] if p in words), None)
        if hit and not set(flags) & _OFFLINE:
            return f"{name} {hit} reaches the network"
    return None


def _git_reach(args: Sequence[_Word]) -> Optional[str]:
    with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                  "--config-env"}
    i = 0
    while i < len(args) and args[i].text.startswith("-"):
        i += 2 if args[i].text in with_value else 1
    if i >= len(args):
        return None
    sub = args[i].text
    plain = _plain_words(args[i + 1:])
    if sub in _GIT_REACH:
        return f"git {sub} talks to a remote"
    if sub == "submodule" and set(plain) & {"update", "add", "sync"}:
        return "git submodule fetches from a remote"
    if sub == "remote" and plain[:1] in (["update"], ["show"], ["prune"]):
        return f"git remote {plain[0]} talks to a remote"
    if sub == "lfs" and plain[:1] in (["fetch"], ["pull"], ["push"], ["clone"]):
        return f"git lfs {plain[0]} talks to a remote"
    if sub == "archive" and any(w.text.startswith("--remote") for w in args[i + 1:]):
        return "git archive --remote talks to a remote"
    return None


def _image_reach(name: str, plain: List[str], flags: List[str]) -> Optional[str]:
    if any(f.startswith(("--pull", "--push")) for f in flags):
        return f"{name} pulls or pushes an image"
    if not plain:
        return None
    rest = plain[1:] if plain[0] == "compose" else (plain if name == "docker-compose" else None)
    if rest is not None:
        hit = next((p for p in rest[:2] if p in ("pull", "push")), None)
        return f"{name} compose {hit} reaches a registry" if hit else None
    if plain[0] in _IMAGE_REACH:
        return f"{name} {plain[0]} reaches a registry"
    if len(plain) > 1 and plain[0] in ("image", "plugin", "trust") and plain[1] in (
            "pull", "push", "install", "sign"):
        return f"{name} {plain[0]} {plain[1]} reaches a registry"
    return None


def _handed(word: _Word) -> bool:
    """A script argument that is not a file named in the command: standard
    input, or a process substitution (`bash <(curl …)` is a fetched script
    piped to a shell)."""
    t = word.text
    return t in ("-", "/dev/stdin") or t.startswith(("<(", "/dev/fd/", "/proc/self/fd/"))


def _spelled(word: _Word) -> bool:
    """`B1669`. Whether a path is spelled out in the command: nothing in it is
    filled in when it runs — a `{}` is, by `find -exec` or `xargs -I` — and a
    `~` in front is the shell's own home (`~user` is someone else's, looked
    up when it runs)."""
    text = word.text
    return (word.plain() and bool(text) and "{}" not in text
            and (not text.startswith("~") or text == "~" or text.startswith("~/")))


def _replaces_through(op: str, target: _Word) -> bool:
    """`B1669`. Whether a redirection opens a file from its start — `>`, `>|`,
    `&>`, or `>&` onto a name rather than a descriptor (`>&2`, `2>&1`, `>&-`)
    — onto something that could be a file: not a device (`/dev/null`,
    `/dev/stderr`) and not a process (`> >(tee …)`, whose `tee` is read as a
    command of its own). `>>` and `<>` keep what is there."""
    text = target.text
    if op == ">&" and (text.isdigit() or text in ("-", "") or text.endswith("-")):
        return False
    return op in (">", ">|", "&>", ">&") and not text.startswith(("/dev/", ">(", "<("))


#: `B1669`. Options of `cp` and `install` that take a value, short and long.
_COPY_VALUES = {"cp": ("tS", {"--target-directory", "--suffix"}),
                "install": ("gmoSt", {"--group", "--mode", "--owner", "--suffix",
                                       "--target-directory", "--strip-program"})}


def _flags(words: Sequence[_Word]) -> List[str]:
    """The options as written, up to `--`."""
    out = []
    for w in words:
        if w.text == "--":
            break
        if w.text.startswith("-") and w.text != "-":
            out.append(w.text)
    return out


def _short(flags: Iterable[str], letter: str) -> bool:
    return any(not f.startswith("--") and letter in f[1:] for f in flags)


def _plain_words(words: Sequence[_Word]) -> List[str]:
    return [w.text for w in words if not w.text.startswith("-")]


def _past_options(words: Sequence[_Word], with_value: set) -> List[_Word]:
    i = 0
    while i < len(words):
        t = words[i].text
        if t == "--":
            return list(words[i + 1:])
        if not t.startswith("-") or t == "-":
            break
        i += 2 if t in with_value else 1
    return list(words[i:])


class _Judge:
    def __init__(self, lexer: _Lexer):
        self.lexer = lexer
        self.findings = lexer.findings

    def destroys(self, why: str) -> None:
        self.findings.append(Finding(DESTROYS, why))

    def unreadable(self, why: str) -> None:
        self.findings.append(Finding(UNREADABLE, why))

    def reaches(self, why: str) -> None:
        self.findings.append(Finding(REACHES, why))

    def writes(self, why: str, word: _Word, sources: Sequence[_Word] = (), into: str = "",
               parents: bool = False) -> None:
        """`B1669`. `why` writes over `word`'s path, if one is there."""
        self.findings.append(Finding(
            WRITES, why, path=word.text, known=_spelled(word), far=self.lexer.far,
            sources=tuple((w.text, _spelled(w)) for w in sources), into=into, parents=parents))

    def chdir(self, word: Optional[_Word]) -> None:
        """`B1669`. What follows runs in another folder — `None`: one only
        known when it runs (`cd` alone, `cd -`, `pushd +1`)."""
        self.findings.append(Finding(CHDIR, "cd", path=word.text if word else "",
                                     known=word is not None and _spelled(word), far=self.lexer.far))

    def shell_string(self, word: _Word, who: str = "a shell") -> None:
        """A command handed over as one string — `sh -c '…'`, `ssh host '…'`."""
        if word.plain():
            self.lexer.sub(word.text)
        else:
            self.unreadable(f"{who} is handed a command made when it runs")

    def simple(self, simple: _Simple) -> None:
        for op, target in simple.redirects:
            if op in (">", ">|", "&>", "<>", ">&") and _DEVICE_RE.match(target.text):
                self.destroys(f"it writes over the disk {target.text}")
            elif _replaces_through(op, target):
                # `B1669`: a file it writes from the start, if one is there.
                self.writes("a > redirect", target)
        words = list(simple.words)
        while words and words[0].keyword(*_SKIP):
            words.pop(0)
        if words and words[0].keyword(*_NOT_A_COMMAND):
            return
        while words and words[0].assignment():
            words.pop(0)
        if not words:
            self._empties(simple)
            return
        self.command(words, simple)

    def _empties(self, simple: _Simple) -> None:
        for op, target in simple.redirects:
            if op in (">", ">|") and target.text and not target.text.startswith("/dev/"):
                self.destroys(f"it empties {target.text}")

    def command(self, words: List[_Word], simple: _Simple) -> None:
        first = words[0]
        name = os.path.basename(first.text.replace("\\", "/")).lower()
        if not first.plain() and (
                "/" not in first.text or not _word_is_plain_text(name)):
            # `$cmd`, `$(…)`, `*`, `{a,b}`: the program itself is chosen when
            # it runs. (`$DIR/run.sh` names its program; only its folder is
            # filled in, and the program is judged by its name.)
            self.unreadable(f"which program runs is decided only when it runs ({first.text[:40]})")
            return
        if name.endswith(".exe"):
            name = name[:-4]
        args = words[1:]
        if name in (":", "true"):
            self._empties(simple)
            return
        if name == "command" and args and args[0].text in ("-v", "-V"):
            return
        if name in _WRAPPERS:
            self._wrapper(name, args, simple)
            return
        if name == "eval":
            self.unreadable("eval runs text as a command")
            return
        if name in ("source", "."):
            if args and _handed(args[0]):
                self.unreadable(f"{name} runs commands it is handed when it runs")
            return
        if name == "busybox":
            if args:
                self.command(args, simple)
            return
        if name in _SHELLS:
            self._shell(name, args, simple)
            return
        if _PYTHON_RE.match(name):
            self._python(args, simple)
            return
        if name in _INLINE:
            self._inline(name, args)
            return
        if name in _AWKS:
            self._awk(args)
            return
        if name in ("cd", "pushd", "chdir"):
            # `B1669`: what follows runs there. `cd` alone or to `~` is the
            # home; `cd -` and `pushd +1` go back to a folder decided earlier.
            rest = [w for w in args if not (w.text.startswith("-") and len(w.text) > 1)
                    and not w.text.startswith("+")]
            if args and any(w.text == "-" or w.text[:1] in "+-" and w.text[1:].isdigit()
                            for w in args):
                self.chdir(None)
            else:
                self.chdir(rest[0] if rest else _Word(text="~"))
            return
        if name == "popd":
            return                          # back to a folder this command was in
        # `B1652`. Whether it reaches another machine is asked of every program
        # from here on; what it deletes is asked below, as before — `rsync
        # --delete host:dir`, `git push --force` and `ssh host 'rm …'` do both.
        reach = _reach_of(name, args)
        if reach:
            self.reaches(reach)
        if name in _DELETERS:
            self.destroys(_DELETERS[name])
            return
        if name == "kill":
            if not any(w.text in ("-0", "-l", "-L", "--list") for w in args):
                self.destroys("kill ends a process")
            return
        if name.startswith("mkfs"):
            self.destroys(f"{name} makes a filesystem over a disk")
            return
        if name == "dd":
            if any(w.text.startswith("of=") for w in args):
                self.destroys("dd writes over its output")
            return
        if name == "mv":
            flags = _flags(args)
            kept = (_short(flags, "n") or _short(flags, "b") or "--no-clobber" in flags
                    or any(f.startswith("--backup") or f in ("--update=none", "--update=none-fail")
                           for f in flags))
            if _short(flags, "f") or "--force" in flags or not kept:
                self.destroys("mv replaces whatever already has the new name")
            return
        if name == "tee":
            # `B1669`: each file it is handed, from its start — unless `-a`.
            flags = _flags(args)
            if not (_short(flags, "a") or "--append" in flags):
                ended = False
                for w in args:
                    if not ended and w.text == "--":
                        ended = True
                    elif ((ended or not w.text.startswith("-"))
                          and not w.text.startswith(("/dev/", ">(", "<("))):
                        self.writes("tee", w)
            return
        if name in _COPY_VALUES:
            self._copies(name, args)
            return
        if name == "ln":
            flags = _flags(args)
            if _short(flags, "f") or "--force" in flags:
                self.destroys("ln -f replaces whatever had the link's name")
            return
        if name == "find":
            self._find(args)
            return
        if name == "rsync":
            if any(f.startswith("--del") or f == "--remove-source-files" for f in _flags(args)):
                self.destroys("rsync deletes on the far side")
            return
        if name == "git":
            self._git(args)
            return
        if name in ("docker", "podman", "nerdctl", "docker-compose"):
            self._docker(name, args)
            return
        if name == "crontab":
            if "-r" in _flags(args):
                self.destroys("crontab -r deletes every scheduled job")
            return
        if name == "journalctl":
            if any(f.startswith("--vacuum") for f in _flags(args)):
                self.destroys("journalctl --vacuum deletes logs")
            return
        if name == "dpkg":
            flags = _flags(args)
            if _short(flags, "r") or _short(flags, "P") or {"--remove", "--purge"} & set(flags):
                self.destroys("dpkg removes a package")
            return
        if name == "pacman":
            if any(f.startswith("-R") or f == "--remove" for f in _flags(args)):
                self.destroys("pacman removes a package")
            return
        if name == "mysqladmin":
            if "drop" in [w.text.lower() for w in args]:
                self.destroys("mysqladmin drop deletes a database")
            return
        if name == "redis-cli":
            if {w.text.lower() for w in args} & _REDIS_DESTROYS:
                self.destroys("redis-cli deletes keys")
            return
        if name in _DB_CLIENTS:
            self._database(name, args)
            return
        if name in _REMOVERS:
            plain = [p.lower() for p in _plain_words(args)]
            hit = next((p for p in plain if p in _REMOVERS[name]), None)
            if hit:
                self.destroys(f"{name} {hit} removes what is there")
            if name == "kubectl" and "exec" in plain:
                rest = next((args[j + 1:] for j, w in enumerate(args) if w.text == "--"), [])
                self._remote(rest)
            return
        if name == "uv":
            plain = _plain_words(args)
            if plain[:2] == ["pip", "uninstall"] or plain[:1] == ["remove"]:
                self.destroys("uv removes a package")
            return
        if name == "ssh":
            self._ssh(args)
            return
        if name == "su":
            for j, w in enumerate(args):
                if w.text in ("-c", "--command") and j + 1 < len(args):
                    self.shell_string(args[j + 1], "su")
            return

    # ── particular programs ────────────────────────────────────────────────

    def _wrapper(self, name: str, args: List[_Word], simple: _Simple) -> None:
        if name == "env" and any(w.text in ("-S", "--split-string")
                                 or w.text.startswith("--split-string=") for w in args):
            self.unreadable("env -S splits a string into a command")
            return
        rest = _past_options(args, _WRAPPERS[name])
        if name in ("env", "sudo"):
            # `B1669`: `env -C dir` and `sudo -D dir` run the rest in `dir`.
            moves = ("-C", "--chdir") if name == "env" else ("-D", "--chdir")
            options = args[:len(args) - len(rest)]
            for j, w in enumerate(options):
                if w.text in moves and j + 1 < len(options):
                    self.chdir(options[j + 1])
                elif w.text.startswith("--chdir="):
                    self.chdir(replace(w, text=w.text.split("=", 1)[1]))
        if name in _WRAPPER_TAKES_ONE:
            rest = rest[1:]
        if name == "env":
            while rest and rest[0].assignment():
                rest = rest[1:]
        if name == "sudo" and not rest and ({"-s", "-i", "--shell", "--login"} & set(_flags(args))):
            self.unreadable("sudo -s runs a shell that reads its commands from its input")
            return
        if name == "watch" and len(rest) == 1:
            self.shell_string(rest[0], "watch")
            return
        if name == "xargs" and not rest:
            return                          # `xargs` alone runs `echo`
        if rest:
            self.command(rest, simple)

    def _stdin(self, simple: _Simple, who: str, read) -> None:
        """A program read from standard input: a here-document or here-string
        written in the command is read by `read`; anything else — a pipe, a
        download — was handed over when it ran, and is not."""
        for op, target in reversed(simple.redirects):
            if op in ("<<", "<<-", "<<<"):
                text = target.body if op != "<<<" else target.text
                if text is None or not target.plain():
                    self.unreadable(f"{who} reads a program filled in when it runs")
                else:
                    read(text)
                return
            if op == "<":
                if _handed(target):
                    self.unreadable(f"{who} reads a program it is handed when it runs")
                return              # a script file, run by name
        self.unreadable(f"{who} reads its program from its input")

    def _shell(self, name: str, args: List[_Word], simple: _Simple) -> None:
        i = 0
        while i < len(args):
            t = args[i].text
            if t == "--":
                i += 1
                break
            if t in _PROBES:
                return
            if t.startswith("-") and len(t) > 1 and not t.startswith("--"):
                if "c" in t[1:]:
                    if i + 1 < len(args):
                        self.shell_string(args[i + 1], name)
                    else:
                        self.unreadable(f"{name} -c is handed no command")
                    return
                if "s" in t[1:]:
                    self._stdin(simple, name, self.lexer.sub)
                    return
                i += 2 if t in ("-o", "+o", "-O", "+O") else 1
                continue
            if t.startswith(("--", "+")):
                i += 1
                continue
            break
        rest = args[i:]
        if not rest:
            self._stdin(simple, name, self.lexer.sub)
        elif _handed(rest[0]):
            self.unreadable(f"{name} runs a script it is handed when it runs")

    def _python(self, args: List[_Word], simple: _Simple) -> None:
        def read(code: str) -> None:
            self.findings.extend(python_findings(code, depth=self.lexer.depth + 1))

        i = 0
        while i < len(args):
            w = args[i]
            t = w.text
            if t in _PROBES:
                return
            if t == "-c" or (t.startswith("-c") and not t.startswith("--")):
                code = args[i + 1] if t == "-c" and i + 1 < len(args) else (
                    _Word(text=t[2:]) if t != "-c" else None)
                if code is None:
                    self.unreadable("python -c is handed no code")
                elif not code.plain():
                    self.unreadable("python -c is handed code made when it runs")
                else:
                    read(code.text)
                return
            if t == "-m":
                # A module run by name — except the ones that are a program
                # this reader reads (`python -m pip install`, `B1652`), read
                # as that program.
                module = args[i + 1].text if i + 1 < len(args) else ""
                if module in _PY_MODULE_PROGRAMS:
                    self.command([_Word(text=_PY_MODULE_PROGRAMS[module])] + list(args[i + 2:]), simple)
                return
            if t == "-":
                self._stdin(simple, "python", read)
                return
            if t in ("-W", "-X"):
                i += 2
                continue
            if t.startswith("-"):
                i += 1
                continue
            if _handed(w):
                self.unreadable("python runs a program it is handed when it runs")
            return                          # a script run by name
        self._stdin(simple, "python", read)

    def _inline(self, name: str, args: List[_Word]) -> None:
        inline = _INLINE[name]
        lowered = [w.text.lower() for w in args]
        if any(t in _PROBES for t in lowered):
            return
        hands = any(t in inline or (t.startswith("--") and t.split("=", 1)[0] in inline)
                    for t in lowered)
        if name in ("perl", "ruby"):
            hands = hands or any(t.startswith("-") and not t.startswith("--") and "e" in t[1:]
                                 for t in lowered)
        if hands:
            self.unreadable(f"{name} is handed a program in the command, which this does not read")
        elif not _plain_words(args):
            self.unreadable(f"{name} reads its program from its input")

    def _awk(self, args: List[_Word]) -> None:
        i = 0
        while i < len(args):
            t = args[i].text
            if t in ("-f", "--file") or t in _PROBES:
                return
            if t in ("-v", "-F", "--assign", "--field-separator"):
                i += 2
                continue
            if t.startswith("-"):
                i += 1
                continue
            program = args[i].text
            if re.search(r"\bsystem\s*\(|\|\s*getline|\|&|\bprint[f]?\b[^;}]*\|", program):
                self.unreadable("awk runs commands from its program")
            return

    def _find(self, args: List[_Word]) -> None:
        i = 0
        while i < len(args):
            t = args[i].text
            if t == "-delete":
                self.destroys("find -delete deletes what it finds")
            elif t in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                sub = []
                while j < len(args) and args[j].text not in (";", "+"):
                    sub.append(args[j])
                    j += 1
                if sub:
                    self.command(sub, _Simple())
                i = j
            i += 1

    def _copies(self, name: str, args: List[_Word]) -> None:
        """`B1669`. `cp` or `install`: what it writes over, read as GNU reads
        its words — options anywhere before `--`, a short option's value
        joined to it or the next word."""
        shorts, longs = _COPY_VALUES[name]
        flags: set = set()
        operands: List[_Word] = []
        folder: Optional[_Word] = None
        ended = False
        i = 0
        while i < len(args):
            w = args[i]
            t = w.text
            i += 1
            if ended or t == "-" or not t.startswith("-"):
                operands.append(w)
                continue
            if t == "--":
                ended = True
                continue
            if t.startswith("--"):
                key, eq, value = t.partition("=")
                flags.add(key)
                if key in longs and not eq:
                    if i >= len(args):
                        return                      # it refuses: nothing copied
                    value_word, i = args[i], i + 1
                else:
                    value_word = replace(w, text=value)
                if key == "--target-directory":
                    folder = value_word
                elif eq:
                    flags.add(f"{key}={value}")
                continue
            for j, letter in enumerate(t[1:], start=1):
                flags.add("-" + letter)
                if letter in shorts:
                    if j + 1 < len(t):
                        value_word = replace(w, text=t[j + 1:])
                    elif i < len(args):
                        value_word, i = args[i], i + 1
                    else:
                        return
                    if letter == "t":
                        folder = value_word
                    break
        if name == "install" and ({"-d", "--directory"} & flags):
            return                                  # it makes folders
        if {"-n", "--no-clobber", "-b", "--backup", "--update=none", "--update=none-fail"} & flags:
            return                                  # it never overwrites, or keeps what it would
        parents = "--parents" in flags
        if folder is not None:
            if operands:
                self.writes(name, folder, sources=operands, into="folder", parents=parents)
        elif len(operands) >= 2:
            into = "file" if ({"-T", "--no-target-directory"} & flags) else ""
            self.writes(name, operands[-1], sources=operands[:-1], into=into, parents=parents)

    def _git(self, args: List[_Word]) -> None:
        with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                      "--config-env"}
        i = 0
        while i < len(args) and args[i].text.startswith("-"):
            i += 2 if args[i].text in with_value else 1
        if i >= len(args):
            return
        sub = args[i].text
        rest = args[i + 1:]
        flags = _flags(rest)
        plain = _plain_words(rest)
        if sub == "push":
            if (_short(flags, "f") or _short(flags, "d")
                    or any(f.startswith(("--force", "--mirror", "--delete", "--prune")) for f in flags)
                    or any(p.startswith(("+", ":")) for p in plain)):
                self.destroys("git push --force replaces what the remote had")
        elif sub == "reset":
            if {"--hard", "--merge", "--keep"} & set(flags):
                self.destroys("git reset --hard throws away work")
        elif sub == "clean":
            if not (_short(flags, "n") or "--dry-run" in flags):
                self.destroys("git clean deletes files git does not track")
        elif sub in ("checkout", "switch"):
            if (_short(flags, "f") or {"--force", "--discard-changes"} & set(flags)
                    or any(w.text == "--" for w in rest) or "." in plain):
                self.destroys(f"git {sub} throws away changes")
        elif sub == "restore":
            if not (("--staged" in flags or _short(flags, "S"))
                    and not ("--worktree" in flags or _short(flags, "W"))):
                self.destroys("git restore throws away changes")
        elif sub == "branch":
            if (any(_short(flags, c) for c in "DdMCf") or {"--delete", "--force"} & set(flags)):
                self.destroys("git branch deletes or replaces a branch")
        elif sub == "stash":
            if plain[:1] in (["drop"], ["clear"]):
                self.destroys("git stash drop deletes saved work")
        elif sub == "tag":
            if _short(flags, "d") or _short(flags, "f") or {"--delete", "--force"} & set(flags):
                self.destroys("git tag deletes or replaces a tag")
        elif sub == "rm":
            if "--cached" not in flags:
                self.destroys("git rm deletes files")
        elif sub == "mv":
            if _short(flags, "f") or "--force" in flags:
                self.destroys("git mv -f replaces a file")
        elif sub in ("filter-branch", "filter-repo"):
            self.destroys(f"git {sub} rewrites history")
        elif sub == "reflog":
            if plain[:1] in (["expire"], ["delete"]):
                self.destroys("git reflog expire deletes the way back")
        elif sub == "update-ref":
            if _short(flags, "d"):
                self.destroys("git update-ref -d deletes a ref")
        elif sub in ("worktree", "remote"):
            if plain[:1] in (["remove"], ["rm"], ["prune"]):
                self.destroys(f"git {sub} {plain[0]} deletes")
        elif sub == "gc":
            if any(f.startswith("--prune") for f in flags):
                self.destroys("git gc --prune deletes unreachable work")

    def _docker(self, name: str, args: List[_Word]) -> None:
        plain = _plain_words(args)
        if not plain:
            return
        if plain[0] == "exec" and name != "docker-compose":
            at = next(j for j, w in enumerate(args) if w.text == "exec")
            rest = _past_options(args[at + 1:], {"-e", "--env", "-u", "--user", "-w", "--workdir",
                                                 "--env-file", "--detach-keys"})
            self._remote(rest[1:])
            return
        ends = {"rm", "rmi", "kill", "prune"}
        objects = ("container", "image", "volume", "network", "system", "builder", "buildx",
                   "context", "plugin", "secret", "config", "service", "stack", "node")
        if plain[0] in ends or (len(plain) > 1 and plain[0] in objects and plain[1] in ends | {"remove"}):
            self.destroys(f"{name} {' '.join(plain[:2])} deletes")
            return
        compose = plain[1:] if plain[0] == "compose" else (plain if name == "docker-compose" else None)
        if compose:
            flags = _flags(args)
            if compose[:1] == ["rm"] or (compose[:1] == ["down"] and (
                    _short(flags, "v") or {"--volumes", "--rmi"} & set(flags))):
                self.destroys(f"{name} compose deletes containers or volumes")

    def _remote(self, words: List[_Word]) -> None:
        """A command another machine or container runs."""
        if not words:
            return
        # `B1669`: a file it writes over is on the far side, which the run
        # cannot look at.
        was, self.lexer.far = self.lexer.far, True
        try:
            if len(words) == 1:
                self.shell_string(words[0], "the far side")
            else:
                self.command(words, _Simple())
        finally:
            self.lexer.far = was

    def _ssh(self, args: List[_Word]) -> None:
        with_value = set("bcDEeFIiJLlmOopQRSWw")
        i = 0
        while i < len(args):
            t = args[i].text
            if t == "--":
                i += 1
                break
            if t.startswith("-") and len(t) > 1:
                i += 2 if (len(t) == 2 and t[1] in with_value) else 1
                continue
            break
        self._remote(args[i + 1:])          # past the host

    def _database(self, name: str, args: List[_Word]) -> None:
        opts = _DB_CLIENTS[name]
        texts: List[str] = []
        for j, w in enumerate(args):
            if w.text in opts and j + 1 < len(args):
                texts.append(args[j + 1].text)
            elif w.text.startswith("--") and w.text.split("=", 1)[0] in opts:
                texts.append(w.text.split("=", 1)[1])
        if name == "sqlite3":
            texts.extend(_plain_words(args)[1:])
        if any(_SQL_DESTROYS.search(t) for t in texts):
            self.destroys(f"{name} is handed a statement that deletes")


# ── The readers ─────────────────────────────────────────────────────────────

def read_shell(command: str, *, depth: int = 0,
               findings: Optional[List[Finding]] = None, far: bool = False) -> List[Finding]:
    """Everything the reader finds in a shell command. Never raises: what it
    cannot read is itself a finding. `far` (`B1669`): the command runs on
    another machine or in a container."""
    findings = findings if findings is not None else []
    text = str(command or "")
    if len(text) > MAX_COMMAND_CHARS:
        findings.append(Finding(UNREADABLE, "it is longer than this reader reads"))
        return findings
    try:
        lexer = _Lexer(depth, findings, far)
        judge = _Judge(lexer)
        for simple in _simple_commands(lexer.tokens(text)):
            judge.simple(simple)
    except _Unreadable as e:
        findings.append(Finding(UNREADABLE, e.why))
    except RecursionError:
        findings.append(Finding(UNREADABLE, "it nests commands deeper than this reader follows"))
    return findings


_PY_DESTROYS = {
    "os.remove": "os.remove deletes a file", "os.unlink": "os.unlink deletes a file",
    "os.rmdir": "os.rmdir deletes a folder", "os.removedirs": "os.removedirs deletes folders",
    "os.truncate": "os.truncate cuts a file short", "os.rename": "os.rename replaces a name",
    "os.replace": "os.replace replaces a file", "os.renames": "os.renames replaces a name",
    "os.kill": "os.kill ends a process", "os.killpg": "os.killpg ends processes",
    "shutil.rmtree": "shutil.rmtree deletes a folder", "shutil.move": "shutil.move replaces a name",
}
#: Methods whose name says what they do whatever they are called on. (`rename`
#: and `replace` are not here: a table's and a string's look the same.)
_PY_METHODS = {"unlink": "deletes a file", "rmdir": "deletes a folder", "rmtree": "deletes a folder"}
_PY_UNREADABLE = {"exec", "eval", "compile", "__import__", "importlib.import_module",
                  "runpy.run_path", "runpy.run_module", "runpy.run_code"}
_PY_SHELL = {"os.system", "os.popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
             "subprocess.check_output", "subprocess.Popen", "subprocess.getoutput",
             "subprocess.getstatusoutput", "pty.spawn"}
_PY_SPAWN = ("os.exec", "os.spawn", "os.posix_spawn")
_PY_SQL = {"execute", "executescript", "executemany", "exec_driver_sql"}
#: `B1652`. Calls into these modules reach another machine, whatever they are
#: handed (a client built here is the start of a request).
_PY_NET_MODULES = ("requests", "httpx", "urllib.request", "urllib3", "http.client", "aiohttp",
                   "ftplib", "smtplib", "poplib", "imaplib", "nntplib", "telnetlib", "paramiko",
                   "websocket", "websockets", "xmlrpc.client", "pycurl", "asyncssh", "fabric",
                   "boto3", "botocore", "dns.resolver", "urllib.urlopen", "urllib2")
#: The parts of `socket` and `ssl` that connect or resolve; the rest of them
#: (`socket.gethostname`, `ssl.create_default_context`) is local.
_PY_NET_CALLS = {"socket.socket", "socket.create_connection", "socket.getaddrinfo",
                 "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr",
                 "socket.getfqdn", "ssl.get_server_certificate", "webbrowser.open"}
_PY_ADDRESS_RE = re.compile(r"^\s*(https?|ftp|wss?|sftp)://", re.I)


def _dotted(node, aliases) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(aliases.get(node.id, node.id))
    return ".".join(reversed(parts))


def _literal(node) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def python_findings(code: str, *, depth: int = 0) -> List[Finding]:
    """What Python `code` deletes, and what in it cannot be read. Never raises."""
    if depth > MAX_DEPTH:
        return [Finding(UNREADABLE, "it nests commands deeper than this reader follows")]
    text = str(code or "")
    if len(text) > MAX_COMMAND_CHARS:
        return [Finding(UNREADABLE, "it is longer than this reader reads")]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [Finding(UNREADABLE, "the Python does not parse")]
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    findings: List[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func, aliases)
        # `B1652`. A call into a network library, or handed an address.
        if name in _PY_NET_CALLS or any(name == m or name.startswith(m + ".") for m in _PY_NET_MODULES):
            findings.append(Finding(REACHES, f"{name} reaches the network"))
        elif any(_PY_ADDRESS_RE.match(_literal(a) or "")
                 for a in list(node.args) + [k.value for k in node.keywords]):
            findings.append(Finding(REACHES, f"{name or 'a call'} is handed an address on the network"))
        if name in _PY_DESTROYS:
            findings.append(Finding(DESTROYS, _PY_DESTROYS[name]))
        elif name in _PY_UNREADABLE:
            findings.append(Finding(UNREADABLE, f"{name} runs code this does not read"))
        elif name == "os.chdir":
            # `B1669`: the commands it runs after this start there.
            folder = _literal(node.args[0]) if node.args else None
            findings.append(Finding(CHDIR, "os.chdir", path=folder or "",
                                    known=bool(folder) and not folder.startswith("~")))
        elif name in _PY_SHELL or name.startswith(_PY_SPAWN):
            first = node.args[0] if node.args else next(
                (k.value for k in node.keywords if k.arg in ("args", "cmd", "command")), None)
            cwd = next((k.value for k in node.keywords if k.arg == "cwd"), None)
            if cwd is not None:
                # `B1669`: this command starts in `cwd`.
                folder = _literal(cwd)
                findings.append(Finding(CHDIR, "cwd", path=folder or "",
                                        known=bool(folder) and not folder.startswith("~")))
            if _literal(first) is not None:
                read_shell(_literal(first), depth=depth + 1, findings=findings)
            elif isinstance(first, (ast.List, ast.Tuple)) and first.elts and _literal(first.elts[0]):
                # The program is named; an argument filled in when it runs is a
                # placeholder, which the reader sees as an expansion.
                line = " ".join(shlex.quote(_literal(e)) if _literal(e) is not None else "$ARG"
                                for e in first.elts)
                read_shell(line, depth=depth + 1, findings=findings)
            else:
                findings.append(Finding(UNREADABLE, f"{name} runs a command made when it runs"))
        elif isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if method in _PY_METHODS:
                findings.append(Finding(DESTROYS, f".{method}() {_PY_METHODS[method]}"))
            elif method in _PY_SQL and node.args and _literal(node.args[0]) is not None \
                    and _SQL_DESTROYS.search(_literal(node.args[0])):
                findings.append(Finding(DESTROYS, "it hands a database a statement that deletes"))
    return findings


def reason(findings: Sequence[Finding], kind: str = DESTROYS) -> Optional[str]:
    """Why these findings carry `destructive` (`kind` `destroys`) or
    `network_egress` (`kind` `reaches`, `B1652`), or `None` when nothing was
    found: what the command does first, since it is the plainer sentence, and
    then that it cannot be read — which carries both."""
    for f in findings:
        if f.kind == kind:
            return f.why
    for f in findings:
        if f.kind == UNREADABLE:
            return f"it cannot be read: {f.why}"
    return None


def readings(findings: Sequence[Finding]) -> Tuple[Optional[str], Optional[str]]:
    """`B1652`. `(why it destroys, why it reaches the network)` from one reading."""
    return reason(findings, DESTROYS), reason(findings, REACHES)


def writes_of(findings: Sequence[Finding]) -> Tuple[Finding, ...]:
    """`B1669`. What the command writes over and where it goes, in the order
    read — for the run to look at (`src/run_files.command_replaces`). Empty
    when it writes over nothing it names."""
    if not any(f.kind == WRITES for f in findings):
        return ()
    return tuple(f for f in findings if f.kind in (WRITES, CHDIR))


def shell_destroys(command: str) -> Optional[str]:
    """Why this shell command carries `destructive`, or `None`."""
    return reason(read_shell(command))


def python_destroys(code: str) -> Optional[str]:
    """Why this Python carries `destructive`, or `None`."""
    return reason(python_findings(code))


def shell_reaches(command: str) -> Optional[str]:
    """`B1652`. Why this shell command carries `network_egress`, or `None`."""
    return reason(read_shell(command), REACHES)


def python_reaches(code: str) -> Optional[str]:
    """`B1652`. Why this Python carries `network_egress`, or `None`."""
    return reason(python_findings(code), REACHES)
