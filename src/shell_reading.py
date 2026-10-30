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
  * `B1679`: a redirect after a compound command — `done > f`, `fi > f`,
    `} > f`, `( … ) > f`, `esac > f` — which writes what it printed, and does
    not only empty the file as a redirect with no command does (`: > log`);
  * `B1680`: a program told to write over a named output — `curl -o`/`-O`,
    `wget -O`, `sort -o`, `unzip -o`, `tar -x`/`-c`, `ffmpeg -y` — as the
    block above `_scan` reads each from its manual (not `sed -i`: an in-place
    edit is a plain write, `D-2026-10-29-03` §1); and (`B1682`) `pandoc -o`,
    ImageMagick's output, `openssl -out`, `cwebp -o`, `7z x -y`, `yt-dlp
    --force-overwrites`, `rsync` and `wget -r`, as the block below it reads
    them;
  * `B1683`: a compressor that takes away the file it packs or unpacks
    (`gzip notes.md`, `gunzip`, `bzip2`, `xz`, `zstd --rm`…), and `zip -m`,
    `tar --remove-files`, `7z a -sdel` — a `writes` finding marked `removes`,
    asked the same question: was the file there before the run began;
  * `B1688`–`B1690`: `scp` as `cp` (onto another machine, the far side);
    `jpegoptim --dest -o`, `oxipng --out`/`--dir` and `mogrify -path`/
    `-format` onto a different file (in place, each is an edit, as `sed -i`
    is); LibreOffice's `--convert-to` and `heif-convert`, as the block
    below `_FFMPEG_INFO` reads them;
  * `B1693`: the numbered names ImageMagick (`out-0.png`…) and `heif-dec`
    (`out-1.jpg`…) give each image when the input holds several — a
    `numbered` finding: the folder, and the shape of those names in it;

and (`B1692`) **the links it makes** — `ln`, `ln -s`, `link`, `cp -l`/`-s`
— a `links` finding, so a write onto a link's name after it in the same
command is looked at where the link points (`B1697`: `cp -l`/`-s` onto a
name that is there writes nothing over it unless `-f`, `--remove-destination`
or `-i` — GNU `cp` refuses, *File exists*); (`B1696`) **the symbolic links it
copies as links** — `cp -a`, `-P`, `-d`, `-r`, `rsync -l`, `-a` — a `links`
finding marked `copied`, whose text the run reads from the source;
(`B1698`) **the names a move puts what it moves at** — `mv`, `mv -n`,
`git mv`, each the source's own file or link (`moved`) — and **what an
archive or git puts in a folder**, any name of which may be a link
(`unpacked`: `tar -x`, `unzip`, `7z x`, `git checkout`, `pull`, `clone`…); and
(`B1695`) a test of the first of `heif-convert`'s numbered names, which
speaks for them all; and **where the command goes**
— a `chdir` finding — for each `cd`, `pushd`,
`env -C`, `sudo -D`, a Python `os.chdir` or a subprocess `cwd=`, so a relative
target is looked for wherever the command could be when it writes. A target or
a `cd` filled in when it runs (`> "$out"`, `cd "$dir"`) is marked not
`known` — except (`B1681`) one that starts with a single variable and has
nothing else filled in (`cd "$PANTHEON_PROJECTS"/'w'`), which is kept with the
variable named (`var`) for the run, which knows what its shell is given, to
fill in — and one inside a command run on another machine or in a container
(`ssh host '…'`, `docker exec`) is marked `far`: the run cannot know whether
either was there, so either is destructive — the cautious reading the ruling
names. `B1682`: a write the command makes only when nothing is at its path —
`[ -e f ] || cwebp … -o f`, `[ ! -e f ] && echo x > f` — replaces nothing,
and is not named (`_guard`); nor (`B1690`) the rest of a loop's body after
`[ -e f ] && continue`, or `if [ ! -e f ]; then …`'s branch, written at the
same words (`_Tests`) — File Converter's loop.

Python's own `open(path, "w")` is **not** read: whether a mode string
writes, appends or reads is a property of the running program (a variable, a
`Path.write_text`, a library call), and this reader reads the words of a call,
not the program, so it stays what it was; its `subprocess` commands are read
as any shell command is.
"""

from __future__ import annotations

import ast
import os
import posixpath
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
LINKS = "links"         # `B1692`: it makes a name that writes through to another file


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
    `cp --parents`, which keeps each source's whole path inside it.

    `B1681`. `var` is the variable a `known` path starts with — `path` is
    `$PANTHEON_PROJECTS/w`, as written — whose value the run fills in as its
    shell will (`src/run_files.py`), and `split` that it is unquoted, so a
    value with a space or a glob in it is not one path. `B1680`: a source
    with no name (`("", False)`) is what an archive holds, which the command
    does not name.

    `B1683`. `removes`: what `why` does to a file that was there is take it
    away (a compressor's input, `zip -m`'s), not write over it — the same
    question to the run, said with its own verb.

    `B1690`. `steady`: `path` names the same file each time the shell reads
    it in this command, until something sets a variable in it (`_steady`) —
    so a test of the same words before it (`_Tests`) is a test of this
    file, whether or not the run can fill it in.

    `B1692`. A `links` finding is a name a link makes — `path` the link's
    name, or the folder it is made in (`into`, as a copy's), and `sources`
    what it points at — so a write onto that name after it, in the same
    command, is looked at where it lands. `beside`: what it points at is
    named from the link's own folder, as a symbolic link's text is (`ln -s
    ../a d/l` points at `a`), not from where the command runs.

    `B1693`. `numbered`: a `writes` finding for the names a program gives
    each image when it writes several — `path` the folder, and `numbered`
    the shape of their names there, as a regular expression a name matches
    whole (`out-[0-9]+\\.png`). How many it writes is the input's to decide,
    so a name of that shape that was there may be written over, or may
    not.

    `B1695`. `first`: the first of those names, as the command spells it
    (`converted/${f%.*}-1.jpg`), where the program numbers them from a
    known start, one after another — `heif-convert`'s from 1 — so it is
    written whenever any of them is; and `tested`, that a test before the
    write skips it where that name is there (`[ -e … ] && continue`,
    `_unguard`). A numbered name that was there is then written over only
    where the first of its own is not.

    `B1696`. `copied`: a `links` finding for a copy that keeps a symbolic
    link as one, with the same text — so a write onto the copy lands where
    that text points from the copy's own folder. Which links it keeps, as
    the copy's options say (`_cp_keeps_links`): `named`, each source that
    is one (`cp -P`, `-d`, `rsync -l`); `deep`, those and every one inside
    a folder it copies (`cp -a`, `cp -r`, `rsync -a`); `inside`, only those
    inside, the sources followed (`cp -rH`). Empty: a link the command
    makes itself (`ln`, `cp -l`).

    `B1698`. And two more: `moved`, the names `mv` (or `git mv`) puts what
    it moves at — each the source's own thing, the person's file itself
    or a symbolic link with the same text, a folder with all it holds — and
    `unpacked`, what an archive (`tar -x`, `unzip`, `7z x`) or git (`git
    checkout`, `pull`, `clone`…) puts in a folder: names the command does
    not hold (its `sources`, as an archive's writes are), any of which may
    be a symbolic link pointing anywhere, which nothing here opens the
    archive to read."""
    kind: str
    why: str
    path: str = ""
    known: bool = True
    far: bool = False
    sources: Tuple[Tuple[str, bool], ...] = ()
    into: str = ""
    parents: bool = False
    var: str = ""
    split: bool = False
    removes: bool = False
    steady: bool = False
    beside: bool = False
    numbered: str = ""
    first: str = ""
    tested: bool = False
    copied: str = ""


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
    fills: int = 0           # `B1681`: how many expansions it holds
    var: str = ""            # `B1681`: the variable it starts with (`$X…`, `${X}…`), if any
    var_split: bool = False  # `B1681`: that variable is unquoted, so its value is split and globbed
    # `B1690`: something in it can be another value the next time it is read
    # in the same command — a command's output, arithmetic, `$RANDOM`, `$?`, a
    # positional parameter, or an expansion left unquoted, which is split and
    # globbed — or (`_unknown`) a name the program fills in, not the shell.
    unsteady: bool = False

    def fill(self) -> None:
        """An expansion the shell fills in when it runs."""
        self.expanded = True
        self.fills += 1

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
    # `B1679`: it follows a group's `)` or is an `esac`, so its redirections
    # are the compound command's (`(…) > x`, `case … esac > x`).
    compound: bool = False
    # `B1682`: the operator before it (`&&`, `||`, `;`, …; "" first), so a
    # test it follows is known to decide whether it runs (`_guard`).
    after: str = ""
    # `B1690`: how many subshells `( … )` it is inside, so a `continue` is
    # known to be in the same shell as the loop it ends (`_Tests`).
    depth: int = 0


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

    def __init__(self, depth: int, findings: List[Finding], far: bool = False,
                 apart: bool = False):
        if depth > MAX_DEPTH:
            raise _Unreadable("it nests commands deeper than this reader follows")
        self.depth = depth
        self.findings = findings
        # `B1669`: reading a command another machine or a container runs.
        self.far = far
        # `B1690`: reading a command another shell runs (`sh -c '…'`), which
        # has only the variables the outer one exported: `$o` there need not
        # be the outer `$o`, so a test outside does not speak for it.
        self.apart = apart
        # `B1690`: the `for` loops' names that hold a name in the folder, here.
        self.bare: frozenset = frozenset()

    def sub(self, text: str, apart: bool = False) -> None:
        """A command inside this one: a substitution (`$(…)`), which shares
        this shell's variables, or (`apart`) a string another shell runs."""
        read_shell(text, depth=self.depth + 1, findings=self.findings, far=self.far,
                   apart=self.apart or apart)

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

    def _dollar(self, s: str, i: int, word: _Word, out: List[str], quoted: bool = False) -> int:
        """`s[i]` is `$`: an expansion, whose commands are read. `quoted`: it
        is inside double quotes."""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if nxt == "'":
            # `$'…'` is decoded as it is read, and its escapes can spell any
            # word (`$'\x72\x6d'` is `rm`): a word that uses them is not read.
            j = i + 2
            while j < len(s) and s[j] != "'":
                if s[j] == "\\":
                    word.fill()
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
                word.fill()
                word.unsteady = True            # `B1690`: `$((i++))`
                self.substitutions_in(s[i + 3:end])
                out.append(s[i:end + 2])
                return end + 2
        if nxt == "(":
            end = self._closing(s, i + 2, "(", ")")
            self.sub(s[i + 2:end])
            word.fill()
            word.unsteady = True                # `B1690`: a command's output
            out.append(s[i:end + 1])
            return end + 1
        if nxt == "{":
            end = self._closing(s, i + 2, "{", "}")
            inner = s[i + 2:end]
            self.substitutions_in(inner)
            if _NAME_RE.fullmatch(inner):
                self._leads(word, out, inner, quoted)
            word.fill()
            # `B1690`: `${x%.*}` is the same each time; `${!x}`, `${#}`,
            # `${RANDOM}`, `${1}` and one holding a command are not.
            name = _NAME_RE.match(inner)
            if (not name or name.group(0) in _SHIFTING or "$" in inner or "`" in inner):
                word.unsteady = True
            out.append(s[i:end + 1])
            return end + 1
        m = _NAME_RE.match(s, i + 1)
        if m:
            self._leads(word, out, m.group(0), quoted)
            word.fill()
            if m.group(0) in _SHIFTING:
                word.unsteady = True            # `B1690`: `$RANDOM`, `$_`
            out.append(s[i:m.end()])
            return m.end()
        if nxt and (nxt.isdigit() or nxt in "@*#?$!-"):
            word.fill()
            word.unsteady = True                # `B1690`: `$?`, `$1` after a `shift`…
            out.append(s[i:i + 2])
            return i + 2
        out.append("$")             # a dollar sign and nothing after it
        return i + 1

    @staticmethod
    def _leads(word: _Word, out: List[str], name: str, quoted: bool) -> None:
        """`B1681`. `$name` is the first thing in `word`: a path that starts
        with it (`"$PANTHEON_PROJECTS"/w`) is spelled against a value the run
        may know — and, unquoted, split and globbed as the shell does."""
        if not word.fills and not "".join(out):
            word.var, word.var_split = name, not quoted

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
                fills = word.fills
                i = self._dollar(s, i, word, out)
                # `B1690`: unquoted, its value is split and globbed.
                word.unsteady = word.unsteady or word.fills > fills
                unquoted.append(" ")
                continue
            if ch == "`":
                end = self._bq_close(s, i + 1)
                self.sub(s[i + 1:end].replace("\\`", "`"))
                word.fill()
                word.unsteady = True
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
                i = self._dollar(s, i, word, out, quoted=True)
                continue
            if ch == "`":
                end = self._bq_close(s, i + 1)
                self.sub(s[i + 1:end].replace("\\`", "`"))
                word.fill()
                word.unsteady = True
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
                word = _Word(text=s[i:end + 1], expanded=True, unsteady=True)
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
#: `B1679`. The words that end a compound command: a redirection after one is
#: the compound command's (`done > list.txt`), not a command of its own.
_CLOSERS = ("}", "fi", "done")


def _simple_commands(tokens: Sequence[tuple]) -> List[_Simple]:
    """Simple commands, each with its own words and redirections. A `case`
    arm's pattern (`docx|odt)`) and a `[[ … ]]` test are not commands."""
    raw: List[_Simple] = []
    cur = _Simple()
    in_test = False
    groups = 0      # `B1679`: subshells `( … )` open here, not a case pattern's `)`
    for tok in tokens:
        if tok[0] == "op":
            if in_test and tok[1] in ("&&", "||", "(", ")"):
                continue
            closed = False
            if tok[1] == "(" and not cur.redirects and all(w.keyword(*_SKIP) for w in cur.words):
                groups += 1     # not `f()`, nor a pattern's `(a)` after `case x in`
            elif tok[1] == ")" and groups:
                groups -= 1
                closed = True
            cur.ended_by = tok[1]
            raw.append(cur)
            cur = _Simple(compound=closed, after=tok[1], depth=groups)
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
            if simple.redirects:
                # `B1679`: `esac > x` — what the whole `case` printed.
                out.append(_Simple(redirects=simple.redirects, ended_by=simple.ended_by,
                                   compound=True, depth=simple.depth))
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


def _spelling(word: _Word) -> Tuple[bool, str, bool]:
    """`B1681`. `(known, var, split)` for a path a command names: spelled
    out (`_spelled`), or spelled against the one variable it starts with and
    nothing else filled in (`cd "$PANTHEON_PROJECTS"/w`) — which the run, that
    knows the variable's value, can look at; anything else is not known."""
    if _spelled(word):
        return True, "", False
    if (word.var and word.fills == 1 and not word.globbed and not word.braced
            and "{}" not in word.text):
        return True, word.var, word.var_split
    return False, "", False


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
#: (`B1697`: and `cp`'s `--no-preserve` and `--sparse`, which take one too.
#: `B1698`: and `mv`'s, whose words `_copy_words` reads as `cp`'s — it is
#: read by `_Judge._mv`, before `cp` and `install` are.)
_COPY_VALUES = {"cp": ("tS", {"--target-directory", "--suffix", "--no-preserve", "--sparse"}),
                "install": ("gmoSt", {"--group", "--mode", "--owner", "--suffix",
                                       "--target-directory", "--strip-program"}),
                "mv": ("tS", {"--target-directory", "--suffix"})}
#: `B1697`. Every long option `cp` and `install` take (coreutils 9.4's
#: `--help`), so one written short of its name — `--forc`, `--remove-d`,
#: `--no-deref` — is read as `getopt_long` reads it: the one it begins.
#: (`B1698`: and `mv`'s.)
_COPY_LONG = {
    "cp": ("--archive", "--attributes-only", "--backup", "--context", "--copy-contents", "--debug",
           "--dereference", "--force", "--help", "--interactive", "--link", "--no-clobber",
           "--no-dereference", "--no-preserve", "--no-target-directory", "--one-file-system",
           "--parents", "--preserve", "--recursive", "--reflink", "--remove-destination",
           "--sparse", "--strip-trailing-slashes", "--suffix", "--symbolic-link",
           "--target-directory", "--update", "--verbose", "--version"),
    "install": ("--backup", "--compare", "--context", "--debug", "--directory", "--group",
                "--help", "--mode", "--no-target-directory", "--owner", "--preserve-context",
                "--preserve-timestamps", "--strip", "--strip-program", "--suffix",
                "--target-directory", "--verbose", "--version"),
    "mv": ("--backup", "--context", "--debug", "--force", "--help", "--interactive",
           "--no-clobber", "--no-copy", "--no-target-directory", "--strip-trailing-slashes",
           "--suffix", "--target-directory", "--update", "--verbose", "--version"),
}
#: `B1697`. What makes `cp -l`/`-s` replace a name that is there: without
#: one, GNU `cp` refuses — measured, coreutils 9.4: *cannot create hard link
#: 'b' to 'a': File exists* — and `-i` replaces it on a yes (`copy.c`'s
#: `create_hard_link`/`force_symlinkat`, told to replace by either).
_LINK_REPLACES = frozenset({"-f", "--force", "--remove-destination", "-i", "--interactive"})


def _long_name(key: str, names: Sequence[str]) -> str:
    """`B1697`. A long option as `getopt_long` reads it: itself, or the one
    option it is the beginning of (`--forc` → `--force`); an ambiguous one
    (`--re`), which the program refuses, as written."""
    if key in names:
        return key
    begun = [n for n in names if n.startswith(key)]
    return begun[0] if len(begun) == 1 else key


def _copy_words(name: str, args: Sequence[_Word]):
    """`B1669`. `cp`'s, `install`'s or (`B1698`) `mv`'s words, read as GNU
    reads them — options anywhere before `--`, a short option's value joined
    to it or the next word, a long one's after `=` or the next, and
    (`B1697`) one written short of its name as the one it begins: `(flags,
    said, operands, folder)` — the options as a set and (`B1696`) in order,
    the operands, and `-t`'s folder — or `None` where it refuses, an option
    missing its value (nothing done)."""
    shorts, longs = _COPY_VALUES[name]
    flags: set = set()
    said: List[str] = []
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
            key = _long_name(key, _COPY_LONG[name])     # `B1697`: `--forc` is `--force`
            flags.add(key)
            said.append(key)
            if key in longs and not eq:
                if i >= len(args):
                    return None
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
            said.append("-" + letter)
            if letter in shorts:
                if j + 1 < len(t):
                    value_word = replace(w, text=t[j + 1:])
                elif i < len(args):
                    value_word, i = args[i], i + 1
                else:
                    return None
                if letter == "t":
                    folder = value_word
                break
    return flags, said, operands, folder


def _cp_keeps_links(said: Sequence[str], hard: bool) -> str:
    """`B1696`. Which symbolic links `cp` copies as links, from its options
    in order (`Finding.copied`). Measured, coreutils 9.4: `-P`, `-d`, `-a`
    and `-r` copy one as a link, plain `cp` and `--preserve=links` the file
    it points at; the last of `-L`, `-P`, `-H`, `-d`, `-a` wins (`-aL`
    follows, `-La` keeps); `-rH` follows the sources and keeps those inside.
    With none, a recursive copy keeps them — unless it makes hard links
    (`cp.c`: `x.recursive && ! x.hard_link`), where it follows."""
    recursive = any(o in ("-R", "-r", "--recursive", "-a", "--archive") for o in said)
    deref = ""
    for o in said:
        if o in ("-L", "--dereference"):
            deref = "always"
        elif o in ("-P", "--no-dereference", "-d", "-a", "--archive"):
            deref = "never"
        elif o == "-H":
            deref = "named"
    if not deref:
        deref = "never" if recursive and not hard else "always"
    if deref == "never":
        return "deep" if recursive else "named"
    return "inside" if deref == "named" and recursive else ""

# ── `B1680` · programs that write over an output they are told to ───────────
#
# `curl -o notes.md …`, `sort -o notes.md …`, `wget -O`, `unzip -o`, `tar -x`
# and `ffmpeg -y` write over a file the command names (or an archive holds)
# whether or not it was there, and were `execute_code` alone while a `>` onto
# the same file was read (`B1669`). Each program's own words, as its manual
# gives them, name what it writes from the start:
#
#   * `curl`: `-o`/`--output` (`-o -` is the screen), and `-O`/`--remote-name`
#     (`--remote-name-all`) the last part of each address's path, under
#     `--output-dir`; and the files it keeps beside a download — `-D`
#     (`--dump-header`), `-c` (`--cookie-jar`), `--trace`, `--trace-ascii`,
#     `--stderr`, `--libcurl`, `--etag-save`. Not when it resumes (`-C`, which
#     appends) or is told not to clobber (`--no-clobber`, which picks another
#     name), for the download;
#   * `wget`: `-O`/`--output-document` (it truncates the file first: the
#     manual's own *"analogous to shell redirection"*) unless `-nc`, `-o`/
#     `--output-file` (its log; `-a` appends) and `--save-cookies`; with
#     `-N` (`--timestamping`), the last part of each address's path. Without
#     them a second download is saved beside the first (`name.1`), and a
#     recursive one (`-r`, `-m`, `-p`) writes a tree of names the command
#     does not hold — read since `B1682`, below;
#   * `sort`: `-o`/`--output` (`sort -o f f` too: it rewrites the file whole);
#   * `unzip -o` (never asking) and `tar -x` (whose default is to replace),
#     into `-d`/`-C` or the folder they run in: each member the command names
#     in it, or — named nowhere in the command — whatever the archive holds,
#     which the run cannot know, in a folder that was there. Not `unzip`
#     without `-o` (it asks, and with no one to answer it keeps the file),
#     `-n`, or a listing, test or print (`-l`, `-t`, `-p`, `-c`, `-v`, `-Z`);
#     not `tar -k`, `--skip-old-files`, `-O` (`--to-stdout`) or
#     `--to-command`. And `tar -c`'s archive (`-f`), which it writes whole;
#   * `ffmpeg -y`: each output file (a word that is not an option's value or
#     an `-i` input); without `-y` it asks, and with `-nostdin` or no one to
#     answer, keeps the file.
#
# `sed -i` is not here: an in-place edit is a plain write
# (`D-2026-10-29-03` §1, *"edits stay writes"* — `edit_file` and a patch's
# *Update File*), and so is `sed -i`'s. An option this does not know is read
# as taking a value (most of these programs' options do), so a word it
# swallows is never called an output it is not; a value it calls an output
# only asks more.

#: `curl`'s short options that take a value.
_CURL_SHORT = "AbcCdDeEFHKmoPQrtTuUwxXyYz"
_CURL_LONG = {
    "--output", "--output-dir", "--dump-header", "--cookie-jar", "--trace", "--trace-ascii",
    "--stderr", "--libcurl", "--etag-save", "--etag-compare", "--continue-at", "--url",
    "--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode", "--json",
    "--form", "--form-string", "--header", "--proxy-header", "--user-agent", "--referer",
    "--cookie", "--user", "--proxy-user", "--request", "--request-target", "--max-time",
    "--connect-timeout", "--retry", "--retry-delay", "--retry-max-time", "--write-out",
    "--upload-file", "--cacert", "--capath", "--cert", "--cert-type", "--key", "--key-type",
    "--config", "--resolve", "--connect-to", "--interface", "--limit-rate", "--max-filesize",
    "--range", "--proxy", "--preproxy", "--socks4", "--socks4a", "--socks5",
    "--socks5-hostname", "--noproxy", "--oauth2-bearer", "--pinnedpubkey", "--time-cond",
    "--local-port", "--dns-servers", "--doh-url", "--unix-socket", "--abstract-unix-socket",
    "--mail-from", "--mail-rcpt", "--mail-auth", "--ftp-port", "--quote", "--expect100-timeout",
    "--hsts", "--alt-svc", "--aws-sigv4", "--variable", "--url-query", "--speed-limit",
    "--speed-time", "--max-redirs", "--create-file-mode", "--parallel-max", "--proto",
    "--proto-redir", "--proto-default", "--netrc-file", "--tls-max", "--ciphers", "--curves",
    "--keepalive-time", "--happy-eyeballs-timeout-ms", "--rate", "--sasl-authzid",
    "--login-options", "--service-name", "--delegation", "--krb", "--engine",
}
#: The files `curl` keeps beside a download, which it writes from the start.
_CURL_SIDE_FILES = {"-D": "curl -D", "--dump-header": "curl --dump-header",
                    "-c": "curl -c", "--cookie-jar": "curl --cookie-jar",
                    "--trace": "curl --trace", "--trace-ascii": "curl --trace-ascii",
                    "--stderr": "curl --stderr", "--libcurl": "curl --libcurl",
                    "--etag-save": "curl --etag-save"}
#: `wget`'s short options that take a value (`-n` takes `c`, `d`, `H`, `v`, `p`).
_WGET_SHORT = "aABDeiIlnoOPQRtTUwX"
_WGET_LONG = {
    "--output-document", "--output-file", "--append-output", "--directory-prefix",
    "--input-file", "--execute", "--user-agent", "--tries", "--timeout", "--wait", "--level",
    "--accept", "--reject", "--domains", "--exclude-domains", "--header", "--post-data",
    "--post-file", "--body-data", "--body-file", "--method", "--user", "--password",
    "--http-user", "--http-password", "--load-cookies", "--save-cookies", "--base", "--config",
    "--referer", "--quota", "--waitretry", "--dns-timeout", "--connect-timeout",
    "--read-timeout", "--limit-rate", "--bind-address", "--ca-certificate", "--certificate",
    "--private-key", "--restrict-file-names", "--cut-dirs", "--default-page", "--progress",
    "--accept-regex", "--reject-regex", "--include-directories", "--exclude-directories",
    "--warc-file", "--use-askpass", "--rejected-log", "--local-encoding", "--remote-encoding",
}
_WGET_RECURSIVE = {"-r", "--recursive", "-m", "--mirror", "-p", "--page-requisites", "-x",
                   "--force-directories"}
_SORT_SHORT = "kotST"
_SORT_LONG = {"--key", "--output", "--field-separator", "--buffer-size",
              "--temporary-directory", "--parallel", "--batch-size", "--compress-program",
              "--files0-from", "--random-source", "--sort"}
#: `unzip`'s options that take a value (`-x` takes the words after it), and
#: those that extract nothing.
_UNZIP_SHORT = "dPIO"
_UNZIP_READS = set("clptvzZT")
#: GNU `tar`'s short options that take a value, and long ones.
_TAR_SHORT = "bCfFgHIKLNTVX"
_TAR_LONG = {
    "--file", "--directory", "--files-from", "--exclude-from", "--blocking-factor", "--format",
    "--starting-file", "--tape-length", "--newer", "--after-date", "--newer-mtime", "--label",
    "--listed-incremental", "--info-script", "--new-volume-script", "--use-compress-program",
    "--exclude", "--transform", "--xform", "--strip-components", "--owner", "--group",
    "--mode", "--mtime", "--to-command", "--record-size", "--volno-file", "--rmt-command",
    "--rsh-command", "--index-file", "--level", "--suffix", "--quoting-style", "--warning",
    "--exclude-tag", "--exclude-tag-all", "--exclude-tag-under", "--owner-map", "--group-map",
    "--pax-option", "--sort",
}
#: `ffmpeg`'s options that take no value; any other option takes one.
_FFMPEG_FLAGS = {
    "-y", "-n", "-nostdin", "-stdin", "-hide_banner", "-an", "-vn", "-sn", "-dn", "-re",
    "-shortest", "-copyts", "-start_at_zero", "-nostats", "-stats", "-benchmark",
    "-benchmark_all", "-dump", "-hex", "-xerror", "-ignore_unknown", "-copy_unknown",
    "-accurate_seek", "-noaccurate_seek", "-autorotate", "-noautorotate", "-autoscale",
    "-noautoscale", "-debug_ts", "-report", "-bitexact", "-fix_sub_duration", "-psnr",
    "-vstats", "-qphist", "-copyinkf", "-sameq", "-same_quant", "-deinterlace", "-intra",
}
#: Each program above, and the reader that reads it — and (`B1682`, `B1683`)
#: each below.
_OUTPUT_READERS = {"curl": "_curl", "wget": "_wget", "wget2": "_wget", "sort": "_sort",
                   "unzip": "_unzip", "tar": "_tar", "gtar": "_tar", "bsdtar": "_tar",
                   "ffmpeg": "_ffmpeg",
                   "pandoc": "_pandoc", "convert": "_magick", "magick": "_magick", "gm": "_magick",
                   "composite": "_magick", "montage": "_magick", "openssl": "_openssl",
                   "cwebp": "_webp", "dwebp": "_webp", "gif2webp": "_webp", "img2webp": "_webp",
                   "webpmux": "_webp", "7z": "_sevenzip", "7za": "_sevenzip", "7zr": "_sevenzip",
                   "7zz": "_sevenzip", "yt-dlp": "_ytdlp", "zip": "_zip"}

# ── `B1682` · more programs that write over an output they are told to ──────
#
# `B1680` read the first ones; these are the rest the row names, each from its
# own manual, by the same rules (`_scan`, `_file_value`, `_under`):
#
#   * `pandoc`: `-o`/`--output` (`-` is the screen) and `--log`, written
#     whole; `--extract-media=DIR`, whose files are named by the document (or
#     by a hash of each), not the command — into a folder that was there,
#     unknowable, as an archive's are;
#   * ImageMagick — `convert`, `magick` (alone or `magick convert`),
#     `composite`, `montage`, and GraphicsMagick's `gm convert`/`composite`/
#     `montage`: the last word is the output, always (a `png:` in front names
#     its format; `-`, `null:`, `info:` and the like are not files; a
#     `%d` is a frame number, filled in when it runs), and each `-write`. Not
#     `mogrify`, which edits in place (`D-2026-10-29-03` §1), nor `identify`,
#     `compare`, `display` or a `-list`/`-version`;
#   * `openssl`: `-out` and `-keyout`, in any subcommand (`-out=f`, `--out`
#     too: its option reader takes both);
#   * the WebP tools — `cwebp`, `dwebp`, `gif2webp`, `img2webp`, `webpmux`:
#     `-o`;
#   * 7-Zip (`7z`, `7za`, `7zr`, `7zz`): `x` and `e` told to answer yes
#     (`-y`) or to overwrite (`-aoa`), into `-o<folder>` or the one it runs
#     in, as `unzip -o` is read — not `-aos`, `-aou`, `-aot` or `-so`;
#   * `yt-dlp --force-overwrites` (without it the download is never written
#     over): each `-o` template under `-P`, one filled in from the video
#     (`%(title)s`) or none at all unknowable;
#   * `rsync` onto a path on this machine — the destination, each source's
#     name in it, or with a trailing `/` what is in the source, which the
#     command does not name — not with `--ignore-existing`, `--backup`,
#     `--append`, `--dry-run` or `--list-only`; onto another machine, on the
#     far side;
#   * `wget -r` (`-m`, `-p`), which writes a tree of names the command does
#     not hold into a folder named for the site (`-nH`: the folder itself) —
#     not with `-nc`, nor `-nd` without `-N`, which keep each old copy.
#
# `B1683` · and the programs that take away the file they pack or unpack.
# `gzip notes.md` leaves `notes.md.gz` and no `notes.md`: the person's file
# is gone from where it was, as `mv`'s replaced name is (`B1622`). The
# content is recoverable — `gunzip` gives it back — so this is the cautious
# reading, built under `D-2026-10-29-02` §1's principle and the deletion rows
# (`B1622`, `B1668`); the owner may rule that a reversible compression is not
# a deletion, and then only the `removes` findings below go. So a compressor
# packing or unpacking a file that was there before the run begins removes
# it — `gzip`, `pigz`, `bzip2`, `pbzip2`, `xz`, `lzma`, `lzip`, `plzip` and
# `compress` by default, `zstd` and `lz4` with `--rm`, `brotli` with `-j` —
# unless told to keep it (`-k`, `--keep`) or to write to the screen (`-c`),
# or only testing or listing (`-t`, `-l`); with `-r`, what is in a folder it
# is handed. And its output, when told to write over one that is there
# (`-f`): the packed name (`notes.md.gz`), or the unpacked one (`gunzip -f
# notes.md.gz` writes `notes.md`), or `-o`. Archivers that remove what they
# add by an option are the same: `zip -m`, `tar --remove-files`, `7z a -sdel`.

#: `pandoc`'s options that take a value.
_PANDOC_SHORT = "frtwodMVHBAcLFDT"
_PANDOC_LONG = {
    "--from", "--read", "--to", "--write", "--output", "--data-dir", "--metadata",
    "--metadata-file", "--defaults", "--variable", "--variable-json", "--template",
    "--include-in-header", "--include-before-body", "--include-after-body", "--css",
    "--lua-filter", "--filter", "--print-default-template", "--print-default-data-file",
    "--title-prefix", "--resource-path", "--request-header", "--extract-media", "--log",
    "--reference-doc", "--bibliography", "--csl", "--citation-abbreviations", "--pdf-engine",
    "--pdf-engine-opt", "--shift-heading-level-by", "--base-header-level", "--tab-stop",
    "--track-changes", "--wrap", "--columns", "--toc-depth", "--highlight-style",
    "--syntax-definition", "--eol", "--dpi", "--id-prefix", "--number-offset",
    "--top-level-division", "--email-obfuscation", "--slide-level", "--epub-cover-image",
    "--epub-metadata", "--epub-embed-font", "--epub-subdirectory", "--split-level",
    "--epub-chapter-level", "--chunk-template", "--reference-location", "--markdown-headings",
    "--ipynb-output", "--abbreviations", "--indented-code-classes", "--default-image-extension",
}
#: ImageMagick's tools that write a named output last, and those that do not.
_MAGICK_WRITERS = {"convert", "composite", "montage"}
_MAGICK_OTHERS = {"animate", "compare", "conjure", "display", "identify", "import",
                  "magick-script", "mogrify", "stream"}
_MAGICK_INFO = {"-version", "--version", "-help", "--help", "-usage", "-list",
                "-script"}   # a script run by name: its words are not read
#: `png:out.png`: a format named in front of the file.
_MAGICK_FORMAT = re.compile(r"^[A-Za-z0-9]{2,}:")
#: `yt-dlp`'s options that take a value, and the kinds a template or a path
#: may be given for (`-o "thumbnail:%(title)s.%(ext)s"`, `-P temp:/tmp`).
_YTDLP_SHORT = "aoPfSup2rRNIt"
_YTDLP_LONG = {"--output", "--paths", "--batch-file", "--format", "--format-sort", "--username",
               "--password", "--twofactor", "--limit-rate", "--retries",
               "--concurrent-fragments", "--playlist-items", "--preset-alias"}
_YTDLP_KINDS = re.compile(r"^(subtitle|thumbnail|description|annotation|infojson|link|"
                          r"pl_thumbnail|pl_description|pl_infojson|chapter|pl_video|home|temp):")
#: `rsync`'s options that take a value, and those that keep what is there.
_RSYNC_SHORT = "efTBM@"
_RSYNC_LONG = {
    "--rsh", "--rsync-path", "--filter", "--exclude", "--include", "--exclude-from",
    "--include-from", "--files-from", "--temp-dir", "--backup-dir", "--suffix", "--compare-dest",
    "--copy-dest", "--link-dest", "--log-file", "--log-file-format", "--out-format",
    "--partial-dir", "--chmod", "--chown", "--usermap", "--groupmap", "--timeout",
    "--contimeout", "--port", "--sockopts", "--password-file", "--bwlimit", "--max-size",
    "--min-size", "--max-delete", "--modify-window", "--block-size", "--compress-level",
    "--compress-choice", "--checksum-choice", "--skip-compress", "--info", "--debug",
    "--stop-after", "--stop-at", "--iconv", "--write-batch", "--only-write-batch",
    "--read-batch", "--protocol", "--checksum-seed", "--address", "--remote-option", "--outbuf",
    "--max-alloc", "--copy-as", "--zc", "--zl", "--cc",
}
_RSYNC_KEEPS = {"--ignore-existing", "-b", "--backup", "--backup-dir", "-n", "--dry-run",
                "--list-only", "--append", "--append-verify", "--only-write-batch"}
#: `B1696`. Of those, the ones that write nothing here at all — the others
#: still make the names that were not there, links among them.
_RSYNC_NOTHING = {"-n", "--dry-run", "--list-only", "--only-write-batch"}


def _rsync_keeps_links(said: Sequence[str]) -> str:
    """`B1696`. Which symbolic links `rsync` copies as links, from its
    options in order (`Finding.copied`): with `-l`/`--links` (in `-a`), each
    one it copies — those inside a folder too when it recurses (`-r`, `-a`)
    — until `--no-l`; none with `-L`/`--copy-links`, which copies what each
    points at. (`--safe-links`, `--copy-unsafe-links` and `-k` keep only
    some: read as keeping all, which asks more, never less.)"""
    links = recursive = follows = False
    for o in said:
        if o in ("-a", "--archive"):
            links = recursive = True
        elif o in ("-l", "--links"):
            links = True
        elif o in ("--no-l", "--no-links"):
            links = False
        elif o in ("-r", "--recursive"):
            recursive = True
        elif o in ("--no-r", "--no-recursive"):
            recursive = False
        elif o in ("-L", "--copy-links"):
            follows = True
        elif o in ("--no-L", "--no-copy-links"):
            follows = False
    if follows or not links:
        return ""
    return "deep" if recursive else "named"


#: `zip`'s options that take a value; `-x` and `-i` take the words after them.
_ZIP_VALUES = {"-b", "-n", "-t", "-tt", "-P", "-Z", "-s", "-O", "-lf", "-ds", "--temp-path",
               "--suffixes", "--from-date", "--before-date", "--password",
               "--compression-method", "--split-size", "--output-file", "--logfile-path"}


@dataclass(frozen=True)
class _Packer:
    """`B1683`. A compressor, as its manual gives it."""
    removes: bool                    # it takes away its input unless told to keep it
    suffix: str                      # what packing adds to the name
    unpacks: Tuple[Tuple[str, str], ...]  # (suffix, what takes its place) when unpacking
    bare: str = "skip"               # unpacking a name with none of them: `try` adding one
                                     # (its input then unknown), `out` (`name.out`), or skip it
    shorts: str = ""                 # its short options that take a value
    longs: frozenset = frozenset()   # and long ones
    keep: frozenset = frozenset({"-k", "--keep"})
    rm: frozenset = frozenset()      # what tells one that keeps its input to take it away
    stdout: frozenset = frozenset({"-c", "--stdout", "--to-stdout"})
    inert: frozenset = frozenset({"-t", "--test", "-l", "--list", "-h", "-H", "--help", "-V",
                                  "--version", "-L", "--license"})
    unpack: frozenset = frozenset({"-d", "--decompress", "--uncompress"})
    pack: frozenset = frozenset()
    force: frozenset = frozenset({"-f", "--force"})
    recursive: frozenset = frozenset()
    output: frozenset = frozenset()  # `-o FILE`: the one output
    keeps_with_output: bool = False  # `lzip -o`: its input stays
    suffix_opts: frozenset = frozenset()  # `-S .suf`
    lists: frozenset = frozenset()   # its inputs read from a file (`--files`, `--filelist`)


_GZ_UNPACKS = ((".gz", ""), ("-gz", ""), (".z", ""), ("-z", ""), ("_z", ""), (".Z", ""),
               (".tgz", ".tar"), (".taz", ".tar"), (".zz", ""))
_XZ_UNPACKS = ((".xz", ""), (".txz", ".tar"), (".lzma", ""), (".tlz", ".tar"), (".lz", ""))
_PACKERS = {
    "gzip": _Packer(True, ".gz", _GZ_UNPACKS, bare="try", shorts="AbCIJpS",
                    longs=frozenset({"--suffix", "--blocksize", "--processes", "--comment",
                                     "--alias", "--iterations", "--maxsplits"}),
                    recursive=frozenset({"-r", "--recursive"}),
                    suffix_opts=frozenset({"-S", "--suffix"})),
    "bzip2": _Packer(True, ".bz2", ((".bz2", ""), (".bz", ""), (".tbz2", ".tar"), (".tbz", ".tar")),
                     bare="out", pack=frozenset({"-z", "--compress"}),
                     inert=frozenset({"-t", "--test", "-h", "--help", "-V", "--version", "-L",
                                      "--license"})),
    "xz": _Packer(True, ".xz", _XZ_UNPACKS, shorts="SFCTM",
                  longs=frozenset({"--suffix", "--format", "--check", "--threads", "--memlimit",
                                   "--memory", "--memlimit-compress", "--memlimit-decompress",
                                   "--memlimit-mt", "--block-size", "--block-list",
                                   "--flush-timeout", "--filters"}),
                  pack=frozenset({"-z", "--compress"}), suffix_opts=frozenset({"-S", "--suffix"}),
                  lists=frozenset({"--files", "--files0"})),
    "zstd": _Packer(False, ".zst", ((".zst", ""), (".tzst", ".tar"), (".gz", ""), (".xz", ""),
                                    (".lzma", ""), (".lz4", "")),
                    shorts="oD", longs=frozenset({"--output-dir-flat", "--output-dir-mirror",
                                                  "--filelist"}),
                    rm=frozenset({"--rm"}), pack=frozenset({"-z", "--compress"}),
                    inert=frozenset({"-t", "--test", "-l", "--list", "-h", "-H", "--help", "-V",
                                     "--version", "-b", "--train"}),
                    recursive=frozenset({"-r"}), output=frozenset({"-o"}),
                    lists=frozenset({"--filelist"})),
    "lz4": _Packer(False, ".lz4", ((".lz4", ""),), rm=frozenset({"--rm"}),
                   pack=frozenset({"-z", "--compress"}),
                   inert=frozenset({"-t", "--test", "--list", "-h", "-H", "--help", "-V",
                                    "--version", "-b"})),
    "brotli": _Packer(False, ".br", ((".br", ""),), shorts="oqwSD",
                      longs=frozenset({"--output", "--quality", "--lgwin", "--suffix",
                                       "--large_window", "--dictionary"}),
                      rm=frozenset({"-j", "--rm"}), output=frozenset({"-o", "--output"}),
                      inert=frozenset({"-t", "--test", "-h", "--help", "-V", "--version"}),
                      suffix_opts=frozenset({"-S", "--suffix"})),
    "lzip": _Packer(True, ".lz", ((".lz", ""), (".tlz", ".tar")), bare="out", shorts="bmosS",
                    longs=frozenset({"--member-size", "--match-length", "--output",
                                     "--dictionary-size", "--volume-size"}),
                    output=frozenset({"-o", "--output"}), keeps_with_output=True),
    "compress": _Packer(True, ".Z", ((".Z", ""),), bare="try", shorts="b",
                        recursive=frozenset({"-r"}),
                        inert=frozenset({"-V", "-h", "--help", "--version"})),
}
#: Each program's name, its kind, and whether its name unpacks.
_PACKER_NAMES = {
    "gzip": ("gzip", False), "gunzip": ("gzip", True), "pigz": ("gzip", False),
    "unpigz": ("gzip", True), "bzip2": ("bzip2", False), "bunzip2": ("bzip2", True),
    "pbzip2": ("bzip2", False), "xz": ("xz", False), "unxz": ("xz", True), "lzma": ("xz", False),
    "unlzma": ("xz", True), "zstd": ("zstd", False), "zstdmt": ("zstd", False),
    "unzstd": ("zstd", True), "lz4": ("lz4", False), "unlz4": ("lz4", True),
    "brotli": ("brotli", False), "lzip": ("lzip", False), "plzip": ("lzip", False),
    "compress": ("compress", False), "uncompress": ("compress", True),
}
_OUTPUT_READERS.update({n: "_packer" for n in _PACKER_NAMES})
#: `ffmpeg`'s own information: it writes nothing.
_FFMPEG_INFO = {"-version", "-h", "-help", "--help", "-?", "-L", "-buildconf", "-formats",
                "-muxers", "-demuxers", "-devices", "-codecs", "-decoders", "-encoders",
                "-bsfs", "-protocols", "-filters", "-pix_fmts", "-layouts", "-sample_fmts",
                "-colors", "-sources", "-sinks", "-hwaccels"}

# ── `B1688`–`B1690` · and the programs `B1682` found still unread ───────────
#
# Each from its own manual (and, where the manual is silent, its source), by
# `B1680`'s rules:
#
#   * `scp` (`B1688`): `cp`'s reading of its last word — the target, or each
#     source's name in it — onto this machine; onto another (`host:path`,
#     `scp://`), the far side, as `rsync`'s. A source on another machine is
#     named by its path there, and one whose name it does not hold (`host:`,
#     a `*` the far side expands) is unknowable in a folder that was there;
#   * `jpegoptim` (`B1689`) edits in place — a plain write by
#     `D-2026-10-29-03` §1, like `sed -i` — unless `-d`/`--dest` names a
#     folder, where it writes each file by its name; and there it refuses a
#     file that is there (*"target file already exists"*) unless `-o`
#     (`--overwrite`). So only `--dest` with `-o` writes over one. Image
#     Optimiser's `jpegoptim --dest=optimised …` never does;
#   * `oxipng` (`B1689`) edits in place too, unless `--out FILE` (one output,
#     written whole) or `--dir DIR` (each input by its name; with `-r`, what
#     a folder holds, which the command does not name). Not `--stdout` or a
#     dry run (`-d`, `--dry-run`; `-P`, `--pretend` before 9.0);
#   * `mogrify` (`B1689`; `magick mogrify`, `gm mogrify`) edits in place,
#     unless `-path DIR` (each image by its name in it) or `-format EXT`
#     (`name.EXT` beside the image, or in `-path`): a different file, written
#     whole. A name it expands itself (`'*.jpg'`, `@list`) is unknowable in
#     the folder. An output that is the input itself (`-format jpg a.jpg`,
#     `jpegoptim -d . -o a.jpg`, `oxipng --out a.png a.png`) is the edit;
#   * LibreOffice (`B1690`; `libreoffice`, `soffice`, `lowriter`…) with
#     `--convert-to EXT[:filter]`: each document as `name.EXT` (its name
#     without its last extension) in `--outdir` or the folder it runs in,
#     over whatever is there (*"Overwriting: …"*); `--print-to-file` writes
#     names it chooses into that folder. Not `--cat` (the screen);
#   * `heif-convert` (`B1690`; `heif-dec` since libheif 1.17): `-o`, or its
#     second word, or the input up to its last `.` with `.jpg`; and beside it
#     `--with-xmp`'s `.xmp` and `--with-exif`'s `.exif` — `--with-aux`,
#     `--tiles` and `--sequence` add names the file decides (unknowable).
#
# A name a program makes from an input filled in when it runs is unknowable
# — except one quoted variable (`"$f"`) whose shape the reader knows
# (`_Judge._named_after`): `heif-convert "$f"` writes `${f%.*}.jpg`, exactly
# the shell's spelling of its rule, and in `for f in *` the value is a name
# with no `/` and no leading `.`, so `libreoffice --outdir converted "$f"`
# writes `converted/${f%.*}.pdf` and `jpegoptim -d out -o "$f"` writes
# `out/$f`. A test of those same words before it (`[ -e "converted/${f%.*}.pdf"
# ] && continue`) is then a test of that file (`_Tests`).
#
# `B1693` · and the names a converter gives each of several images. A file
# holding several images is written as `out-1.jpg`, `out-2.jpg` by
# `heif-convert` (`heif_dec.cc`), and as `out-0.png`, `out-1.png`… by
# ImageMagick (measured, 6.9.12: `convert`, `magick`, `montage`,
# `composite`, each `-write`, and `mogrify -format`/`-path`) — the name it is
# given up to its last `.`, a `-` and the image's number, then the rest;
# with no `.`, the name and the number. How many there are is the input's:
# the reader does not open it to count (`D-2026-10-29-02` §1's cautious
# reading, as the owner's rulings have taken it). So besides the one name,
# each is read for the names of that shape in its folder (`_numbered`): a
# file of that shape that was there before the run may be written over —
# it cannot be known, so it is destructive — and where none is, it is a
# plain write. Not for an ImageMagick format that keeps every frame in one
# file (`_MAGICK_ONE_FILE`, measured) unless `+adjoin` says otherwise, and
# not for a `%d` name, which is unknowable already. GraphicsMagick (`gm`) is
# not installed here to measure, so it is read for ImageMagick's shape and
# for a number after the whole name (`out.png.0`) as well — the cautious
# reading. The name made from a `for` loop's name
# (`"converted/${f%.*}.jpg"`, `lexer.bare`) has any name with no `/` before
# its number, so the shape is read as that.

#: `scp`'s options that take a value (OpenSSH).
_SCP_SHORT = "cDFiJlMoPSX"
#: `user@host:path`, `host:path`, `[::1]:path` or `scp://host/path` — a path
#: on another machine; a `:` after a `/` is a file's own name.
_SCP_REMOTE_RE = re.compile(r"^(?:scp://[^/]*(?:/|$)|\[[^\]/]*\]:|[^/:\s]+:)")
#: `jpegoptim`'s options that take a value (`d:hm:nstqvfVpProT:S:bw:`).
_JPEGOPTIM_SHORT = "dmTSw"
_JPEGOPTIM_LONG = {"--dest", "--max", "--threshold", "--size", "--workers", "--files-from",
                   "--max-pixels"}
#: `oxipng`'s options that take a value (`-o` is its level, not its output).
_OXIPNG_SHORT = "oift"
_OXIPNG_LONG = {"--opt", "--dir", "--out", "--strip", "--keep", "--interlace", "--filters",
                "--zc", "--zi", "--ziwi", "--brute-level", "--brute-lines", "--timeout",
                "--max-raw-size", "--threads", "--zw", "--zm", "--zs"}
#: ImageMagick's options, as its table (`magick/option.c`) counts their
#: values: these `-` options take none (any other takes one), these take two,
#: and these `+` options take one (any other takes none). `mogrify`'s inputs
#: are its outputs, so an option read as taking a value it does not take
#: would hide one — the list is the table's, whole.
_MAGICK_FLAGS = frozenset("""
    -adjoin -antialias -append -attenuate -auto-gamma -auto-level -auto-orient -average
    -black-point-compensation -charcoal -clamp -clip -clut -coalesce -combine -compare
    -composite -concurrent -contrast -deconstruct -despeckle -enhance -equalize -fft -flatten
    -flip -flop -hald-clut -help -identify -ift -immutable -magnify -matte -maximum -minimum
    -moments -monitor -monochrome -mosaic -negate -noop -normalize -ping -quiet
    -regard-warnings -render -respect-parentheses -reverse -sans0 -separate -strip
    -subimage-search -synchronize -taint -transform -transpose -transverse -trim -unique
    -unique-colors -verbose""".split())
_MAGICK_TWO = frozenset("""
    -annotate -copy -distort -evaluate -floodfill -limit -morphology -sans2 -set
    -sparse-color -statistic +copy +distort +evaluate +floodfill +morphology +sans2
    +sparse-color +statistic""".split())
_MAGICK_PLUS_VALUED = frozenset("""
    +alpha +blur +resize +adaptive-blur +adaptive-resize +adaptive-sharpen +blue-shift +border
    +canny +cdl +chop +colorize +color-matrix +colors +complex +connected-components
    +contrast-stretch +convolve +crop +cycle +decipher +define +display +duration +edge
    +emboss +encipher +evaluate-sequence +extent +frame +fx +gamma +gaussian +gaussian-blur
    +highlight-color +hough-lines +interpolative-resize +kuwahara +lat +layers +level
    +level-colors +linear-stretch +liquid-rescale +lowlight-color +mean-shift +median +mode
    +modulate +morph +motion-blur +noise +opaque +poly +posterize +print +process +profile
    +radial-blur +raise +random-threshold +recolor +resample +roll +rotate +sample +sans
    +scale +segment +selective-blur +sepia-tone +set +shadow +sharpen +shave +shear
    +sigmoidal-contrast +sketch +smush +solarize +splice +spread +stretch +strokewidth
    +swirl +thumbnail +tint +transparent +transparent-color +treedepth +unsharp +vignette
    +wave +weight +white-threshold +write""".split())
#: The extensions `mogrify -format` looks past (`a.png.gz` → `a.jpg`).
_MAGICK_PACKED = ("gz", "bz2", "z", "svgz", "wmz")
#: LibreOffice by its names (`libreoffice7.6`, `soffice.bin`…).
_OFFICE_RE = re.compile(r"^(libreoffice[\d.]*|soffice(\.bin)?|lowriter|localc|loimpress|"
                        r"lodraw|lomath|lobase|loweb)$")
#: LibreOffice's options that take the next word as their value.
_OFFICE_VALUES = {"--convert-to", "--outdir", "--printer-name", "--pt", "--display",
                  "--convert-images-to"}
#: `heif-convert`'s options that take a value.
_HEIF_SHORT = "qdCo"
_HEIF_LONG = {"--quality", "--decoder", "--output", "--chroma-upsampling",
              "--png-compression-level", "--transparency-composition-mode", "--codec-threads",
              "--tile-threads", "--extract-mime-item"}
_OUTPUT_READERS.update({"scp": "_scp", "jpegoptim": "_jpegoptim", "oxipng": "_oxipng",
                        "mogrify": "_mogrify", "heif-convert": "_heif", "heif-dec": "_heif"})
#: `B1693`. ImageMagick's formats that keep every frame in one file —
#: measured, 6.9.12, a three-frame GIF written as each: no numbered names.
#: Any other (`png`, `jpg`, `bmp`, `tga`, a name it does not know…) may be.
_MAGICK_ONE_FILE = frozenset("""
    apng avif dcx dds exr fits gif hdr heic ico json jxl mat miff mng mpc pam pbm pdf pgm pnm
    ppm ps psd ras rgb sgi sun svg tif tiff txt webp xcf""".split())
#: `B1693`. What the name ends with when a program numbers it: `-3`, `-3.png`
#: — or GraphicsMagick's `.3` — the only names the run need look at
#: (`src/run_files.py`) for any shape `_numbered` reads.
NUMBERED_TAIL = re.compile(r"(?:-[0-9]+(?:\.[^./]*)?|\.[0-9]+)$")
#: `B1693`. A variable in a name, as `_numbered` lets one through: `$f`,
#: `${f}`, or `${f}` with a part taken off its end or start — none of which
#: can put a `/` in a value that holds none.
_TRIMMED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(?:%%?|##?)[^}]*)?\}"
                      r"|\$([A-Za-z_][A-Za-z0-9_]*)")
#: `B1692`. `ln`'s options that take a value.
_LN_SHORT = "St"
_LN_LONG = {"--suffix", "--target-directory"}
#: `B1698`. `git clone`'s options that take a value (git 2.43's `-h`).
_GIT_CLONE_SHORT = "objcu"
_GIT_CLONE_LONG = {"--origin", "--branch", "--upload-pack", "--template", "--config", "--depth",
                   "--shallow-since", "--shallow-exclude", "--reference", "--reference-if-able",
                   "--separate-git-dir", "--jobs", "--filter", "--bundle-uri", "--server-option",
                   "--revision", "--ref-format"}
#: `B1698`. git's commands that write its work tree from what it holds
#: whatever their words, beside those `_Judge._git_puts` reads the words of.
_GIT_PUTS = frozenset({"pull", "merge", "rebase", "cherry-pick", "revert", "am"})


def _scan(words: Sequence[_Word], shorts: str, longs: set,
          old_style: bool = False) -> Tuple[List[Tuple[str, Optional[_Word]]], List[_Word]]:
    """`B1680`. A command's options and operands, read as `getopt_long`
    reads them: `[(option, its value or None)]` and the operands. Options
    anywhere before `--`; a short option's value joined to it or the next
    word (`shorts` take one), a long one's after `=` or the next word
    (`longs` take one), and a long one written short of its name (`--outp`)
    read as the one of `longs` it begins. `old_style` (`tar xzf a.tgz`): a
    first word without a `-` is a cluster whose options take their values
    from the words after it, in order."""
    opts: List[Tuple[str, Optional[_Word]]] = []
    operands: List[_Word] = []
    rest = list(words)
    pending: List[str] = []
    if old_style and rest and not rest[0].text.startswith("-"):
        for letter in rest.pop(0).text:
            if letter in shorts:
                pending.append("-" + letter)
            else:
                opts.append(("-" + letter, None))
    ended = False
    i = 0
    while i < len(rest):
        w = rest[i]
        t = w.text
        i += 1
        if pending:
            opts.append((pending.pop(0), w))
            continue
        if ended or t == "-" or not t.startswith("-"):
            operands.append(w)
            continue
        if t == "--":
            ended = True
            continue
        if t.startswith("--"):
            key, eq, value = t.partition("=")
            if key not in longs:
                key = next((n for n in sorted(longs) if len(key) > 3 and n.startswith(key)), key)
            if key in longs:
                if eq:
                    opts.append((key, replace(w, text=value)))
                elif i < len(rest):
                    opts.append((key, rest[i]))
                    i += 1
                else:
                    opts.append((key, None))
            else:
                opts.append((key, None))
            continue
        for j, letter in enumerate(t[1:], start=1):
            if letter in shorts:
                if j + 1 < len(t):
                    opts.append(("-" + letter, replace(w, text=t[j + 1:])))
                elif i < len(rest):
                    opts.append(("-" + letter, rest[i]))
                    i += 1
                else:
                    opts.append(("-" + letter, None))
                break
            opts.append(("-" + letter, None))
    return opts, operands


def _file_value(word: Optional[_Word]) -> Optional[_Word]:
    """`B1680`. A value that names a file: not the screen (`-`, curl's `%`
    for its error output) or a device."""
    if word is None or word.text in ("-", "%", "") or word.text.startswith("/dev/"):
        return None
    return word


def _unknown(text: str) -> _Word:
    """`B1680`. A path filled in when the command runs — by the program
    (`%d`, `#1`, a name an archive holds), so not the same words twice
    (`B1690`)."""
    return _Word(text=text, expanded=True, fills=2, unsteady=True)


def _steady(word: _Word) -> bool:
    """`B1690`. Whether a path is the same file each time the shell reads
    its words in one command, until a variable in it is set: spelled out,
    or filled in only from variables in quotes (`"converted/${f%.*}.pdf"`) —
    not a command's output, arithmetic, a variable the shell changes by
    itself (`$RANDOM`, `$_`, `$?`, `$1`), anything unquoted (split and
    globbed), a glob, a `{a,b}`, or a name the program fills in."""
    return (bool(word.text) and not (word.unsteady or word.globbed or word.braced)
            and "{}" not in word.text)


def _under(folder: Optional[_Word], name: _Word) -> _Word:
    """`B1680`. `name` inside an output folder (`--output-dir`, `-P`), as the
    program joins them: an absolute name is itself."""
    if folder is None or name.text.startswith("/"):
        return name
    if not _spelling(folder)[0] or not _spelled(name):
        joined = posixpath.join(folder.text, name.text)
        if _steady(folder) and _steady(name):
            # `B1690`: filled in by the shell alone — the same words, the same file.
            return _Word(text=joined, expanded=True, fills=2, quoted=True)
        return _unknown(joined)
    return replace(folder, text=posixpath.join(folder.text, name.text))


def _numbered(word: _Word, bare: frozenset, gm: bool = False,
              also: Sequence[str] = ()) -> Optional[Tuple[_Word, str, Optional[Tuple[str, str]]]]:
    """`B1693`. Where a program that may write several images puts them,
    and the shape of their names there: `(the folder, a regular expression
    a name in it matches whole, how one is spelled)` — `out.png` →
    `out-[0-9]+\\.png` in `.` — or `None` when it cannot be known.
    (`B1695`: how one is spelled is the words before its number and after
    it, `("converted/${f%.*}", ".jpg")`, or `None` where the loop's value
    decides where its last `.` is, which no words spell.)

    The name is cut at its last `.` (none: the whole name), and the number
    goes before it. The folder must be spelled out, or spelled against the
    one variable the path starts with (`_spelling`); a variable in the name
    only a `for` loop's name over names in the folder (`bare`, so its value
    holds no `/`), whole or trimmed (`${f%.*}`), each read as any name. `gm`
    reads GraphicsMagick's other shape too (`out.png.0`); `also` other
    suffixes beside the image's (`heif-convert --with-xmp`'s)."""
    text = word.text
    if not _steady(word) or text.endswith("/"):
        return None
    head, slash, name = text.rpartition("/")
    folder_text = (head or "/") if slash else "."
    if _spelled(word):
        folder: _Word = _Word(text=folder_text)
        pieces: List[Tuple[bool, str]] = [(False, name)]
    else:
        if "$" in folder_text or "`" in folder_text:
            # Only the one variable the path starts with (`B1681`).
            if not (word.var and folder_text.count("$") == 1 and "`" not in folder_text
                    and folder_text.startswith((f"${word.var}", f"${{{word.var}}}"))):
                return None
            folder = _Word(text=folder_text, expanded=True, fills=1, quoted=True,
                           var=word.var, var_split=word.var_split)
        else:
            folder = _Word(text=folder_text)
        if not _spelling(folder)[0]:
            return None
        pieces, at = [], 0
        for m in _TRIMMED.finditer(name):
            if (m.group(1) or m.group(2)) not in bare:
                return None
            pieces += [(False, name[at:m.start()]), (True, m.group(0))]
            at = m.end()
        pieces.append((False, name[at:]))
        if any("$" in t or "`" in t for filled, t in pieces if not filled):
            return None         # `$1`, `${#f}`, `${f/a/b}`: not a trimmed name
    last = pieces[-1][1]
    around: Optional[Tuple[str, str]] = None
    if "." in last:
        root = [(f, t) for f, t in pieces[:-1]] + [(False, last[:last.rfind(".")])]
        ext = last[last.rfind(".") + 1:]
        tail = r"\.(?i:" + "|".join(re.escape(s) for s in (ext, *also)) + ")"
        # The last `.` of the words is the last of the name: it is in its
        # last piece, which nothing fills in.
        around = (text[:text.rfind(".")], text[text.rfind("."):])
    elif len(pieces) == 1:
        root, tail = pieces, ""
        around = (text, "")
    else:
        # Where its last `.` is, the loop's value decides: any number before
        # an ending with no `.` in it.
        root, tail = [(True, "")], r"(?:\.[^./]*)?"
    spelled = "".join("[^/]*" if filled else re.escape(t) for filled, t in root)
    shape = spelled + "-[0-9]+" + tail
    if gm:
        whole = "".join("[^/]*" if filled else re.escape(t) for filled, t in pieces)
        shape = f"(?:{shape}|{whole}\\.[0-9]+)"
        around = None           # two shapes: no one first name
    return folder, shape, around


def _address_name(word: _Word, default: str) -> _Word:
    """`B1680`. The name `curl -O` and `wget -N` save an address as: the last
    part of its path, as written (its query is not part of it), or `default`
    when it has none — `curl_response` (curl 8.10 on; an older curl writes
    nothing), wget's `index.html`. Unknown when the address is filled in when
    it runs or holds `curl`'s own `[1-3]`/`{a,b}` ranges."""
    from urllib.parse import urlsplit
    text = word.text
    if not word.plain() or any(c in text for c in "[]{}"):
        return _unknown(text)
    try:
        path = urlsplit(text if "://" in text else "http://" + text).path
    except ValueError:
        return _unknown(text)
    name = posixpath.basename(path)
    return _Word(text=name if name and name not in (".", "..") else default)


def _site_folder(word: _Word) -> _Word:
    """`B1682`. The folder `wget -r` keeps an address's site in: its host as
    wget writes it — lower case, with a port that is not the scheme's own —
    or unknown when the address is filled in when it runs."""
    from urllib.parse import urlsplit
    text = word.text
    if not word.plain():
        return _unknown(text)
    try:
        parts = urlsplit(text if "://" in text else "http://" + text)
        host, port = parts.hostname or "", parts.port
    except ValueError:
        return _unknown(text)
    if not host or not _word_is_plain_text(host):
        return _unknown(text)
    own = {"http": 80, "https": 443, "ftp": 21}.get(parts.scheme.lower())
    return _Word(text=host + (f":{port}" if port and port != own else ""))


def _in(folder: Optional[_Word], name: _Word) -> _Word:
    """`B1689`. `name` in an output folder a program is given — in the one
    it runs in (none, or `.`), the name as it is."""
    return name if folder is None or folder.text in (".", "./") else _under(folder, name)


def _same_path(a: _Word, b: _Word) -> bool:
    """`B1689`. Whether two paths are one file by their words — the output
    a program is told to write is the input it edits (`mogrify -format jpg
    a.jpg`), which is the edit in place `D-2026-10-29-03` §1 keeps a write."""
    return _steady(a) and _steady(b) and posixpath.normpath(a.text) == posixpath.normpath(b.text)


def _far_name(word: _Word, remote: "re.Pattern") -> Tuple[_Word, bool]:
    """`B1688`. A copy's source, as `scp` and `rsync` name what they copy:
    `(its path, whether it is on another machine)` — `host:dir/a.md` is
    `dir/a.md` there; one with no path (`host:`) or one the far side
    expands (`host:*.md`, `host:$X`) holds no name here (`_Word()`)."""
    m = remote.match(word.text) if word.plain() else None
    if m is None:
        return word, False
    path = word.text[m.end():]
    if not path or any(c in path for c in "*?[{$`"):
        return _Word(), True
    return replace(word, text=path), True


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
        # `B1697`: the program is BusyBox's, whose `cp` reads as GNU's but
        # for a link onto a name that is there (`_copies`).
        self.busybox = False

    def destroys(self, why: str) -> None:
        self.findings.append(Finding(DESTROYS, why))

    def unreadable(self, why: str) -> None:
        self.findings.append(Finding(UNREADABLE, why))

    def reaches(self, why: str) -> None:
        self.findings.append(Finding(REACHES, why))

    def writes(self, why: str, word: _Word, sources: Sequence[_Word] = (), into: str = "",
               parents: bool = False, removes: bool = False) -> None:
        """`B1669`. `why` writes over `word`'s path, if one is there — or
        (`B1683`, `removes`) takes away the file there."""
        known, var, split = _spelling(word)
        self.findings.append(Finding(
            WRITES, why, path=word.text, known=known, far=self.lexer.far,
            sources=tuple((w.text, _spelled(w)) for w in sources), into=into, parents=parents,
            var=var, split=split, removes=removes,
            # `B1690`: in a shell of its own, a variable may not be the outer one.
            steady=_steady(word) and not (self.lexer.apart and word.expanded)))

    def removes(self, why: str, word: _Word, recursive: bool = False) -> None:
        """`B1683`. `why` takes away the file at `word` — and, `recursive`,
        what is in the folder there, which the command does not name."""
        self.writes(why, word, sources=[_Word()] if recursive else (), removes=True)

    def links(self, why: str, word: _Word, targets: Sequence[_Word], into: str = "",
              parents: bool = False, beside: bool = False, copied: str = "") -> None:
        """`B1692`. `why` makes a link at `word` — or (`into`) in the folder
        there, by each target's name — to each of `targets`. (`B1696`:
        `copied`, a copy of each that keeps a symbolic link as one.)"""
        known, var, split = _spelling(word)
        self.findings.append(Finding(
            LINKS, why, path=word.text, known=known, far=self.lexer.far,
            sources=tuple((w.text, _spelled(w)) for w in targets), into=into, parents=parents,
            var=var, split=split, beside=beside, copied=copied))

    def numbered(self, why: str, word: _Word, gm: bool = False, also: Sequence[str] = (),
                 first: Optional[int] = None) -> None:
        """`B1693`. `why` may write several images, each by a number after
        `word`'s name (`_numbered`): the names of that shape in its folder,
        or — when they cannot be spelled — what it writes there, unknown.
        `B1695`: `first`, the number a program that numbers them one after
        another starts from (`heif-convert`'s 1), so a test of that name is
        followed (`Finding.first`)."""
        shape = _numbered(word, self.lexer.bare, gm, also)
        if shape is None:
            # Not a folder (`into`): the names beside `word`, wherever it is.
            self.findings.append(Finding(WRITES, why, path=word.text, known=False,
                                         far=self.lexer.far, numbered=".+"))
            return
        folder, pattern, around = shape
        known, var, split = _spelling(folder)
        # Never `steady`: a test of one name (`[ -e out.png ] ||`) says
        # nothing of the numbered ones beside it — but (`B1695`) a test of
        # the first, the same words read the same way, does of them all.
        spelled = (f"{around[0]}-{first}{around[1]}"
                   if around is not None and first is not None
                   and not (self.lexer.apart and word.expanded) else "")
        self.findings.append(Finding(WRITES, why, path=folder.text, known=known,
                                     far=self.lexer.far, into="folder", var=var, split=split,
                                     numbered=pattern, first=spelled))

    def chdir(self, word: Optional[_Word]) -> None:
        """`B1669`. What follows runs in another folder — `None`: one only
        known when it runs (`cd` alone, `cd -`, `pushd +1`)."""
        known, var, split = _spelling(word) if word is not None else (False, "", False)
        self.findings.append(Finding(CHDIR, "cd", path=word.text if word else "",
                                     known=known, far=self.lexer.far, var=var, split=split))

    def shell_string(self, word: _Word, who: str = "a shell") -> None:
        """A command handed over as one string — `sh -c '…'`, `ssh host '…'`."""
        if word.plain():
            self.lexer.sub(word.text, apart=True)
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
        closes = simple.compound
        while words and words[0].keyword(*_SKIP):
            closes = closes or words[0].keyword(*_CLOSERS)
            words.pop(0)
        if words and words[0].keyword(*_NOT_A_COMMAND):
            return
        while words and words[0].assignment():
            words.pop(0)
        if not words:
            # `B1679`: `done > list.txt`, `fi > x`, `} > x` and `(…) > x` send
            # what the compound command printed into the file — the `writes`
            # above, a replacement only of a file that was there — and do not
            # only empty it, as a redirection with no command does (`: > log`).
            if not closes:
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
                was, self.busybox = self.busybox, True
                try:
                    self.command(args, simple)
                finally:
                    self.busybox = was
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
        reader = _OUTPUT_READERS.get(name) or ("_office" if _OFFICE_RE.match(name) else None)
        if reader:
            # `B1680`: the file its own words tell it to write over.
            getattr(self, reader)(name, args)
            return
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
            self._mv(name, args)            # `B1698`: and the names it moves things to
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
        if name in ("ln", "link"):
            flags = _flags(args)
            if name == "ln" and (_short(flags, "f") or "--force" in flags):
                self.destroys("ln -f replaces whatever had the link's name")
            self._ln(name, args)            # `B1692`: and the name it makes
            return
        if name == "find":
            self._find(args)
            return
        if name == "rsync":
            if any(f.startswith("--del") or f == "--remove-source-files" for f in _flags(args)):
                self.destroys("rsync deletes on the far side")
            self._rsync(name, args)         # `B1682`: and what it writes over
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
                    self._stdin(simple, name, lambda t: self.lexer.sub(t, apart=True))
                    return
                i += 2 if t in ("-o", "+o", "-O", "+O") else 1
                continue
            if t.startswith(("--", "+")):
                i += 1
                continue
            break
        rest = args[i:]
        if not rest:
            self._stdin(simple, name, lambda t: self.lexer.sub(t, apart=True))
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

    # ── `B1680` · what a program writes over by its own words ──────────────

    def _curl(self, name: str, args: List[_Word]) -> None:
        opts, operands = _scan(args, _CURL_SHORT, _CURL_LONG)
        said = {o for o, _v in opts}
        # Resuming appends; `--no-clobber` saves under another name.
        keeps = bool(said & {"-C", "--continue-at", "--no-clobber"})
        folder = next((v for o, v in reversed(opts) if o == "--output-dir" and v is not None), None)
        for option, value in opts:
            target = _file_value(value)
            if target is None:
                continue
            if option in ("-o", "--output") and not keeps:
                # `#1` is filled in from the address's own `[1-3]` range.
                named = _unknown(target.text) if re.search(r"#\d", target.text) else target
                self.writes(f"curl {option}", _under(folder, named))
            elif option in _CURL_SIDE_FILES:
                self.writes(_CURL_SIDE_FILES[option], target)
        if keeps or not said & {"-O", "--remote-name", "--remote-name-all"}:
            return
        addresses = operands + [v for o, v in opts if o == "--url" and v is not None]
        for address in addresses:
            self.writes("curl -O", _under(folder, _address_name(address, "curl_response")))

    def _wget(self, name: str, args: List[_Word]) -> None:
        opts, operands = _scan(args, _WGET_SHORT, _WGET_LONG)
        said = {o for o, _v in opts}
        never = any(o == "-n" and v is not None and "c" in v.text for o, v in opts) \
            or "--no-clobber" in said
        for option, value in opts:
            target = _file_value(value)
            if target is None:
                continue
            if option in ("-O", "--output-document") and not never:
                self.writes(f"{name} {option}", target)
            elif option in ("-o", "--output-file", "--save-cookies"):
                self.writes(f"{name} {option}", target)
        if (said & {"-N", "--timestamping"} and not said & _WGET_RECURSIVE
                and not said & {"-O", "--output-document"}):
            folder = next((v for o, v in reversed(opts)
                           if o in ("-P", "--directory-prefix") and v is not None), None)
            for address in operands:
                self.writes(f"{name} -N", _under(folder, _address_name(address, "index.html")))
        recursive = [o for o, _v in opts if o in ("-r", "--recursive", "-m", "--mirror", "-p",
                                                  "--page-requisites")]
        if recursive and not never and not said & {"-O", "--output-document"}:
            # `B1682`: a tree of names the command does not hold, in a folder
            # named for each site (`-nH`, `-nd`: the folder itself). Without
            # `-N` a `-nd` download keeps the old copy and saves `name.1`.
            letters = "".join(v.text for o, v in opts if o == "-n" and v is not None)
            no_dirs = "d" in letters or "--no-directories" in said
            if no_dirs and not said & {"-N", "--timestamping", "-m", "--mirror"}:
                return
            flat = (no_dirs or "H" in letters
                    or bool(said & {"--no-host-directories", "--protocol-directories"}))
            prefix = next((v for o, v in reversed(opts)
                           if o in ("-P", "--directory-prefix") and v is not None), None)
            addresses = list(operands) + ([_unknown("-i")] if said & {"-i", "--input-file"}
                                          else [])
            for address in addresses:
                where = (prefix or _Word(text=".")) if flat else _under(prefix, _site_folder(address))
                self.writes(f"{name} {recursive[0]}", where, sources=[_Word()], into="folder",
                            parents=True)

    def _sort(self, name: str, args: List[_Word]) -> None:
        opts, _operands = _scan(args, _SORT_SHORT, _SORT_LONG)
        for option, value in opts:
            target = _file_value(value)
            if option in ("-o", "--output") and target is not None:
                self.writes(f"sort {option}", target)

    def _unzip(self, name: str, args: List[_Word]) -> None:
        # `-x` takes the words after it, up to the next option.
        words, excluding = [], False
        for w in args:
            if w.text == "-x":
                excluding = True
            elif excluding and not w.text.startswith("-"):
                continue
            else:
                excluding = False
                words.append(w)
        opts, operands = _scan(words, _UNZIP_SHORT, set())
        said = {o for o, _v in opts}
        if not operands or any(o[1:] in _UNZIP_READS for o in said):
            return
        folder = next((v for o, v in reversed(opts) if o == "-d" and v is not None),
                      _Word(text="."))
        members = operands[1:]
        if any(not _spelled(m) or _GLOB_RE.search(m.text) for m in members):
            members = []        # its own patterns: which members, it decides
        if "-j" in said:
            members = [replace(m, text=posixpath.basename(m.text)) for m in members]
        if "-o" in said and "-n" not in said:
            self.writes("unzip -o", folder, sources=members or [_Word()], into="folder",
                        parents=True)
        # `B1698`: and what it unpacks, with `-o` or not, may be a link.
        self.links(name, folder, members or [_Word()], into="folder", parents=True,
                   copied="unpacked")

    def _tar(self, name: str, args: List[_Word]) -> None:
        opts, operands = _scan(args, _TAR_SHORT, _TAR_LONG, old_style=True)
        said = {o for o, _v in opts}
        archive = next((v for o, v in reversed(opts) if o in ("-f", "--file")), None)
        if "--remove-files" in said and said & {"-c", "--create", "-r", "--append", "-u",
                                                "--update"}:
            # `B1683`: each file it adds, taken away once it is in — from the
            # folder `-C` names, or (`-T`, several `-C`s) from where it decides.
            why = f"{name} --remove-files"
            folders = [v for o, v in opts if o in ("-C", "--directory")]
            if said & {"-T", "--files-from"} or len(folders) > 1 or None in folders:
                self.writes(why, _Word(text="."), sources=[_Word()], into="folder", removes=True)
            else:
                for member in operands:
                    path = _under(folders[0] if folders else None, member)
                    if path.text.endswith("/."):    # `-C site .`: the folder itself
                        path = replace(path, text=path.text[:-2])
                    self.removes(why, path, recursive=True)
        if said & {"-c", "--create"}:
            # It writes the archive whole (`-r`, `-u` and `-A` add to it).
            target = _file_value(archive)
            if target is not None:
                self.writes(f"{name} -c", target)
            return
        if not said & {"-x", "--extract", "--get"}:
            return
        if said & {"-O", "--to-stdout", "--to-command"}:
            return              # onto the screen, or into a program: no file
        folders = [v for o, v in opts if o in ("-C", "--directory")]
        if len(folders) > 1 or (folders and folders[0] is None):
            folder = _unknown(" ".join(w.text for w in folders if w is not None))
        else:
            folder = folders[0] if folders else _Word(text=".")
        members = operands
        if (said & {"-P", "--absolute-names", "--strip-components", "--transform", "--xform",
                    "--wildcards", "-T", "--files-from"}
                or any(not _spelled(m) for m in members)):
            members = []        # where each lands, it decides
        # `B1698`: with `-P`, which keeps a name's leading `/` and its `..`,
        # what it writes may be anywhere at all — measured, GNU tar 1.35: a
        # member named `/…/notes.md` writes the person's notes from inside a
        # folder `mkdir` made — so where cannot be known.
        absolute = bool(said & {"-P", "--absolute-names"})
        held = _file_value(archive)
        anywhere = _unknown(f"what {held.text if held is not None else 'the archive'} holds")
        if not said & {"-k", "--keep-old-files", "--skip-old-files"}:
            self.writes(f"{name} -x", anywhere if absolute else folder,
                        sources=members or [_Word()], into="folder", parents=True)
        # `B1698`: and what it unpacks, keeping old files or not, may be a link.
        self.links(f"{name} -x", anywhere if absolute else folder,
                   members or [_Word()], into="folder", parents=True, copied="unpacked")

    def _ffmpeg(self, name: str, args: List[_Word]) -> None:
        texts = {w.text for w in args}
        if "-y" not in texts or texts & _FFMPEG_INFO:
            return              # without `-y` it asks, and keeps the file
        i = 0
        while i < len(args):
            t = args[i].text
            if t == "-i" or (t.startswith("-") and len(t) > 1 and t not in _FFMPEG_FLAGS):
                i += 2          # an input, or an option's value
                continue
            if not t.startswith("-") or t == "-":
                target = args[i]
                if t.startswith("file:"):
                    target = replace(target, text=t[len("file:"):])
                if _file_value(target) is not None and not t.startswith("pipe:") \
                        and "://" not in t:
                    self.writes("ffmpeg -y", _unknown(t) if "%" in t else target)
            i += 1

    # ── `B1682` · the rest of the programs that write over a named output ──

    def _pandoc(self, name: str, args: List[_Word]) -> None:
        opts, _operands = _scan(args, _PANDOC_SHORT, _PANDOC_LONG)
        for option, value in opts:
            target = _file_value(value)
            if target is None:
                continue
            if option in ("-o", "--output", "--log"):
                self.writes(f"pandoc {option}", target)
            elif option == "--extract-media":
                # Named by the document, or by a hash of each: not the command.
                self.writes("pandoc --extract-media", target, sources=[_Word()], into="folder",
                            parents=True)

    def _magick(self, name: str, args: List[_Word]) -> None:
        words = list(args)
        tool = name
        if (name in ("magick", "gm") and words and words[0].plain()
                and words[0].text.lower() in _MAGICK_WRITERS | _MAGICK_OTHERS):
            tool = words.pop(0).text.lower()
        elif name == "gm":
            return              # each of its tools is named
        if tool == "mogrify":
            self._mogrify(f"{name} mogrify", words)     # `B1689`
            return
        if tool not in _MAGICK_WRITERS and tool != "magick":
            return              # it edits in place, or writes no file it is named
        if len(words) < 2 or {w.text for w in words} & _MAGICK_INFO:
            return
        why = name if tool == name else f"{name} {tool}"
        split = any(w.text == "+adjoin" for w in words)
        for j, w in enumerate(words[:-1]):
            if w.text in ("-write", "+write"):
                self._image_output(why, words[j + 1], split, name == "gm")
        self._image_output(why, words[-1], split, name == "gm")

    def _image_output(self, why: str, word: _Word, split: bool = False, gm: bool = False) -> None:
        """An ImageMagick output: a file, unless it is the screen, a pipe or
        no file at all (`null:`, `info:`, `x:`). `B1693`: and the numbered
        names it writes instead for several frames — unless its format keeps
        them in one file (`_MAGICK_ONE_FILE`) and `+adjoin` (`split`) does
        not say otherwise."""
        text = word.text
        if (text.startswith(("-", "+")) and text != "-") or text.lower().startswith(("fd:", "pipe:")):
            return              # an option where the output goes: it names none
        fmt = ""
        if word.plain() and _MAGICK_FORMAT.match(text):
            fmt, text = text.split(":", 1)
            word = replace(word, text=text)
        if _file_value(word) is None:
            return
        if "%" in text:
            self.writes(why, _unknown(text))     # its own numbers: unknowable already
            return
        self.writes(why, word)
        fmt = (fmt or posixpath.splitext(posixpath.basename(text))[1][1:]).lower()
        if split or fmt not in _MAGICK_ONE_FILE:
            self.numbered(why, word, gm=gm)

    def _openssl(self, name: str, args: List[_Word]) -> None:
        for j, w in enumerate(args):
            if not w.text.startswith("-"):
                continue
            key, eq, value = w.text.lstrip("-").partition("=")
            if key not in ("out", "keyout"):
                continue
            target = _file_value(replace(w, text=value) if eq
                                 else (args[j + 1] if j + 1 < len(args) else None))
            if target is not None:
                self.writes(f"openssl -{key}", target)

    def _webp(self, name: str, args: List[_Word]) -> None:
        for j, w in enumerate(args[:-1]):
            if w.text == "-o":
                target = _file_value(args[j + 1])
                if target is not None:
                    self.writes(f"{name} -o", target)

    def _sevenzip(self, name: str, args: List[_Word]) -> None:
        switches: List[_Word] = []
        operands: List[_Word] = []
        ended = False
        for w in args:
            if not ended and w.text == "--":
                ended = True
            elif not ended and w.text.startswith("-") and w.text != "-":
                switches.append(w)
            else:
                operands.append(w)
        said = [w.text.lower() for w in switches]
        if not operands:
            return
        command = operands[0].text.lower()
        if command in ("a", "u") and "-sdel" in said:
            # `B1683`: each file it adds, taken away once it is in.
            for w in operands[2:]:
                self.removes(f"{name} {command} -sdel", w, recursive=True)
            return
        if command not in ("x", "e") or "-so" in said:
            return
        modes = [s for s in said if s.startswith("-ao")]
        # Unless it asks, skips or renames, where what is there stays.
        over = (modes[-1] if modes else ("-aoa" if "-y" in said else "")) == "-aoa"
        why = f"{name} {command}"
        outs = [w for w in switches if w.text.startswith("-o")]
        folder = replace(outs[-1], text=outs[-1].text[2:]) if outs else _Word(text=".")
        if not folder.text or "*" in folder.text or any(s.startswith("-spf") for s in said):
            unknown = _unknown(folder.text or "-o")     # where each lands, it decides
            if over:
                self.writes(why, unknown)
            self.links(why, unknown, [_Word()], into="folder", parents=True, copied="unpacked")
            return
        members = operands[2:]
        if (any(s.startswith(("-i", "-ai")) or (s.startswith("-r") and s != "-r-") for s in said)
                or any(not _spelled(m) or _GLOB_RE.search(m.text) for m in members)):
            members = []        # which members, it decides
        if command == "e":
            members = [replace(m, text=posixpath.basename(m.text.rstrip("/"))) for m in members]
        if over:
            self.writes(why, folder, sources=members or [_Word()], into="folder", parents=True)
        # `B1698`: and what it unpacks, however it treats what is there, may be a link.
        self.links(why, folder, members or [_Word()], into="folder", parents=True,
                   copied="unpacked")

    def _ytdlp(self, name: str, args: List[_Word]) -> None:
        opts, _operands = _scan(args, _YTDLP_SHORT, _YTDLP_LONG)
        over = False
        for option, _value in opts:
            if option == "--force-overwrites":
                over = True
            elif option in ("-w", "--no-overwrites", "--no-force-overwrites"):
                over = False
        if not over:
            return              # the download itself is never written over
        why = f"{name} --force-overwrites"
        home: Optional[_Word] = None
        outputs: List[_Word] = []
        for option, value in opts:
            if value is None:
                continue
            kind = _YTDLP_KINDS.match(value.text) if value.plain() else None
            bare = replace(value, text=value.text[kind.end():]) if kind else value
            if option in ("-P", "--paths") and (kind is None or kind.group(1) == "home"):
                home = bare
            elif option in ("-o", "--output"):
                outputs.append(bare)
        if not outputs:
            # Its own template, `%(title)s [%(id)s].%(ext)s`: named by the video.
            self.writes(why, home or _Word(text="."), sources=[_Word()], into="folder")
            return
        for out in outputs:
            target = _file_value(out)
            if target is not None:
                self.writes(why, _under(home, _unknown(target.text) if "%" in target.text
                                        else target))

    def _rsync(self, name: str, args: List[_Word]) -> None:
        opts, operands = _scan(args, _RSYNC_SHORT, _RSYNC_LONG)
        said = {o for o, _v in opts}
        if said & _RSYNC_NOTHING or len(operands) < 2:
            return              # it only lists, or writes nothing here
        *sources, dest = operands
        names: List[_Word] = []
        copies: List[_Word] = []    # `B1696`: what each source is, for the links it keeps
        for src in sources:
            # `B1688`: a source on another machine by its path there — and
            # `host:*.md`, which the far side expands, by no name at all.
            path, far_source = _far_name(src, _REMOTE_PATH_RE)
            if "--files-from" in said or path.text.endswith("/") or path.text in ("", ".", ".."):
                names.append(_Word())       # what is in it: names the command does not hold
            else:
                names.append(path)
            if far_source or "--files-from" in said or path.text in ("", ".."):
                copies.append(_unknown(src.text))   # not looked at from here
            elif path.text.endswith("/") or path.text == ".":
                # What is in it, into the destination: the folder itself, there.
                copies.append(replace(path, text=path.text.rstrip("/") + "/."))
            else:
                copies.append(path)
        far = dest.plain() and bool(_REMOTE_PATH_RE.match(dest.text))
        was, self.lexer.far = self.lexer.far, self.lexer.far or far
        into = "folder" if dest.text.endswith("/") else ""
        parents = bool(said & {"-R", "--relative"})
        try:
            if not said & _RSYNC_KEEPS:     # unless it keeps what is there
                self.writes(name, dest, sources=names, into=into, parents=parents)
            copied = _rsync_keeps_links([o for o, _v in opts])
            if copied:
                # `B1696`: a symbolic link it copies is one there, with the
                # same text, whether or not it keeps what was there.
                self.links(name, dest, copies, into=into, parents=parents, copied=copied)
        finally:
            self.lexer.far = was

    # ── `B1688`–`B1690` · scp, the image tools, LibreOffice, heif-convert ──

    def _named_after(self, word: _Word, how: str) -> Optional[_Word]:
        """`B1689`, `B1690`. The name a program gives its output after an
        input: its last part (`base`), that without its last extension
        (`stem`; a name that only starts with a `.` has none, as LibreOffice
        reads `.notes`), or the whole path without its last extension
        (`root`: `heif-convert`'s `rfind('.')`). `None` when it cannot be
        known — the input is filled in when it runs — except one quoted
        variable (`"$f"`): `root` is `${f%.*}`, the shell's own spelling of
        that rule; `base` (`$f`) and `stem` (`${f%.*}`) only for a `for`
        loop's name, which holds no `/` and starts with no `.`
        (`lexer.bare`)."""
        text = word.text
        if _spelled(word):
            if how == "root":
                cut = text.rfind(".")
                return _Word(text=text[:cut] if cut >= 0 else text)
            base = posixpath.basename(text.rstrip("/"))
            if not base or how == "base":
                return _Word(text=base) if base else None
            cut = base.rfind(".")
            return _Word(text=base[:cut] if cut > 0 else base)
        var = word.var
        if (not var or word.fills != 1 or not _steady(word)
                or text not in (f"${var}", f"${{{var}}}")):
            return None
        if how != "root" and var not in self.lexer.bare:
            return None
        return _Word(text=text if how == "base" else f"${{{var}%.*}}", expanded=True, fills=2,
                     quoted=True)

    def _scp(self, name: str, args: List[_Word]) -> None:
        """`B1688`. `scp … sources target`, read as `cp` is: onto this
        machine, the target or each source's name in it; onto another, the
        far side, as `rsync`'s."""
        _opts, operands = _scan(args, _SCP_SHORT, set())
        if len(operands) < 2:
            return
        *sources, dest = operands
        names = [_far_name(src, _SCP_REMOTE_RE)[0] for src in sources]
        far = _far_name(dest, _SCP_REMOTE_RE)[1]
        was, self.lexer.far = self.lexer.far, self.lexer.far or far
        try:
            self.writes(name, dest, sources=names, into="folder" if dest.text.endswith("/") else "")
        finally:
            self.lexer.far = was

    def _jpegoptim(self, name: str, args: List[_Word]) -> None:
        """`B1689`. In place — the edit — unless `-d`/`--dest`, where only
        `-o`/`--overwrite` writes over a file that is there."""
        opts, operands = _scan(args, _JPEGOPTIM_SHORT, _JPEGOPTIM_LONG)
        said = {o for o, _v in opts}
        if said & {"-n", "--noaction", "--stdout", "-h", "--help", "-V", "--version"}:
            return
        dest = next((v for o, v in reversed(opts) if o in ("-d", "--dest") and v is not None), None)
        over = next((o for o in ("-o", "--overwrite") if o in said), "")
        if dest is None or not over:
            return              # an edit in place, or it keeps the file that is there
        why = f"{name} {over}"
        if said & {"--files-from", "--files-stdin", "--stdin"}:
            self.writes(why, dest, sources=[_Word()], into="folder")   # names it is handed
        for w in operands:
            base = self._named_after(w, "base")
            if base is None:
                self.writes(why, dest, sources=[_Word()], into="folder")
            elif not _same_path(_in(dest, base), w):
                self.writes(why, _in(dest, base))

    def _oxipng(self, name: str, args: List[_Word]) -> None:
        """`B1689`. In place — the edit — unless `--out` or `--dir`."""
        opts, operands = _scan(args, _OXIPNG_SHORT, _OXIPNG_LONG)
        said = {o for o, _v in opts}
        if said & {"-d", "--dry-run", "-P", "--pretend", "--stdout", "-h", "--help", "-V",
                   "--version"}:
            return
        inputs = [w for w in operands if w.text != "-"]
        out = next((v for o, v in reversed(opts) if o == "--out" and v is not None), None)
        if out is not None:
            target = _file_value(out)
            if target is not None and not (len(inputs) == 1 and _same_path(target, inputs[0])):
                self.writes(f"{name} --out", target)
            return
        folder = next((v for o, v in reversed(opts) if o == "--dir" and v is not None), None)
        if folder is None:
            return
        for w in inputs:
            # With `-r` an input may be a folder: what it holds, by no name here.
            base = None if said & {"-r", "--recursive"} else self._named_after(w, "base")
            if base is None:
                self.writes(f"{name} --dir", folder, sources=[_Word()], into="folder")
            elif not _same_path(_in(folder, base), w):
                self.writes(f"{name} --dir", _in(folder, base))

    def _mogrify(self, name: str, args: List[_Word]) -> None:
        """`B1689`. In place — the edit — unless `-path` (GraphicsMagick's
        `-output-directory`) or `-format`; and each `-write`, as `convert`'s."""
        fmt: Optional[_Word] = None
        folder: Optional[_Word] = None
        moved = ""
        inputs: List[_Word] = []
        if {w.text.lower() for w in args} & _MAGICK_INFO:
            return
        i = 0
        while i < len(args):
            w = args[i]
            t = w.text
            key = t.lower()
            i += 1
            if t in ("(", ")", "-") or not t.startswith(("-", "+")) or len(t) == 1:
                if t not in ("(", ")", "-"):
                    inputs.append(w)
                continue
            value = args[i] if i < len(args) else None
            if key == "-format" and value is not None:
                fmt = value
            elif key in ("-path", "-output-directory") and value is not None:
                folder, moved = value, key
            elif key in ("-write", "+write") and value is not None:
                self._image_output(f"{name} {key}", value, gm=name.startswith("gm"),
                                   split=any(a.text == "+adjoin" for a in args))
            if key in _MAGICK_TWO:
                i += 2
            elif t.startswith("-"):
                i += 0 if key in _MAGICK_FLAGS else 1
            else:
                i += 1 if key in _MAGICK_PLUS_VALUED else 0
        if fmt is None and folder is None:
            return              # each image in place: the edit
        why = f"{name} {moved or '-format'}"
        for w in inputs:
            out = self._mogrify_output(w, folder, fmt)
            if out is None:
                # A name it expands itself (`'*.jpg'`), or one filled in when it runs.
                where = folder if folder is not None else _Word(text=posixpath.dirname(w.text) or ".")
                if folder is None and not _word_is_plain_text(where.text):
                    where = _unknown(where.text)
                self.writes(why, where, sources=[_Word()], into="folder")
            elif not _same_path(out, w):
                self.writes(why, out)
                # `B1693`: `mogrify -format png anim.gif` writes `anim-0.png`….
                ext = (fmt.text if fmt is not None
                       else posixpath.splitext(posixpath.basename(out.text))[1][1:]).lower()
                if ext not in _MAGICK_ONE_FILE or any(a.text == "+adjoin" for a in args):
                    self.numbered(why, out, gm=name.startswith("gm"))

    def _mogrify_output(self, word: _Word, folder: Optional[_Word],
                        fmt: Optional[_Word]) -> Optional[_Word]:
        """`B1689`. The file `mogrify` writes for one input, as its source
        names it (`wand/mogrify.c`, `AppendImageFormat`), or `None`."""
        if word.plain() and _MAGICK_FORMAT.match(word.text):
            word = replace(word, text=word.text.split(":", 1)[1])     # `png:a.dat`
        text = word.text
        if any(c in text for c in "*?[") or text.startswith("@") or (
                fmt is not None and not (fmt.plain() and _word_is_plain_text(fmt.text))):
            return None
        if fmt is None:
            base = self._named_after(word, "base")
            return _in(folder, base) if base is not None else None
        if not _spelled(word):
            return None         # `-format`'s rule looks past `.gz`: no spelling of it
        ext = fmt.text
        base = posixpath.basename(text)
        packed = ""
        head, dot, last = base.rpartition(".")
        if dot and head and last.lower() in _MAGICK_PACKED:
            if folder is None:
                base = head     # it reads past `.gz`, and writes none
            else:
                base, packed = head, "." + last
        head, dot, _last = base.rpartition(".")
        name = (head if dot and head else base) + "." + ext + packed
        if folder is None:
            return _Word(text=posixpath.join(posixpath.dirname(text), name))
        return _in(folder, _Word(text=name))

    def _office(self, name: str, args: List[_Word]) -> None:
        """`B1690`. LibreOffice told to `--convert-to` (or `--print-to-file`):
        each document's name with the new extension, in `--outdir` or the
        folder it runs in."""
        convert: Optional[_Word] = None
        folder: Optional[_Word] = None
        printing = cat = False
        inputs: List[_Word] = []
        i = 0
        while i < len(args):
            w = args[i]
            t = w.text
            i += 1
            if not (t.startswith("-") and len(t) > 1):
                inputs.append(w)
                continue
            key, eq, value = t.partition("=")
            if not key.startswith("--"):
                key = "-" + key     # `-convert-to`, its old spelling
            value_word: Optional[_Word] = replace(w, text=value) if eq else None
            if key in _OFFICE_VALUES and not eq:
                value_word = args[i] if i < len(args) else None
                i += 1
            if key == "--convert-to":
                convert = value_word
            elif key == "--outdir":
                folder = value_word
            printing = printing or key == "--print-to-file"
            cat = cat or key == "--cat"
        if cat or not inputs or (convert is None and not printing):
            return              # the screen, or nothing converted
        where = folder if folder is not None else _Word(text=".")
        why = f"{name} {'--convert-to' if convert is not None else '--print-to-file'}"
        ext = convert.text.split(":", 1)[0] if convert is not None and _steady(convert) else ""
        for w in inputs:
            stem = self._named_after(w, "stem") if ext and _word_is_plain_text(ext) else None
            if stem is None:
                self.writes(why, where, sources=[_Word()], into="folder")
            else:
                self.writes(why, _in(folder, replace(stem, text=f"{stem.text}.{ext}")))

    def _heif(self, name: str, args: List[_Word]) -> None:
        """`B1690`. `heif-convert in [out]`: `-o`, its second word, or the
        input up to its last `.` with `.jpg`; and the metadata beside it."""
        opts, operands = _scan(args, _HEIF_SHORT, _HEIF_LONG)
        said = {o for o, _v in opts}
        if said & {"-h", "--help", "-v", "--version", "--list-decoders"} or not operands:
            return
        out = next((v for o, v in reversed(opts) if o in ("-o", "--output") and v is not None),
                   operands[1] if len(operands) > 1 else None)
        if out is None:
            root = self._named_after(operands[0], "root")
            out = (replace(root, text=root.text + ".jpg") if root
                   else _unknown(f"{operands[0].text}.jpg"))
        target = _file_value(out)
        if target is None:
            return
        self.writes(name, target)
        root = self._named_after(target, "root")
        for option, suffix in (("--with-xmp", ".xmp"), ("--with-exif", ".exif")):
            if option in said:
                self.writes(f"{name} {option}", replace(root, text=root.text + suffix) if root
                            else _unknown(target.text))
        if said & {"--with-aux", "--tiles", "-S", "--sequence"}:
            # Each auxiliary image, tile or frame: names the file decides.
            self.writes(name, _unknown(f"{root.text if root else target.text}-*"))
            return
        # `B1693`: a file holding several images is written `out-1.jpg`,
        # `out-2.jpg`… (`heif_dec.cc`), and their metadata, read as beside them.
        # `B1695`: numbered from 1, one after another (its `image_index`), so
        # `out-1.jpg` is written whenever any of them is.
        self.numbered(name, target, also=[s for o, s in (("--with-xmp", "xmp"),
                                                         ("--with-exif", "exif")) if o in said],
                      first=1)

    # ── `B1683` · what packs or unpacks a file and takes it away ──────────

    def _packer(self, name: str, args: List[_Word]) -> None:
        kind, unpacks_by_name = _PACKER_NAMES[name]
        spec = _PACKERS[kind]
        opts, operands = _scan(args, spec.shorts, set(spec.longs))
        said = [o for o, _v in opts]
        flags = set(said)
        if flags & spec.inert or flags & spec.stdout:
            return              # it tests, lists, or writes to the screen
        unpacking, removes, rm_word = unpacks_by_name, spec.removes, ""
        for o in said:          # the last one said wins
            if o in spec.unpack:
                unpacking = True
            elif o in spec.pack:
                unpacking = False
            elif o in spec.keep:
                removes, rm_word = False, ""
            elif o in spec.rm:
                removes, rm_word = True, o
        output = next((v for o, v in reversed(opts) if o in spec.output and v is not None), None)
        inputs = [w for w in operands if w.text != "-"]
        if kind == "lz4" and not flags & {"-m", "--multiple"} and len(inputs) == 2:
            inputs, output = inputs[:1], inputs[1]      # `lz4 in out`
        if output is not None:
            if _file_value(output) is None:
                return          # `-o -`: the screen
            removes = removes and not spec.keeps_with_output
        base = name + (" -d" if unpacking and not unpacks_by_name else "")
        gone, over = base + (f" {rm_word}" if rm_word else ""), base + " -f"
        force, recursive = bool(flags & spec.force), bool(flags & spec.recursive)
        if flags & spec.lists:
            # The names it is handed in a file, which the command does not hold.
            if removes:
                self.writes(gone, _Word(text="."), sources=[_Word()], into="folder", removes=True)
            return
        suffixes = [v.text for o, v in opts if o in spec.suffix_opts and v is not None]
        fmt = next((v.text.lower() for o, v in reversed(opts)
                    if o in ("-F", "--format") and v is not None and kind == "xz"), "")
        suffix = (suffixes[-1] if suffixes else ".lzma" if name == "lzma" or fmt in ("lzma", "alone")
                  else ".lz" if fmt == "lzip" else spec.suffix)
        flat = next((v for o, v in reversed(opts) if o == "--output-dir-flat" and v is not None), None)
        mirror = next((v for o, v in reversed(opts)
                       if o == "--output-dir-mirror" and v is not None), None)
        for w in inputs:
            source: _Word = w
            target: Optional[_Word] = None
            if unpacking:
                # The longest suffix it knows that the name ends with (`.tbz2`, not `.bz2`).
                known = sorted([(s, "") for s in suffixes] + list(spec.unpacks),
                               key=lambda sr: -len(sr[0]))
                hit = next(((s, r) for s, r in known
                            if s and w.text.endswith(s) and len(w.text) > len(s)), None)
                if hit:
                    target = replace(w, text=w.text[:-len(hit[0])] + hit[1])
                elif spec.bare == "try":
                    # `gunzip notes` unpacks `notes.gz`, or `notes.z`, or…
                    source = _unknown(w.text + spec.suffix)
                elif spec.bare == "out":
                    target = replace(w, text=w.text + ".out")
                else:
                    continue    # it names no output, and leaves the file
                if kind == "gzip" and target is not None and flags & {"-N", "--name"}:
                    target = _unknown(w.text)   # the name kept inside the file
            else:
                target = replace(w, text=w.text + suffix)
            if output is not None:
                target = output
            elif target is not None and flat is not None:
                target = _under(flat, replace(target, text=posixpath.basename(target.text)))
            elif target is not None and mirror is not None:
                target = _under(mirror, target)
            found = []
            if removes:
                found.append(lambda s=source: self.removes(gone, s, recursive=recursive))
            if force and target is not None:
                found.append(lambda t=target: self.writes(over, t))
            # What a person meets first: the file packed away, or the one an
            # unpacking writes over.
            for say in (reversed(found) if unpacking else found):
                say()

    def _zip(self, name: str, args: List[_Word]) -> None:
        """`B1683`. `zip -m`: each file it adds, taken away once it is in."""
        operands: List[_Word] = []
        move = recursive = handed = False
        i = 0
        while i < len(args):
            t = args[i].text
            i += 1
            if t in ("-x", "-i", "--exclude", "--include"):
                while i < len(args) and not args[i].text.startswith("-"):
                    i += 1              # its patterns, up to the next option
                continue
            if t in _ZIP_VALUES or t == "-TT":
                i += 1
                continue
            if t in ("-d", "--delete", "-U", "--copy-entries"):
                return                  # it changes what the archive holds, not your files
            if t.startswith("--"):
                move = move or t == "--move"
                recursive = recursive or t in ("--recurse-paths", "--recurse-patterns")
                handed = handed or t == "--names-stdin"
                continue
            if t.startswith("-") and t != "-":
                move = move or "m" in t[1:]
                recursive = recursive or "r" in t[1:] or "R" in t[1:]
                handed = handed or "@" in t[1:]
                continue
            operands.append(args[i - 1])
        if not move or not operands:
            return
        if handed:
            self.writes("zip -m", _Word(text="."), sources=[_Word()], into="folder", removes=True)
        for w in operands[1:]:
            self.removes("zip -m", w, recursive=recursive)

    def _ln(self, name: str, args: List[_Word]) -> None:
        """`B1692`. The names `ln` (and `link`) makes, read as GNU reads its
        words: `ln TARGET LINK`, `ln TARGET` (in the folder it runs in, by
        the target's name), `ln TARGET… FOLDER` or `-t FOLDER`; `-T` makes
        the last word the link whatever is there. A hard link shares its
        target's file; a symbolic one names it, from the link's own folder
        unless `-r` (`beside`). A write onto that name later in the command
        writes the target (`src/run_files.py`); `ln` itself makes the name
        and writes nothing (with `-f` it replaces — read above)."""
        opts, operands = _scan(args, _LN_SHORT, _LN_LONG)
        said = {o for o, _v in opts}
        if said & {"--help", "--version"} or not operands:
            return
        if name == "link":
            if len(operands) == 2:          # `link FILE1 FILE2`, and nothing else
                self.links("link", operands[1], operands[:1], into="file")
            return
        symbolic = bool(said & {"-s", "--symbolic"})
        beside = symbolic and not said & {"-r", "--relative"}
        why = "ln -s" if symbolic else "ln"
        folder = next((v for o, v in reversed(opts)
                       if o in ("-t", "--target-directory") and v is not None), None)
        if folder is not None:
            self.links(why, folder, operands, into="folder", beside=beside)
        elif len(operands) == 1:
            self.links(why, _Word(text="."), operands, into="folder", beside=beside)
        else:
            into = ("file" if said & {"-T", "--no-target-directory"}
                    else "folder" if len(operands) > 2 else "")
            self.links(why, operands[-1], operands[:-1], into=into, beside=beside)

    def _mv(self, name: str, args: List[_Word]) -> None:
        """`B1698`. The names `mv` puts what it moves at, its words read as
        `cp`'s are (`_copy_words`): `mv SOURCE DEST` (`-T`: `DEST` whatever
        is there), `mv SOURCE… FOLDER`, or `-t FOLDER`. Each holds what its
        source held — the person's file itself, or a symbolic link with the
        same text, read from its new folder — so a write onto it later in
        the command lands there (`src/run_files.py`): a `links` finding
        marked `moved`. With `-n` too, which only keeps a name that is there
        (above, replacing nothing), and moves onto one that is not."""
        words = _copy_words(name, args)
        if words is None:
            return                                  # it refuses: nothing moved
        flags, _said, operands, folder = words
        if flags & {"--help", "--version"}:
            return
        if folder is not None:
            if operands:
                self.links(name, folder, operands, into="folder", copied="moved")
            return
        if len(operands) < 2:
            return
        into = ("file" if flags & {"-T", "--no-target-directory"}
                else "folder" if len(operands) > 2 else "")
        self.links(name, operands[-1], operands[:-1], into=into, copied="moved")

    def _copies(self, name: str, args: List[_Word]) -> None:
        """`B1669`. `cp` or `install`: what it writes over, read as GNU reads
        its words (`_copy_words`)."""
        words = _copy_words(name, args)
        if words is None:
            return                                  # it refuses: nothing copied
        # `B1696`: `said`, the options in order — the last of `-L`/`-P` wins.
        flags, said, operands, folder = words
        if name == "install" and ({"-d", "--directory"} & flags):
            return                                  # it makes folders
        parents = "--parents" in flags
        if folder is not None:
            if not operands:
                return
            dest, sources, into = folder, operands, "folder"
        elif len(operands) >= 2:
            dest, sources = operands[-1], operands[:-1]
            into = "file" if ({"-T", "--no-target-directory"} & flags) else ""
        else:
            return
        symbolic = name == "cp" and bool({"-s", "--symbolic-link"} & flags)
        hard = name == "cp" and bool({"-l", "--link"} & flags)
        keeps = bool({"-n", "--no-clobber", "-b", "--backup", "--update=none",
                      "--update=none-fail"} & flags)
        if (symbolic or hard) and not _LINK_REPLACES & flags and not self.busybox:
            # `B1697`: a link onto a name that is there is refused ("File
            # exists") — it makes a new name, or nothing — unless told to
            # replace it (`-f`, `--remove-destination`, or `-i` and a yes).
            # Not BusyBox's: built `FEATURE_NON_POSIX_CP`, its default, it
            # takes the name away and links (`copy_file.c`'s
            # `ask_and_unlink`) — read as replacing it.
            keeps = True
        if not keeps:
            # Unless it never overwrites, or keeps what it would.
            self.writes(name, dest, sources=sources, into=into, parents=parents)
        if symbolic or hard:
            # `B1692`: it makes links, not copies — read after its own write,
            # which makes the name and does not write through it.
            self.links("cp -s" if symbolic else "cp -l", dest, sources, into=into,
                       parents=parents, beside=symbolic)
        copied = "" if name != "cp" or symbolic else _cp_keeps_links(said, hard)
        if copied:
            # `B1696`: a symbolic link it copies is one in the copy, with the
            # same text — so a write onto the copy writes where that points.
            self.links("cp", dest, sources, into=into, parents=parents, copied=copied)

    def _git(self, args: List[_Word]) -> None:
        with_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                      "--config-env"}
        i = 0
        # `B1698`: where its paths are named from — moved by each `-C`, and
        # unknown once told where its work tree is.
        home: Optional[_Word] = None
        while i < len(args) and args[i].text.startswith("-"):
            t = args[i].text
            if t == "-C" and i + 1 < len(args):
                home = _under(home, args[i + 1])
            elif t.startswith(("--work-tree", "--git-dir")):
                home = _unknown(t)
            i += 2 if t in with_value else 1
        if i >= len(args):
            return
        sub = args[i].text
        rest = args[i + 1:]
        flags = _flags(rest)
        plain = _plain_words(rest)
        self._git_puts(sub, rest, flags, plain, home)
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
            cut = next((j for j, w in enumerate(rest) if w.text == "--"), len(rest))
            names = [w for w in rest[:cut] if not w.text.startswith("-") or w.text == "-"]
            names += rest[cut + 1:]
            if len(names) >= 2 and not (_short(flags, "n") or "--dry-run" in flags):
                # `B1698`: as `mv` moves (`_mv`) — the work tree's own file, at its new name.
                names = [_under(home, w) for w in names]
                self.links("git mv", names[-1], names[:-1],
                           into="folder" if len(names) > 2 else "", copied="moved")
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

    def _git_puts(self, sub: str, rest: List[_Word], flags: List[str], plain: List[str],
                  home: Optional[_Word]) -> None:
        """`B1698`. A git command that writes its work tree from what git
        holds — another commit checked out or restored, a merge, a pull, a
        stash put back, a patch applied, a clone — may put a symbolic link
        at any name in it, pointing anywhere, as an archive may: a `links`
        finding marked `unpacked`. Where the work tree is, the words do not
        say (the folder the command is in, or any folder above it), so a
        write after one is unknown wherever it is; a clone's is the folder
        it names, and — named by its address (`git_url_basename`'s rules,
        not followed here) — unknown too. Not what leaves the tree as it
        is: a branch made where it stands (`checkout -b new`, `switch -c`),
        `restore --staged`, a soft or mixed `reset`, `stash list`, `apply
        --check`, a bare clone or one that checks nothing out, or `-h`."""
        if {"-h", "--help"} & set(flags):
            return
        why = f"git {sub}"
        if sub in ("checkout", "switch"):
            shorts, longs = (("bB", {"--orphan", "--conflict", "--pathspec-from-file"})
                             if sub == "checkout" else
                             ("cC", {"--create", "--force-create", "--orphan", "--conflict"}))
            opts, operands = _scan(rest, shorts, longs)
            if not operands and "--pathspec-from-file" not in {o for o, _v in opts}:
                return          # a branch made where it stands, or nothing at all
        elif sub == "restore":
            if ("--staged" in flags or _short(flags, "S")) and not (
                    "--worktree" in flags or _short(flags, "W")):
                return
        elif sub == "reset":
            if not {"--hard", "--merge", "--keep"} & set(flags):
                return
        elif sub == "stash":
            if plain[:1] and plain[0] in ("list", "show", "drop", "clear", "create", "store"):
                return
        elif sub == "apply":
            if {"--check", "--stat", "--numstat", "--summary", "--cached"} & set(flags):
                return
        elif sub == "clone":
            opts, operands = _scan(rest, _GIT_CLONE_SHORT, _GIT_CLONE_LONG)
            said = {o for o, _v in opts}
            if said & {"--bare", "--mirror", "-n", "--no-checkout"} or not operands:
                return
            folder = (_under(home, operands[1]) if len(operands) > 1
                      else _unknown(operands[0].text))
            self.links(why, folder, [_Word()], into="folder", copied="unpacked")
            return
        elif sub not in _GIT_PUTS:
            return
        self.links(why, _unknown("its work tree"), [_Word()], into="folder", copied="unpacked")

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
               findings: Optional[List[Finding]] = None, far: bool = False,
               apart: bool = False) -> List[Finding]:
    """Everything the reader finds in a shell command. Never raises: what it
    cannot read is itself a finding. `far` (`B1669`): the command runs on
    another machine or in a container; `apart` (`B1690`): in a shell of its
    own, started by the one a test was read in."""
    findings = findings if findings is not None else []
    text = str(command or "")
    if len(text) > MAX_COMMAND_CHARS:
        findings.append(Finding(UNREADABLE, "it is longer than this reader reads"))
        return findings
    try:
        lexer = _Lexer(depth, findings, far, apart)
        judge = _Judge(lexer)
        tokens = lexer.tokens(text)
        tests = _Tests(tokens, text)
        for simple in _simple_commands(tokens):
            tests.before(simple, lexer)
            start = len(findings)
            judge.simple(simple)
            tests.after(simple, findings, start)
    except _Unreadable as e:
        findings.append(Finding(UNREADABLE, e.why))
    except RecursionError:
        findings.append(Finding(UNREADABLE, "it nests commands deeper than this reader follows"))
    return findings


