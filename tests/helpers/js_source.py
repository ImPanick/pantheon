# SPDX-License-Identifier: AGPL-3.0-or-later
r"""One JavaScript source scanner for the suite: `js_function` and its spans.

`Law 20` option 2 — scope a JavaScript assertion to one function rather than
grepping the file — needs a way to cut one function out of a module. That way
is `js_function`, and until `B876` it lived as a private pair of functions at
the bottom of `tests/test_a_draft_skill_is_uncatalogued_not_inactive.py`, which
eight other test files imported by name.

**`B876`: it could not open the one function `B866`'s sweep was about.**
`js_function(escape_html_src, "export function esc")` raised
`unbalanced braces after 'export function esc'`. The old `_js_skip` knew about
`//`, `/* */`, `'`, `"` and `` ` `` and nothing else, so the `'` inside
`/[&<>"']/g` read as the start of a string; the scan ran from there to the next
apostrophe in the file and the closing brace of `esc` was inside the span it
skipped. The repository's own recommended way to scope an assertion could not
scope an assertion to the repository's own canonical escaper.

That is the same defect `B290` fixed in the comment blanker, one layer up, and
this module does not fix it a second way. `.pantheon/check-specifiers.py` is
this repository's one JavaScript scanner: `B84` wrote it, `B290` taught it
strings, template literals and regex literals, and
`tests/helpers/source_text.py` loads it rather than restating it. Two things
follow, and both are deliberate:

  * **Comments are not detected here at all.** `js_spans` runs on
    `blank_text(source)` — the checker's own output, offsets preserved — so a
    comment is already whitespace before this module looks at the text. There
    is no `//` branch below and no `/* */` branch below.
  * **Where a regex literal may begin is not decided here.**
    `REGEX_MAY_FOLLOW` and `KEYWORD_BEFORE_REGEX` are the checker's frozensets,
    imported, not copied. `tests/test_one_js_function_extractor.py` asserts they
    are the same objects, so teaching the checker a new keyword teaches this.

What is left in this file is the part the checker does not expose: it blanks
comments and returns text, and brace balance needs to know *where the literals
are*. `js_spans` returns those offsets.

Public names:

  ``js_spans(source)``
      Sorted, non-overlapping ``(start, end)`` half-open spans covering every
      byte of `source` that is not code: comments, string literals, regex
      literals, and the text chunks of template literals. The ``${`` and ``}``
      of a template substitution are *code*, so they balance, and the
      expression between them is scanned like any other code.
  ``js_skip(source, i, n, spans=None)``
      The single-step form the old private `_js_skip` had, kept because it is
      the readable way to say "step over one literal".
  ``js_function(source, signature)``
      The body of one function, braces balanced, literals skipped.
  ``js_code(source)``
      `source` with every non-code span blanked to spaces, newlines kept. For
      the assertions that want "does this word appear in code anywhere",
      `blank_text` only removes comments and this also removes string bodies.
"""
import bisect
import functools
import re

from tests.helpers.source_text import blank_text, checker

#: `B290`'s tables, loaded from the checker that owns them (`Law 14`).
REGEX_MAY_FOLLOW = checker._REGEX_MAY_FOLLOW
KEYWORD_BEFORE_REGEX = checker._KEYWORD_BEFORE_REGEX


def _end_of_quoted(text: str, i: int, n: int) -> int:
    """End of the `'`/`"` string opening at `i`.

    Ends at the matching quote **or at the newline it did not escape**, which
    is the checker's rule and the reason a stray quote costs one line rather
    than the rest of the file. A JavaScript string literal cannot hold a raw
    newline; one that appears to is an unterminated literal or, far more often,
    an apostrophe in text the scanner should never have been reading.
    """
    quote = text[i]
    j = i + 1
    while j < n and text[j] != quote and text[j] != "\n":
        j += 2 if text[j] == "\\" else 1
    return min(j + 1, n)


def _end_of_regex(text: str, i: int, n: int):
    """End of the regex literal opening at `i`, or `None` if it is division.

    `[` … `]` is a character class and a `/` inside one is a literal slash, so
    `/[/]/` is one regex and not two empty ones. A newline before the closing
    delimiter means this was never a regex — a regex literal cannot span lines
    — so the caller treats the `/` as an ordinary character. That is the safety
    valve that keeps a misread division cheap: it costs nothing, where the old
    scanner's misread quote cost the rest of the file.
    """
    j, in_class = i + 1, False
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            return j + 1
        elif c == "\n":
            return None
        j += 1
    return None


