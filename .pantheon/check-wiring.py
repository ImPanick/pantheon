#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Count element lookups that resolve to nothing — the drift metric.

A backend with no caller and an element id with no markup are the same disease:
something was built and never wired, and nothing in CI noticed because nothing
was broken. This counts the JS half of it.

    python3 .pantheon/check-wiring.py            # report
    python3 .pantheon/check-wiring.py --max 78   # fail if it grew

Scope, stated so the number means something (Law 5): `getElementById("...")`
calls with a string literal, PLUS ids reached through a literal collection that
a lookup indexes or iterates; across tracked files under static/, excluding
static/lib; minus ids present in any tracked .html; minus ids the JS itself
creates at runtime via id="...", .id = "...", or setAttribute("id", ...).

THREE BLIND SPOTS, CLOSED 2026-09-07 BY `P3-15`, WHICH REQUIRED IT FIRST.

  1. **It scanned `static/js` only**, so `static/app.js` — 3,000 lines of the
     application's own wiring — and `static/sw.js` were never looked at. Two
     files, and adding them to the identical algorithm moved UNRESOLVED from 2
     to 6. A drift metric that does not read the biggest file is not a floor,
     it is a different number.

  2. **It did not strip comments.** Writing a sentence ABOUT a lookup made the
     checker count the sentence. That is not a hypothetical: documenting this
     very defect added a fourth unresolved id on 2026-08-30, which is the
     fourth time this project has had a checker read prose as code.

  3. **It matched only a STRING LITERAL argument**, so an id map indexed by a
     variable scored clean:

         const RAILS = { research: 'rail-research', gallery: 'rail-gallery' };
         el(RAILS[which]);            // invisible to the old check

     On 2026-08-30 exactly that shape hid the highest-harm finding in the
     discovery audit — the agent reporting that it had opened a panel with no
     button behind it. Literal collections are resolved now when the lookup
     indexes or iterates them; anything genuinely computed remains invisible and
     always will be. This is a floor on the drift, never a ceiling.