#: `B1682`. Where a test still decides whether the command after it runs: at
#: the head of its list, or after the operator it ends with (`a || [ -e f ] ||
#: …`). After the other one (`mkdir d && [ -e f ] || …`) the command runs when
#: what came before fails, whatever is at `f`.
_LIST_HEADS = ("", ";", "\n", "&", "(", ")", ";;", ";&", ";;&")
#: `B1682`. Variables bash gives a new value each time it expands them (`$_`
#: is the last word of the command before): a test of one is not a test of
#: what the next command writes.
_SHIFTING = frozenset({"RANDOM", "SRANDOM", "SECONDS", "LINENO", "BASHPID", "EPOCHREALTIME",
                       "EPOCHSECONDS", "BASH_COMMAND", "HISTCMD", "_"})


#: `B1690`. The keywords that begin a body — a loop's, a branch's, a group's
#: — so a test after one is at the head of its list.
_BODY_STARTS = frozenset({"do", "then", "else", "{"})
#: `B1690`. Where a body ends, or another branch begins: past these, what
#: runs no longer depends on a test inside it.
_BODY_ENDS = frozenset({"fi", "done", "}", "else", "elif", "esac"})
#: `B1690`. After these the shell may be elsewhere, or any variable another
#: value: no test before them speaks for what follows.
_RESETS = frozenset({"source", ".", "eval", "cd", "pushd", "popd", "chdir"})
_IDENT_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*")