@functools.lru_cache(maxsize=64)
def js_spans(source: str):
    """Every ``(start, end)`` in `source` that is not code.

    Comments come from `blank_text` — the checker's blanker — so they are
    already whitespace when this walk begins and are reported as spans by
    comparing the blanked text against the original. Strings, regex literals
    and template text are found here, because the checker knows where they are
    and does not say.
    """
    n = len(source)
    blanked = blank_text(source, "js")
    spans = []

    # Comment spans, recovered from the blanker rather than re-detected: every
    # character the blanker changed was inside a comment, and nothing else in
    # `strip_comments` writes to the output.
    #
    # It blanks to spaces, so a space *inside* a comment is unchanged and the
    # raw run of differing characters splits `// note` into `//` and `note`.
    # Two runs are rejoined when everything between them is whitespace: there
    # is no code in such a gap, so joining can only ever be right, and it
    # keeps a span equal to the comment a reader would point at.
    runs = []
    start = None
    for k in range(n):
        if blanked[k] != source[k]:
            if start is None:
                start = k
        elif start is not None:
            runs.append((start, k))
            start = None
    if start is not None:
        runs.append((start, n))
    for a, b in runs:
        if spans and source[spans[-1][1]:a].strip() == "":
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))

    i = 0
    prev, word = "", ""      # last significant character; "w" stands for a word
    stack = []               # ["tpl", text-start] or ["expr", brace-depth]
    while i < n:
        ch = blanked[i]

        if stack and stack[-1][0] == "tpl":
            if ch == "\\":
                i += 2
            elif ch == "`":
                spans.append((stack.pop()[1], i + 1))
                prev, word = "`", ""
                i += 1
            elif ch == "$" and blanked[i + 1:i + 2] == "{":
                spans.append((stack[-1][1], i))
                stack[-1] = ["expr", 0]
                prev, word = "{", ""
                i += 2           # `${` stays code, so its `{` balances
            else:
                i += 1
            continue

        if ch in "\"'":
            end = _end_of_quoted(blanked, i, n)
            spans.append((i, end))
            prev, word = ch, ""
            i = end
            continue

        if ch == "`":
            stack.append(["tpl", i])
            i += 1
            continue

        if ch == "/" and (prev in REGEX_MAY_FOLLOW
                          or (prev == "w" and word in KEYWORD_BEFORE_REGEX)):
            end = _end_of_regex(blanked, i, n)
            if end is not None:
                spans.append((i, end))
                prev, word = "/", ""
                i = end
                continue

        if stack and stack[-1][0] == "expr":
            if ch == "{":
                stack[-1][1] += 1
            elif ch == "}":
                if stack[-1][1] == 0:
                    stack[-1] = ["tpl", i + 1]   # the `}` stays code
                    prev, word = "}", ""
                    i += 1
                    continue
                stack[-1][1] -= 1

        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (blanked[j].isalnum() or blanked[j] in "_$"):
                j += 1
            prev, word = "w", blanked[i:j]
            i = j
            continue

        if not ch.isspace():
            prev, word = ch, ""
        i += 1

    # An unterminated template literal at EOF: report what is left, so a caller
    # never walks into it looking for a brace.
    while stack:
        top = stack.pop()
        if top[0] == "tpl":
            spans.append((top[1], n))

    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return tuple(merged)


def js_skip(source: str, i: int, n: int = None, spans=None) -> int:
    """Step `i` past one comment, string, template chunk or regex literal.

    The signature the private `_js_skip` had, so the shape of a scan written
    against it still reads the same. `spans` is `js_spans(source)` when the
    caller already has it; computing it per character would be quadratic, which
    is why `js_function` below computes it once.
    """
    if spans is None:
        spans = js_spans(source)
    k = bisect.bisect_right(spans, (i, float("inf"))) - 1
    if k >= 0 and spans[k][0] <= i < spans[k][1]:
        return spans[k][1]
    return i


def js_code(source: str) -> str:
    """`source` with every non-code span blanked, newlines and offsets kept."""
    out = list(source)
    for a, b in js_spans(source):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "
    return "".join(out)