"""
import re
import signal
import sys
import pathlib
import subprocess
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent


def tracked(*globs):
    out = subprocess.run(["git", "ls-files", *globs], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
    return [f for f in out if "/lib/" not in f]


def read(f):
    try:
        return (ROOT / f).read_text(errors="replace")
    except OSError:
        return ""


# Comment stripping is a SCANNER, not a regex, and the first version proved why.
#
# `re.sub(r"/\*.*?\*/", "", src, flags=re.S)` looks obviously correct and ate
# **55% of `static/js/gallery.js`** — 144,034 characters down to 64,919 — because
# a `/*` inside a string literal opened a comment that ran to the next `*/`
# thousands of lines away. Every `id="..."` in the span vanished with it, so the
# checker reported 153 unresolved ids that are created three lines from where
# they are looked up. A stripper that silently removes half its input is exactly
# the defect this file exists to find, which is a fair thing to have to say
# about one's own fix.
#
# Regex literals are the hard part of doing this properly: `/` is division or
# the start of a pattern depending on what came before it. The rule below is the
# standard one — a regex may begin only where a value may not — and it is
# approximate. Being wrong costs a mis-scanned line; the alternative was being
# wrong by half a file.
_REGEX_MAY_START_AFTER = set("(,=:[!&|?{};+-*%~^<>") | {""}
_KEYWORD_BEFORE_REGEX = ("return", "typeof", "instanceof", "in", "of", "new",
                         "delete", "void", "case", "do", "else", "yield", "await")


def code_only(text: str) -> str:
    """`text` with comments blanked and everything else — strings, templates,
    regex literals — left exactly as it was. Newlines are preserved so line
    numbers do not move."""
    out = []
    i, n = 0, len(text)
    prev_significant = ""
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in text[i:j]))
            i = j
            continue
        if c in "'\"`":
            quote, j = c, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            prev_significant = quote
            i = j
            continue
        if c == "/" and _regex_starts_here(text, i, prev_significant):
            j, in_class = i + 1, False
            while j < n:
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    j += 1
                    break
                elif ch == "\n":
                    break
                j += 1
            out.append(text[i:j])
            prev_significant = "/"
            i = j
            continue
        out.append(c)
        if not c.isspace():
            prev_significant = c
        i += 1
    return "".join(out)


def _regex_starts_here(text: str, i: int, prev_significant: str) -> bool:
    """Is the `/` at `i` the start of a regex literal rather than division?"""
    if prev_significant in _REGEX_MAY_START_AFTER:
        return True
    head = text[max(0, i - 12):i]
    stripped = head.rstrip()
    return any(stripped.endswith(k) for k in _KEYWORD_BEFORE_REGEX)


# Candidates reached INDIRECTLY must look like ids, and in this codebase an
# element id is kebab-case with at least one hyphen. Without the hyphen the
# collection scan swept up menu labels — `Calendar`, `Controls`, `Done` — sitting
# in the same object as a real id. A direct `getElementById("Foo")` is still
# counted whatever it is spelled like: there the author said it was an id.
_ID_LIKE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
_COLLECTION = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([\[{])", re.M)
_LOOKUP_ANY = re.compile(r"(?:getElementById|\bel)\(\s*([^)]*?)\)")
_IS_LITERAL = re.compile(r"""['"][^'"]*['"]""")
# How far past an iteration's opening the lookup may be. A callback body, not a
# file: the point of the window is that the lookup belongs to THIS loop.
_ITERATION_WINDOW = 400


def _literal_span(text: str, start: int) -> str:
    """The source of the object/array literal opening at `start`, brace-matched.

    Brace matching rather than a regex, because `{ a: { b: 'x' } }` is common
    and a non-greedy match stops at the first `}` — which is how a checker
    reports a clean file and misses half of it.
    """
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            quote, i = c, i + 1
            while i < n and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:start + 4000]


def collection_ids(text: str) -> dict:
    """`{name: {id, ...}}` for every literal collection of id-shaped strings."""
    out = {}
    for m in _COLLECTION.finditer(text):
        name, brace_at = m.group(1), m.end(2) - 1
        body = _literal_span(text, brace_at)
        values = {v for v in re.findall(r"['\"]([^'\"\n]{4,})['\"]", body)
                  if _ID_LIKE.match(v)}
        if values:
            out.setdefault(name, set()).update(values)
    return out


def indirect_lookups(text: str) -> set:
    """Blind spot 3: ids reached through a collection a lookup uses.

    STRICT ON PURPOSE, and the first version was not.

    The obvious rule — "this file contains a computed lookup, so every literal
    collection in it counts" — took UNRESOLVED from 2 to 511 on the real tree,
    because it swept up model catalogues (`gpt-4o`, `claude-3-5-sonnet`), icon
    names and every other kebab-shaped string that shares a file with an
    `el(x)`. A drift ceiling that reports five hundred non-defects is worse than
    one that reports two: nobody reads it, and the real ones hide inside it.

    So a collection counts only when it is named AT the lookup:

        el(RAILS[which])                 # the name is in the argument
        RAILS.forEach(id => el(id))      # iterated, with a lookup in the body

    Anything genuinely computed — an id assembled from a template string, a
    value off the network — stays invisible, as the module docstring says.
    """
    collections = collection_ids(text)
    if not collections:
        return set()

    found = set()
    args = [a.strip() for a in _LOOKUP_ANY.findall(text)]
    computed = [a for a in args if a and not _IS_LITERAL.fullmatch(a)]
    for name, ids in collections.items():
        word = re.compile(rf"\b{re.escape(name)}\b")
        # 1. Named directly in a lookup's argument.
        if any(word.search(a) for a in computed):
            found |= ids
            continue
        # 2. Iterated, and the lookup inside that iteration uses the LOOP
        #    VARIABLE. "A lookup somewhere in the next 400 characters" was the
        #    second version and it still admitted `args: ["-y", "caldav-mcp"]`
        #    from an MCP preset table that happened to sit near one. Binding to
        #    the loop variable is what makes it an id rather than a string.
        for m in re.finditer(
                rf"\b{re.escape(name)}\b\s*\.\s*(?:forEach|map|flatMap)\s*\(\s*"
                rf"(?:\(\s*([\w$,\s]*)\s*\)|([\w$]+))\s*=>"
                rf"|for\s*\(\s*(?:const|let|var)?\s*([\w$]+)\s+of\s+{re.escape(name)}\b",
                text):
            params = next((g for g in m.groups() if g), "")
            names = [v.strip() for v in params.split(",") if v.strip()]
            if not names:
                continue
            window = text[m.end():m.end() + _ITERATION_WINDOW]
            if any(re.search(rf"\b{re.escape(v)}\b", a)
                   for a in _LOOKUP_ANY.findall(window) for v in names):
                found |= ids
                break
    return found


# Blind spot 4: the codebase does not call `getElementById` directly very
# often. It calls a one-line helper — `ui.el`, `admin.el`, `settings/dom.byId`,
# all three of which are `return document.getElementById(id)` and nothing else
# — and there are ~925 such call sites against ~1,100 direct ones. Scanning only
# the direct form therefore missed nearly half the wiring in the product, which
# is how `set-carddav-url/user/pass/save/msg` sat in `settings.js` referencing
# markup that does not exist anywhere: a loader filling five elements that were
# never built and a click handler bound to a button that is not there.
#
# `el(` is matched only with a STRING LITERAL argument, so `el(someVar)` stays
# out — those are the indirect lookups `indirect_lookups` handles, and sweeping
# them in here would resurrect the 511-false-positive version.
_LOOKUPS = (
    re.compile(r"getElementById\(\s*['\"]([A-Za-z0-9_-]+)['\"]"),
    re.compile(r"\bel\(\s*['\"]([A-Za-z0-9_-]+)['\"]\s*\)"),
    re.compile(r"\bbyId\(\s*['\"]([A-Za-z0-9_-]+)['\"]\s*\)"),
)


def main() -> int:
    limit = None
    if "--max" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--max") + 1])

    html_ids = set()
    for f in tracked("*.html"):
        html_ids |= set(re.findall(r'id="([^"]+)"', read(f)))

    # Blind spot 1: `static/app.js` and `static/sw.js` sat outside the scan.
    js_files = sorted(set(tracked("static/js")) | set(tracked("static/*.js")))
    sources = {f: code_only(read(f)) for f in js_files}
    blob = "\n".join(sources.values())
    made = set(re.findall(r"""id=\\?["']([A-Za-z0-9_-]+)""", blob))
    # An id built by concatenation or interpolation — `id="cmp-history-' + i`
    # or `id="cmp-history-${i}"` — never appears whole in the source, so the
    # literal lookup `getElementById('cmp-history-0')` read as unresolved. Both
    # forms leave the fixed part ending in a separator, which is the signal: a
    # `made` entry ending in `-` or `_` is a PREFIX, not an id. Length-gated at
    # four characters — three letters and a separator, the shortest prefix
    # anyone writes — so a stray `id="a-"` cannot make every id in the
    # product "known", which is how a ratchet stops measuring without
    # anyone editing the number.
    made_prefixes = tuple(sorted(
        {p for p in made if p.endswith(("-", "_")) and len(p) > 3}
        | {pre for pre in re.findall(r"""id=\\?["']([A-Za-z0-9_-]*)\$\{""", blob)
           if "-" in pre and len(pre) > 3}
    ))
    made |= set(re.findall(r"""\.id\s*=\s*['"]([A-Za-z0-9_-]+)['"]""", blob))
    made |= set(re.findall(r"""setAttribute\(\s*['"]id['"]\s*,\s*['"]([A-Za-z0-9_-]+)['"]""", blob))

    where = {}
    for f, text in sources.items():
        for pat in _LOOKUPS:
            for i in pat.findall(text):
                where.setdefault(i, set()).add(f)
        for i in indirect_lookups(text):
            where.setdefault(i, set()).add(f)

    looked = set(where)
    known = html_ids | made
    dead = sorted(i for i in looked - known
                  if len(i) > 3 and not i.startswith("__")
                  and not i.startswith(made_prefixes))

    print(f"lookups {len(looked)}  ·  in markup {len(looked & html_ids)}  ·  "
          f"made at runtime {len(looked & made - html_ids)}  ·  UNRESOLVED {len(dead)}")
    print()
    for prefix, n in Counter(d.split("-")[0] for d in dead).most_common():
        ids = [d for d in dead if d.split("-")[0] == prefix]
        print(f"  {n:>3}  {prefix + '-*':<14} {', '.join(sorted(ids)[:4])}"
              f"{' …' if len(ids) > 4 else ''}")

    if limit is None:
        return 0
    if len(dead) > limit:
        print(f"\nFAIL — {len(dead)} unresolved, ceiling is {limit}. Law 13: nothing ships "
              f"half-wired. Wire it, or do not merge the half.")
        return 1
    if len(dead) < limit:
        print(f"\n{len(dead)} unresolved, under the ceiling of {limit}. Lower the ceiling.")
    return 0


if __name__ == "__main__":
    # `| head` closes the pipe; that is not an error worth a traceback.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