def _leading(simple: _Simple) -> Tuple[List[str], List[_Word]]:
    """`B1690`. A command's keywords (`do`, `then`, `!`, `done`…) and the
    words after them."""
    words = list(simple.words)
    lead: List[str] = []
    while words and words[0].keyword(*_SKIP):
        lead.append(words.pop(0).text)
    return lead, words


def _existence(lead: Sequence[str], words: Sequence[_Word]) -> Optional[Tuple[bool, _Word, str]]:
    """`B1682`, `B1690`. `[ -e f ]`, `test -f f` or `[[ -e f ]]`, each
    turned round by a `!` inside it or before it: `(absent, f, the test)` —
    `absent` when it holds only while nothing (`-e`), or nothing that is a
    file (`-f`), is at `f` — or `None`: another command or test, or a path
    whose words may not name the same file twice (`_steady`)."""
    negated = lead.count("!") % 2 == 1
    if len(words) < 3:
        return None
    if words[0].keyword("[") and words[-1].keyword("]"):
        body = list(words[1:-1])
    elif words[0].keyword("[[") and words[-1].keyword("]]"):
        body = list(words[1:-1])
    elif words[0].keyword("test"):
        body = list(words[1:])
    else:
        return None
    if len(body) == 3 and body[0].keyword("!"):
        negated, body = not negated, body[1:]
    if len(body) != 2 or not body[0].keyword("-e", "-f") or not _steady(body[1]):
        return None
    return negated, body[1], body[0].text