def _find_in_code(source: str, needle: str, spans) -> int:
    """The first offset of `needle` that is code, not comment and not string.

    The old helper used `source.index(signature)`, which opens whichever text
    comes first — and this repository's comments quote function signatures
    constantly. Same failure class as `Law 20`: the right string in the wrong
    place.
    """
    at = source.find(needle)
    while at >= 0:
        if not any(a <= at < b for a, b in spans):
            return at
        at = source.find(needle, at + 1)
    raise AssertionError(f"{needle!r} does not appear in code")


def js_function(source: str, signature: str) -> str:
    """The body of one JS function, resolved by brace balance from its
    signature, with comments, strings, template text and regex literals
    skipped.

    `Law 20` option 2. `skills.js` is 2,000 lines of code interleaved with
    prose about code and `memory.js` is 1,700 more; three separate defects in
    this repo's history were tests matching the right string in the wrong
    function, and `B41` was green while the handler it described raised on
    every call.

    The parameter list is stepped over before the body's `{` is looked for —
    `skillGateHints({ autoApprove = true })` destructures, so the first `{`
    after the signature is an argument and not a body. That was this helper's
    own first bug, found by it returning the parameter object.

    Its second was comments. `P8-25` measured that one on `static/js/tasks.js`:
    with every `'` read as a string delimiter, including the ones in
    `// the app's whirlpool`, `js_function(src, "function _wireActivityRows")`
    raised `unbalanced braces` — loud, and the only reason it was noticed —
    while `js_function(src, "function renderTriggerOpts")` returned a
    **1,434-line** body for a 190-line function. Balanced, plausible, and
    silently file-wide: a `Law 20` option-2 assertion made inside that scope is
    a file-wide grep wearing a scope's clothes.

    Its third was regex literals, and `B876` records what that one cost.

    Returns the body including its outer braces, sliced from the **original**
    source, so the text a caller asserts on is the text in the file.
    """
    spans = js_spans(source)
    n = len(source)

    sig_at = _find_in_code(source, signature, spans)
    i = _skip_to(source, sig_at, n, spans, "(")
    depth = 0
    while i < n:
        j = js_skip(source, i, n, spans)
        if j != i:
            i = j
            continue
        c = source[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    open_at = _skip_to(source, i, n, spans, "{")
    depth, i = 0, open_at
    while i < n:
        j = js_skip(source, i, n, spans)
        if j != i:
            i = j
            continue
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[open_at:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces after {signature!r}")


def js_definition(source: str, start: int) -> str:
    """The whole declaration beginning at offset `start`.

    `js_function` wants a `function` keyword and returns only the braces.
    An escaper in this tree is as often `const _esc = (s) => …` — an arrow with
    no braces at all, ending at the first `;` or newline outside any bracket —
    and `B874`'s sweep has to read both shapes. This returns the declaration
    *including* its name, from `start` to whichever end it has.

    Lifted out of `tests/test_one_html_escaper_js.py`, which grew its own
    scanner for it and its own regex-literal rule with it; that is the copy
    `B876` is about, in the file `B874` is about.
    """
    spans = js_spans(source)
    i, n = start, len(source)
    depth, seen_body = 0, False
    while i < n:
        j = js_skip(source, i, n, spans)
        if j != i:
            i = j
            continue
        c = source[i]
        if c in "{([":
            depth += 1
            if c == "{":
                seen_body = True
        elif c in "})]":
            depth -= 1
            if depth == 0 and seen_body and c == "}":
                return source[start:i + 1]
        elif depth == 0 and c in ";\n" and i > start:
            return source[start:i]
        i += 1
    raise AssertionError(f"unbalanced declaration at offset {start}")


def js_binding(source: str, name: str) -> str:
    """The whole `const`/`let`/`var NAME = …` declaration, by name.

    Used to lift a table a function depends on — `ESC_MAP` beside `esc` — so a
    stub can carry the shipped implementation rather than a copy of it.
    """
    spans = js_spans(source)
    pattern = re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+"
                         + re.escape(name) + r"\b", re.M)
    for m in pattern.finditer(source):
        if any(a <= m.start() < b for a, b in spans):
            continue
        return js_definition(source, m.start())
    raise AssertionError(f"no binding named {name!r} in code")


def _skip_to(source: str, i: int, n: int, spans, ch: str) -> int:
    """The first `ch` at or after `i` that is code."""
    while i < n:
        j = js_skip(source, i, n, spans)
        if j != i:
            i = j
            continue
        if source[i] == ch:
            return i
        i += 1
    raise AssertionError(f"no {ch!r} found in code")
