# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1880` — the pattern an If or a Switch condition "matches", checked in time
proportional to the text, whatever the pattern and whatever the text.

The audit (`condition-operators-and-coercion`) asked for a condition that
matches a pattern ("an order number like AB-1234", "a subject that starts
with Re: or Fwd:"). Python's own `re` backtracks: a pattern such as `(a+)+$`
the author writes once, run on text whoever sends the mail chooses, takes
time exponential in the text's length — the denial of service
`src/tool_allow_rules.py` refuses a regex kind for. So a pattern here is read
by this module's own small engine and never handed to `re`:

  * **what a pattern may say** — a character as itself; `.` any character
    but a new line; `\\d` a digit (0-9), `\\w` a letter, digit or _, `\\s`
    a space of any kind, and their capitals for "not"; `\\n`, `\\t`, and `\\`
    before any sign for the sign itself; `[abc]`, `[a-z]`, `[^…]` one of
    (or none of) a set; `^` the start and `$` the end of the text (or just
    before a last new line, as in most pattern languages); `( )` and
    `(?: )` to group; `|` one or the other; `*`, `+`, `?` and `{n}`,
    `{n,}`, `{n,m}` to repeat (a `?` after one is accepted and changes
    nothing: here a pattern only says yes or no). Nothing else — no
    referring back to a group, no looking ahead or behind, no flags —
    each refused at save in a sentence (`pattern_problem`);
  * **bounded** — a pattern is at most `PATTERN_MAX_CHARS` characters, a
    count at most `PATTERN_REPEAT_MAX`, groups `PATTERN_DEPTH_MAX` deep, and
    what it is compiled to at most `PATTERN_PROGRAM_MAX` steps; the text
    looked at is its first `PATTERN_TEXT_MAX` characters;
  * **linear** — the compiled pattern is run as a set of states moving
    together over the text (Thompson's construction), each character
    visited once; a set of states met before is looked up, not worked out
    again. So the time is at most the text's length times the program's,
    both bounded above, and a pattern cannot make it more;
  * **a search** — it holds when the pattern is found anywhere in the text,
    unless `^` or `$` pins it to the start or the end.

Pure: no I/O, no clock, nothing a value supplies is called.
"""

from __future__ import annotations

import re
from functools import lru_cache

PATTERN_MAX_CHARS = 120
PATTERN_REPEAT_MAX = 50
PATTERN_DEPTH_MAX = 10
PATTERN_PROGRAM_MAX = 400
PATTERN_TEXT_MAX = 20_000
# How many state-and-character steps one text remembers; past it a step is
# worked out each time (the bound on time holds either way).
_CACHE_MAX = 4096

# The words a refusal says, after "The pattern …".
PATTERN_HELP = ("A pattern knows . (any character), \\d \\w \\s (a digit, a letter or digit, "
                "a space) and their capitals for “not”, [abc] and [a-z] (one of these), "
                "^ and $ (the start and the end), ( ) and | (one or the other), and "
                "* + ? {2,5} to repeat.")

_COUNT_RE = re.compile(r"\{([0-9]{1,3})(?:(,)([0-9]{0,3}))?\}")
_CLASS_ESCAPES = "dDwWsS"


class PatternError(ValueError):
    """A pattern this module does not read. `sentence` says why in words."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


def _class_hit(kind: str, ch: str) -> bool:
    if kind == "d":
        return "0" <= ch <= "9"
    if kind == "D":
        return not ("0" <= ch <= "9")
    if kind == "w":
        return ch == "_" or ch.isalnum()
    if kind == "W":
        return not (ch == "_" or ch.isalnum())
    if kind == "s":
        return ch.isspace()
    return not ch.isspace()          # "S"


def _set_hit(items: tuple, ch: str) -> bool:
    for item in items:
        if item[0] == "c":
            if ch == item[1]:
                return True
        elif item[0] == "r":
            if item[1] <= ch <= item[2]:
                return True
        elif _class_hit(item[1], ch):
            return True
    return False


def _hit(matcher: tuple, ch: str, fold: bool) -> bool:
    """Does one character match one step of the pattern? `fold`: capitals
    do not count."""
    kind = matcher[0]
    if kind == "lit":
        return ch == matcher[1] or (fold and ch.lower() == matcher[1].lower())
    if kind == "any":
        return ch != "\n"
    if kind == "cls":
        return _class_hit(matcher[1], ch)
    _, negated, items = matcher
    hit = _set_hit(items, ch) or (fold and (_set_hit(items, ch.lower())
                                            or _set_hit(items, ch.upper())))
    return hit != negated


class _Reader:
    """The pattern read into a tree: `("alt", [..])`, `("seq", [..])`,
    `("rep", node, low, high)`, `("char", matcher)`, `("bol",)`, `("eol",)`."""

    def __init__(self, text: str):
        self.t = text
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def read(self):
        node = self.alt()
        if self.i < len(self.t):
            raise PatternError("closes a group with ) that was never opened.")
        return node

    def alt(self):
        branches = [self.seq()]
        while self.peek() == "|":
            self.i += 1
            branches.append(self.seq())
        return ("alt", branches) if len(branches) > 1 else branches[0]

    def seq(self):
        items = []
        while self.peek() is not None and self.peek() not in "|)":
            items.append(self.repeated(self.atom()))
        return ("seq", items)

    def atom(self):
        c = self.t[self.i]
        if c == "(":
            self.i += 1
            if self.t.startswith("?:", self.i):
                self.i += 2
            elif self.peek() == "?":
                raise PatternError("looks ahead or behind, or names a group: (?…) other than "
                                   "(?:…) is not something a pattern here does.")
            self.depth += 1
            if self.depth > PATTERN_DEPTH_MAX:
                raise PatternError(f"has groups more than {PATTERN_DEPTH_MAX} deep.")
            inner = self.alt()
            if self.peek() != ")":
                raise PatternError("opens a group with ( that is never closed.")
            self.i += 1
            self.depth -= 1
            return inner
        if c == "[":
            return ("char", self.char_set())
        if c in "*+?{":
            raise PatternError("has a *, +, ? or {…} with nothing before it to repeat; "
                               "write \\ before it for the sign itself.")
        self.i += 1
        if c == "^":
            return ("bol",)
        if c == "$":
            return ("eol",)
        if c == ".":
            return ("char", ("any",))
        if c == "\\":
            self.i -= 1
            return ("char", self.escape())
        return ("char", ("lit", c))

    def escape(self):
        self.i += 1
        if self.i >= len(self.t):
            raise PatternError("ends in a \\ with nothing after it.")
        c = self.t[self.i]
        self.i += 1
        if c in _CLASS_ESCAPES:
            return ("cls", c)
        if c == "n":
            return ("lit", "\n")
        if c == "t":
            return ("lit", "\t")
        if c.isdigit():
            raise PatternError(f"refers back to a group (\\{c}), which a pattern here cannot.")
        if c.isalnum() or c == "_":
            raise PatternError(f"has \\{c}, which a pattern here does not know: it knows \\d \\w "
                               f"\\s, their capitals, \\n and \\t, and \\ before a sign for "
                               f"the sign itself.")
        return ("lit", c)

    def char_set(self):
        self.i += 1
        negated = False
        if self.peek() == "^":
            negated = True
            self.i += 1
        items = []
        first = True
        while True:
            c = self.peek()
            if c is None:
                raise PatternError("opens a set with [ that is never closed.")
            if c == "]" and not first:
                self.i += 1
                break
            first = False
            if c == "\\":
                m = self.escape()
                item = ("c", m[1]) if m[0] == "lit" else ("k", m[1])
            else:
                self.i += 1
                item = ("c", c)
            if (item[0] == "c" and self.peek() == "-" and self.i + 1 < len(self.t)
                    and self.t[self.i + 1] != "]"):
                self.i += 1
                if self.peek() == "\\":
                    m = self.escape()
                    if m[0] != "lit":
                        raise PatternError("has a range in […] that does not run from one "
                                           "character to another.")
                    high = m[1]
                else:
                    high = self.t[self.i]
                    self.i += 1
                if high < item[1]:
                    raise PatternError(f"has the range {item[1]}-{high}, which runs backwards.")
                item = ("r", item[1], high)
            items.append(item)
        return ("set", negated, tuple(items))

    def repeated(self, atom):
        c = self.peek()
        if c is None or c not in "*+?{":
            return atom
        if atom[0] in ("bol", "eol"):
            raise PatternError("repeats ^ or $, which mark the start and the end.")
        if c == "*":
            low, high = 0, None
            self.i += 1
        elif c == "+":
            low, high = 1, None
            self.i += 1
        elif c == "?":
            low, high = 0, 1
            self.i += 1
        else:
            m = _COUNT_RE.match(self.t, self.i)
            if not m:
                raise PatternError("has a { that is not a count such as {3} or {2,5}; "
                                   "write \\{ for the sign itself.")
            low = int(m.group(1))
            if m.group(2) is None:
                high = low
            else:
                high = int(m.group(3)) if m.group(3) else None
            if low > PATTERN_REPEAT_MAX or (high is not None and high > PATTERN_REPEAT_MAX):
                raise PatternError(f"counts more than {PATTERN_REPEAT_MAX}.")
            if high is not None and high < low:
                raise PatternError("has a count {m,n} whose n is less than its m.")
            self.i = m.end()
        if self.peek() == "?":
            self.i += 1          # "as few as can be" — the same yes or no here
        if self.peek() is not None and self.peek() in "*+{":
            raise PatternError("repeats a repeat (such as a**); put the inner one in ( ).")
        return ("rep", atom, low, high)


def _emit(node, prog: list) -> None:
    """Compile `node` onto `prog`: `("char", m)`, `("split", x, y)`,
    `("jmp", x)`, `("bol",)`, `("eol",)`."""
    if len(prog) > PATTERN_PROGRAM_MAX:
        raise PatternError("repeats too much to be checked quickly; count less, or "
                           "repeat a shorter part.")
    kind = node[0]
    if kind == "char":
        prog.append(("char", node[1]))
    elif kind in ("bol", "eol"):
        prog.append((kind,))
    elif kind == "seq":
        for item in node[1]:
            _emit(item, prog)
    elif kind == "alt":
        jumps = []
        branches = node[1]
        for k, branch in enumerate(branches):
            if k < len(branches) - 1:
                split_at = len(prog)
                prog.append(None)
                _emit(branch, prog)
                jumps.append(len(prog))
                prog.append(None)
                prog[split_at] = ("split", split_at + 1, len(prog))
            else:
                _emit(branch, prog)
        for at in jumps:
            prog[at] = ("jmp", len(prog))
    elif kind == "rep":
        _, atom, low, high = node
        for _ in range(low):
            _emit(atom, prog)
        if high is None:
            loop = len(prog)
            prog.append(None)
            _emit(atom, prog)
            prog.append(("jmp", loop))
            prog[loop] = ("split", loop + 1, len(prog))
        else:
            outs = []
            for _ in range(high - low):
                outs.append(len(prog))
                prog.append(None)
                _emit(atom, prog)
            for at in outs:
                prog[at] = ("split", at + 1, len(prog))
    if len(prog) > PATTERN_PROGRAM_MAX:
        raise PatternError("repeats too much to be checked quickly; count less, or "
                           "repeat a shorter part.")


@lru_cache(maxsize=256)
def compile_pattern(pattern: str) -> tuple:
    """The program for `pattern`, its last step `("match",)`. Raises
    `PatternError`."""
    if not isinstance(pattern, str) or not pattern:
        raise PatternError("is empty.")
    if len(pattern) > PATTERN_MAX_CHARS:
        raise PatternError(f"is longer than {PATTERN_MAX_CHARS} characters.")
    prog: list = []
    _emit(_Reader(pattern).read(), prog)
    prog.append(("match",))
    return tuple(prog)


def pattern_problem(pattern) -> str | None:
    """`None` for a pattern this module reads, else why not — "is longer
    than 120 characters." — said after "The pattern “…” "."""
    try:
        compile_pattern(pattern)
    except PatternError as exc:
        return exc.sentence
    return None


def _closure(prog: tuple, pcs, at_start: bool, at_end: bool) -> frozenset:
    """Every step reachable from `pcs` without reading a character."""
    out = set()
    stack = list(pcs)
    while stack:
        pc = stack.pop()
        if pc in out:
            continue
        out.add(pc)
        step = prog[pc]
        op = step[0]
        if op == "jmp":
            stack.append(step[1])
        elif op == "split":
            stack.append(step[2])
            stack.append(step[1])
        elif op == "bol":
            if at_start:
                stack.append(pc + 1)
        elif op == "eol":
            if at_end:
                stack.append(pc + 1)
    return frozenset(out)


def pattern_found(pattern: str, text: str, *, fold: bool = True) -> bool:
    """Is `pattern` found in `text` (its first `PATTERN_TEXT_MAX`
    characters)? `fold`: capitals do not count. A pattern that does not read
    is never found. Never raises on what it is handed."""
    try:
        prog = compile_pattern(pattern)
    except (PatternError, TypeError):
        return False
    if not isinstance(text, str):
        return False
    cut = len(text) > PATTERN_TEXT_MAX
    if cut:
        text = text[:PATTERN_TEXT_MAX]
    done = len(prog) - 1
    state = _closure(prog, (0,), True, not text and not cut)
    if done in state:
        return True
    restart = _closure(prog, (0,), False, False)
    cache: dict = {}
    last = len(text) - 1
    for i, ch in enumerate(text):
        if i == last and ch == "\n" and not cut and _at_end(prog, state, done):
            return True   # `$` is also just before a last new line, as in most patterns
        key = (state, ch)
        nxt = cache.get(key)
        if nxt is None:
            moved = [pc + 1 for pc in state if prog[pc][0] == "char" and _hit(prog[pc][1], ch, fold)]
            nxt = _closure(prog, moved, False, False) | restart
            if len(cache) < _CACHE_MAX:
                cache[key] = nxt
        state = nxt
        if done in state:
            return True
    if cut:
        return False      # `$` is the end of the text, and this is not it
    return _at_end(prog, state, done)


def _at_end(prog: tuple, state: frozenset, done: int) -> bool:
    """Would the pattern be found if the text ended here (`$` passes)?"""
    ends = [pc for pc in state if prog[pc][0] == "eol"]
    return bool(ends) and done in _closure(prog, ends, False, True)