def _guard(simple: _Simple) -> Optional[Tuple[str, _Word, str]]:
    """`B1682`. `[ -e f ] || cmd`, `test -f f || cmd`, `[[ -e f ]] || cmd` or
    `[ ! -e f ] && cmd`: the command after it runs only when nothing is at
    `f` (`-e`), or nothing that is a file (`-f`) — so what it writes at `f`
    replaces nothing, and Image Optimiser's `[ -e optimised/a.webp ] || cwebp
    … -o optimised/a.webp` skips what it made before instead of being refused
    for it. `(the operator, f, the test)`, or `None`. (`B1690`: `f` may be
    any words that name the same file each time — `_steady` — and a `!` in
    front turns the test round.)"""
    if simple.compound:
        return None
    lead, words = _leading(simple)
    test = _existence(lead, words)
    if test is None:
        return None
    absent, word, how = test
    ender = "&&" if absent else "||"
    # After a keyword it is the head of the list the keyword begins.
    after = "" if any(k != "!" for k in lead) else simple.after
    if simple.ended_by != ender or after not in _LIST_HEADS + (ender,):
        return None
    return ender, word, how


def _unguard(findings: List[Finding], start: int, word: _Word, test: str) -> None:
    """`B1682`. Take back what the command a test decides writes at the
    path it tested — not when it moves elsewhere first (`env -C`, `sh -c 'cd
    …'`) or writes on another machine, and after `-f` only a write onto the
    name, not a copy into a folder there. (`B1690`: the same words, read the
    same way — `steady` — whether or not the run can fill them in.)"""
    added = findings[start:]
    if any(f.kind == CHDIR for f in added):
        return
    findings[start:] = [
        # `B1695`: a test of the first of a program's numbered names skips
        # them all where it is there — kept, marked, for the run to read
        # each numbered name that was there against the first of its own.
        replace(f, tested=True) if f.kind == WRITES and not f.far and f.first == word.text
        else f
        for f in added if not (
            f.kind == WRITES and not f.far and f.steady and f.path == word.text
            and (test == "-e" or not f.sources))]


def _skips_the_rest(words: Sequence[_Word]) -> bool:
    """`B1690`. `continue` or `break`, alone or with a count (`continue 2`)
    — not `continue 0` or `$n`, which fail and let what follows run."""
    return bool(words) and words[0].keyword("continue", "break") and (
        len(words) == 1 or (len(words) == 2 and words[1].plain()
                            and words[1].text.isdigit() and int(words[1].text) >= 1))


def _names_in(word: _Word) -> frozenset:
    """`B1690`. The variables a path's words read (`~` reads `HOME`)."""
    names = set(re.findall(r"\$\{?[#!]?([A-Za-z_][A-Za-z0-9_]*)", word.text))
    if word.text.startswith("~"):
        names.add("HOME")
    return frozenset(names)


def _sets(simple: _Simple, words: Sequence[_Word]) -> Optional[set]:
    """`B1690`. The variables `simple` could give another value: every name
    in its words that is not read with a `$` (`o=x`, `read o`, `export o`,
    `for o in`, `(( o++ ))`) or that a `${o:=…}` sets — more than it sets,
    which only ends a test sooner — or `None` for any at all (`source`,
    `eval`) or a folder change (`cd`, `popd`) after which a path names
    another file. An option (`-f`, `-o`) is not a name."""
    if words and words[0].plain() and words[0].text in _RESETS:
        return None
    found: set = set()
    for w in list(simple.words) + [t for _op, t in simple.redirects]:
        text = w.text
        for m in _IDENT_RE.finditer(text):
            before = text[:m.start()]
            if before.endswith(("$", "${", "${#", "${!")):
                if before.endswith("${") and re.match(r":?=", text[m.end():]):
                    found.add(m.group(0))
            elif not before.endswith("-"):
                found.add(m.group(0))
    return found


def _redefines(tokens: Sequence[tuple]) -> bool:
    """`B1690`. Whether a command defines a function (`f() {`, `function
    f`) — whose body runs wherever it is called, and may set anything — a
    `trap` (whose command runs between any two), or a name for another
    variable (`declare -n r=o`)."""
    for j, tok in enumerate(tokens):
        if tok[0] != "w":
            continue
        word = tok[1]
        if (word.keyword("function", "trap")
                or tokens[j + 1:j + 3] == [("op", "("), ("op", ")")]):
            return True
        if word.plain() and word.text in ("declare", "typeset", "local"):
            k = j + 1
            while k < len(tokens) and tokens[k][0] != "op":
                t = tokens[k]
                if (t[0] == "w" and t[1].text.startswith("-") and not t[1].text.startswith("--")
                        and "n" in t[1].text):
                    return True
                k += 1
    return False


class _Tests:
    """`B1682`, `B1690`. The tests in a command that decide whether what
    follows them runs, followed as the command is read — so a write the
    command makes only where nothing was replaces nothing:

      * `B1682`: one at the head of its list over the next command —
        `[ -e f ] || cwebp … -o f`, `[ ! -e f ] && echo x > f`;
      * a loop's `[ -e f ] && continue` (or `break`, or `[ ! -e f ] ||
        continue`) over the rest of its body — File Converter's arms — when
        it is in the same shell as its loop (in `( … )` or a pipe a
        `continue` ends nothing, and bash runs on), at the head of its list
        or after an `||`, and inside a loop at all;
      * `if [ ! -e f ]; then …` (`elif`, `! [ -e f ]`, `test ! -e f`) over
        its branch, when the test is the whole condition.

    A body ends at its `done`, `fi`, `}`, `else`/`elif`, a case arm's `;;` or
    a subshell's `)`, and a test stops speaking for what follows at a `cd`,
    `popd` or `source`, or a command that could set a variable its path is
    spelled with (`_sets`), where its words stop naming the same file; and
    a write in a shell of its own (`sh -c '…'`) is the same file only when
    its words fill nothing in (`_Lexer.apart`). A command that defines a
    function, a `trap` or a `declare -n` keeps no body-wide test
    (`_redefines`).

    And `for f in *`: a loop's name over words with no `/`, no leading `.`
    and no expansion (and no `dotglob` anywhere) holds a name in the folder
    — no `/`, no leading `.` — until something sets it (`lexer.bare`), which
    is what makes `libreoffice --outdir converted "$f"` write exactly
    `converted/${f%.*}.pdf` (`_Judge._named_after`)."""

    def __init__(self, tokens: Sequence[tuple], text: str):
        self.whole = not _redefines(tokens)
        self.dotglob = "dotglob" in text or "GLOBIGNORE" in text
        self.next: Optional[Tuple[str, _Word, str]] = None
        self.held: List[Tuple[_Word, str, frozenset]] = []
        self.loops: List[list] = []         # [depth, name, bare] per `do` open
        self.header: Optional[Tuple[str, bool]] = None
        self.last: Optional[tuple] = None   # the command before, as a test
        self.branch: Optional[Tuple[_Word, str, frozenset]] = None

    def _header(self, words: Sequence[_Word]) -> Tuple[str, bool]:
        """`for name in words`: its name, and whether each value is bare."""
        name = words[1].text if len(words) > 1 and words[1].plain() else ""
        if not _NAME_RE.fullmatch(name):
            return "", False
        listed = list(words[3:]) if len(words) > 2 and words[2].keyword("in") else None
        bare = (self.whole and not self.dotglob and words[0].keyword("for") and listed is not None
                and all(w.text and not (w.expanded or w.braced) and "/" not in w.text
                        and not w.text.startswith((".", "[")) for w in listed))
        return name, bare

    def before(self, simple: _Simple, lexer: _Lexer) -> None:
        lead, words = _leading(simple)
        if self.held and (simple.compound or simple.after == ")" or _BODY_ENDS & set(lead)):
            self.held = []
        for k in lead:
            if k == "done" and self.loops:
                self.loops.pop()
            elif k == "do":
                name, bare = self.header or ("", False)
                self.loops.append([simple.depth, name, bare])
                self.header = None
        if self.branch is not None and lead[:1] == ["then"]:
            self.held.append(self.branch)
        self.branch = None
        if words and words[0].keyword("for", "select"):
            self.header = self._header(words)
        bare, seen = set(), set()
        for _depth, name, is_bare in reversed(self.loops):     # the innermost loop's name wins
            if name and name not in seen:
                seen.add(name)
                if is_bare:
                    bare.add(name)
        lexer.bare = frozenset(bare)

    def after(self, simple: _Simple, findings: List[Finding], start: int) -> None:
        lead, words = _leading(simple)
        sets = _sets(simple, words)
        self.held = [] if sets is None else [g for g in self.held if not g[2] & sets]
        for frame in self.loops:
            if sets is None or frame[1] in sets:
                frame[2] = False
        if self.next is not None and simple.after == self.next[0]:
            _unguard(findings, start, self.next[1], self.next[2])
        for word, test, _names in self.held:
            _unguard(findings, start, word, test)
        if any(f.kind == CHDIR for f in findings[start:]):
            self.held = []
        self.next = _guard(simple)
        if (self.whole and self.last is not None and not lead and _skips_the_rest(words)
                and simple.ended_by in (";", "\n") and self.loops
                and self.loops[-1][0] == simple.depth):
            absent, word, test, before, before_after = self.last
            ender = "||" if absent else "&&"
            if (before.depth == simple.depth and simple.after == before.ended_by == ender
                    and before_after in _LIST_HEADS + ("&&" if absent else "||",)):
                self.held.append((word, test, _names_in(word)))
        body = [k for k in lead if k != "!"]
        test = None if simple.compound else _existence(lead, words)
        self.last = None
        if test is not None and set(body) <= _BODY_STARTS:
            self.last = (*test, simple, "" if body else simple.after)
        if (self.whole and test is not None and test[0] and body and body[-1] in ("if", "elif")
                and simple.ended_by in (";", "\n")):
            self.branch = (test[1], test[2], _names_in(test[1]))
        if simple.ended_by in (")", ";;", ";&", ";;&"):
            self.held = []


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
    links: List[Finding] = []       # `B1692`
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
        elif name in ("os.link", "os.symlink"):
            # `B1692`: a name the commands it runs may write through. Read
            # first, wherever it is in the code: `ast.walk` is not the order
            # the code runs in, and a link read late would be missed.
            given = dict(zip(("src", "dst"), node.args))
            given.update({k.arg: k.value for k in node.keywords if k.arg in ("src", "dst")})
            src, dst = _literal(given.get("src")), _literal(given.get("dst"))
            links.append(Finding(LINKS, name, path=dst or "", known=bool(dst) and dst[:1] != "~",
                                 sources=((src or "", bool(src) and src[:1] != "~"),),
                                 into="file", beside=name == "os.symlink"))
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
                read_shell(_literal(first), depth=depth + 1, findings=findings, apart=True)
            elif isinstance(first, (ast.List, ast.Tuple)) and first.elts and _literal(first.elts[0]):
                # The program is named; an argument filled in when it runs is a
                # placeholder, which the reader sees as an expansion.
                line = " ".join(shlex.quote(_literal(e)) if _literal(e) is not None else "$ARG"
                                for e in first.elts)
                read_shell(line, depth=depth + 1, findings=findings, apart=True)
            else:
                findings.append(Finding(UNREADABLE, f"{name} runs a command made when it runs"))
        elif isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if method in _PY_METHODS:
                findings.append(Finding(DESTROYS, f".{method}() {_PY_METHODS[method]}"))
            elif method in _PY_SQL and node.args and _literal(node.args[0]) is not None \
                    and _SQL_DESTROYS.search(_literal(node.args[0])):
                findings.append(Finding(DESTROYS, "it hands a database a statement that deletes"))
    return links + findings


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


def writes_of(findings: Sequence[Finding], command: str = "") -> Tuple[Finding, ...]:
    """`B1669`. What the command writes over and where it goes, in the order
    read — for the run to look at (`src/run_files.command_replaces`). Empty
    when it writes over nothing it names.

    `B1681`. `command` is the whole text read. A variable it could set
    itself — its name written anywhere but in a `$name` or `${name…}`
    (`PANTHEON_PROJECTS=/x; …`, `export HOME=/etc`, `env NAME=… sh -c …`,
    Python's `os.environ["NAME"] = …`) — is not the run's value, so a path
    spelled against it is not known; nor, with `HOME`, a path after `~`.

    `B1692`. And the links it makes, which a write after them goes through
    — and which, even with no write, the run must not go on taking for its
    own once a link is there."""
    if not any(f.kind in (WRITES, LINKS) for f in findings):
        return ()
    out = tuple(f for f in findings if f.kind in (WRITES, CHDIR, LINKS))
    if command:
        home_set = _set_here("HOME", command)
        out = tuple(replace(f, known=False, var="", split=False)
                    if f.known and ((f.var and _set_here(f.var, command))
                                    or (home_set and f.path.startswith("~")))
                    else f for f in out)
    return out


def _set_here(name: str, command: str) -> bool:
    """`B1681`. Whether `command` could set the variable `name` itself: the
    name appears other than right after a `$` or `${`."""
    for m in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", command):
        if not command[:m.start()].endswith(("$", "${")):
            return True
    return False


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
