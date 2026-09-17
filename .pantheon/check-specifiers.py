#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Count modules imported under more than one URL — the accidental-fork metric.

ES module identity is keyed on the RESOLVED URL, query string included, and this
tree has no import map. So `./tasks.js` and `./js/tasks.js?v=20260723…` are two
different modules. The browser instantiates both, each with its own copy of every
module-level variable, and neither knows the other exists.

Nothing breaks loudly when this happens. A registry populated through one
specifier is simply empty when read through the other, and the feature that
depended on it does nothing — quietly, forever. That is Law 14's failure mode
arrived at by accident: a second scaffolding nobody chose to build.

    python3 .pantheon/check-specifiers.py           # report
    python3 .pantheon/check-specifiers.py --max 0   # fail if any module forks

Scope, stated so the number means something (Law 5): every static `import … from
'…'`, dynamic `import('…')`, `<script src="…">`, `<link rel="…preload" href="…">`
and service-worker precache entry in tracked `.js` and `.html` files under
`static/`, excluding `static/lib/`. Specifiers are resolved relative to the
importing file and compared by path; a module counts as forked when the same
path is reached under two or more distinct query strings (a bare import and a
versioned one are two). Absolute `http(s)://` and protocol-relative URLs are out
of scope — they are not this tree's modules.

**The last two entered scope on 2026-09-14 (`B58`, absorbing `B09`), and this
checker reported `FORKED 0` until they did.** The rule was already right; it was
looking at four of the six places a URL is written. Widening it found four
forked assets that had been there the whole time:

  * `static/js/chat.js` — preloaded at `?v=20260815toolapproval4` and executed
    at `?v=20260829trustladder1`. The HTTP cache and the module map are keyed on
    the full URL, query included, so the second-largest module in the shell
    (372 KB) was fetched **twice on every cold load**, both on the critical
    path. `git log -L` says the preload line has not been edited since the fork
    baseline while the script tag has been bumped twice — the bump happened
    twice without anybody knowing the second copy existed.
  * `admin.js`, `emailInbox.js`, `sidebar-layout.js` — precached bare in
    `static/sw.js` and imported with a version. `sw.js`'s fetch handler matches
    with `cache.match(e.request)` and **no `ignoreSearch`**, so those three
    entries were downloaded at install and could never be served to anything.
    That is the third recurrence of the defect `P3-11` closed eight of and
    `B54` closed nine of, and no row had named it.

`FORBIDDEN.md`'s own cache-buster control could not have caught the first:
`tests/test_tool_approval_frontend_routing.py` asserts the version string is a
**substring** of `index.html`, and it is — at line 3256. A substring test cannot
see a *second* copy under a different string. Only a set comparison can, which
is the argument for widening this file rather than adding an assertion there.
"""
import collections
import pathlib
import re
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

IMPORT_RE = re.compile(
    r"""(?:^|[^\w.])(?:import\s*\(?\s*|from\s+)['"]([^'"]+\.js(?:\?[^'"]*)?)['"]"""
)
SCRIPT_RE = re.compile(r"""<script[^>]*\ssrc=["']([^"']+\.js(?:\?[^"']*)?)["']""")
# `B58`. A `modulepreload` opens a real request for a real URL; a stale one is a
# second copy of the module fetched and thrown away.
LINK_RE = re.compile(
    r"""<link[^>]*\srel=["'](?:module)?preload["'][^>]*\shref=["']([^"']+\.js(?:\?[^"']*)?)["']"""
)
LINK_REV_RE = re.compile(
    r"""<link[^>]*\shref=["']([^"']+\.js(?:\?[^"']*)?)["'][^>]*\srel=["'](?:module)?preload["']"""
)
# `B58`. The service worker's precache list is a list of URLs it will fetch and
# then try to serve — and its fetch handler matches without `ignoreSearch`, so an
# entry whose query does not match the importer's is downloaded and never used.
PRECACHE_RE = re.compile(r"""["'](/static/[^"']+\.js(?:\?[^"']*)?)["']""")


def tracked():
    out = subprocess.run(["git", "ls-files", "static"], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
    return [f for f in out
            if f.endswith((".js", ".html")) and not f.startswith("static/lib/")]


def resolve(importer: str, spec: str):
    """Return the repo-relative path a specifier points at, or None if out of scope."""
    if spec.startswith(("http://", "https://", "//")):
        return None
    path, _, _query = spec.partition("?")
    if path.startswith("/"):
        resolved = path.lstrip("/")
    else:
        base = pathlib.PurePosixPath(importer).parent
        resolved = (base / path).as_posix()
        while "/../" in resolved:
            resolved = re.sub(r"[^/]+/\.\./", "", resolved, count=1)
        resolved = resolved.replace("./", "")
    if "static/lib/" in resolved:
        return None
    return resolved


# `B290`. A regex literal may begin only where a *value* may not, and this is
# the standard approximation of that rule: the character before it, or the
# keyword before it. Being wrong here costs one mis-scanned line; the naive
# alternative was being wrong by half a file.
_REGEX_MAY_FOLLOW = frozenset("=(,:[!&|?{};+-*%<>~^") | {""}
_KEYWORD_BEFORE_REGEX = frozenset((
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await",
))
_EMBED_OPEN = re.compile(r"<(script|style)\b[^>]*>", re.I)


def mode_for(path) -> str:
    """The blanker mode for a file name: `js`, `css` or `html`.

    `.mjs`, `.cjs` and `.ts` read as JavaScript. Anything unrecognised reads as
    `js`, which is the strictest of the three — it blanks the most — so an
    unknown extension over-reports rather than silently under-scanning.
    """
    name = str(path).lower()
    if name.endswith((".html", ".htm", ".svg", ".xml")):
        return "html"
    if name.endswith(".css"):
        return "css"
    return "js"


def strip_comments(text: str, html: bool = False, *, mode: str = "",
                   embedded: bool = True) -> str:
    """Blank out comments so a *sentence about* a thing is not the thing.

    This is **the** comment blanker for this repository. Every census that has
    to ignore commented-out source calls it — the checkers here and, through
    `tests/helpers/source_text.py`, the test suite. Do not write a second one
    (`Law 14`); the reason is the whole of `B290`.

    `mode` is `js`, `css` or `html`; `mode_for(path)` picks it from a file name.
    `html=True` is the old spelling of `mode="html"` and still works.

      * `js`   — `//` and `/* … */`, with string, template and regex literals
                 tracked so none of them can open a comment.
      * `css`  — `/* … */` only. `//` is **not** a comment in CSS, and blanking
                 from one eats the rest of `url(http://…)`.
      * `html` — `<!-- … -->`, with `<script>` and `<style>` bodies blanked as
                 JavaScript and CSS. Pass `embedded=False` to leave those bodies
                 byte-identical — `tests/test_app_shell_csp_hashes.py` hashes
                 them for the CSP and a blanked comment would change the hash.

    Characters are replaced with spaces rather than deleted so every offset and
    line number downstream is unchanged: a line number a census reports is the
    line number in the file.

    `B84` built the first version of this because a docstring in
    `static/js/runStatus.js` explaining why a module is loaded as
    `import('./tasks.js?v=…')` was counted as a second specifier for `tasks.js`
    — `Law 20` in the checker itself.

    `B290` made it the only one and taught it two things its callers' copies
    did not know. **Strings**: `re.sub(r"/\\*.*?\\*/", "", flags=re.S)` cannot
    tell a comment from a string, so `input.accept = 'image/*,video/*'` at
    `static/js/gallery.js:1202` opens a "comment" that the next `*/` anywhere
    in the file closes — measured over `static/js/**`, that substitution blanks
    **7,277 lines that hold live code across 15 modules**, and every census
    built on it was measuring a smaller tree than it claimed. **Regex
    literals**: `/["']/` is a pattern, not a quote, and a blanker that reads
    the `"` as opening a string stops blanking comments from there to the next
    `"` in the file — the same defect with the sign flipped, a census that
    counts commented-out code as live.
    """
    mode = mode or ("html" if html else "js")
    if mode not in ("js", "css", "html"):
        raise ValueError(f"mode must be js, css or html, not {mode!r}")
    out = list(text)
    i, n = 0, len(text)
    stack = []          # "tpl", or ["expr", brace-depth] inside a `${…}`
    in_tag = False      # html: between `<name` and the `>` that closes it
    prev = ""           # last significant character; "w" stands for a word
    word = ""           # that word, for `return /…/` and friends

    def wipe(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        ch = text[i]

        # Inside a template literal body: only a backtick or a `${` gets out.
        if stack and stack[-1][0] == "tpl":
            if ch == "\\":
                i += 2
            elif ch == "`":
                stack.pop()
                prev, word = "`", ""
                i += 1
            elif ch == "$" and text[i + 1:i + 2] == "{":
                stack.append(["expr", 0])
                prev, word = "{", ""
                i += 2
            else:
                i += 1
            continue

        # A quoted string ends at its quote or at the newline it did not
        # escape, so an apostrophe in prose costs one line, not a file.
        # In HTML only an attribute value is quoted, so `don't` in a paragraph
        # is text — the old blanker read it as opening a string and stopped
        # blanking comments from there on.
        if ch in "\"'" and (mode != "html" or in_tag):
            quote = ch
            i += 1
            while i < n and text[i] != quote and text[i] != "\n":
                i += 2 if text[i] == "\\" else 1
            i += 1
            prev, word = quote, ""
            continue

        if mode != "css" and ch == "`":
            stack.append(["tpl", 0])
            i += 1
            continue

        if mode == "html":
            if text.startswith("<!--", i):
                end = text.find("-->", i + 4)
                end = n if end < 0 else end + 3
                wipe(i, end)
                i = end
                continue
            if in_tag:
                if ch == ">":
                    in_tag = False
                i += 1
                continue
            embed = _EMBED_OPEN.match(text, i)
            if embed and not embedded:
                # Leave the body exactly as it is, and do not read an html
                # comment out of it either.
                close = re.compile(r"</\s*" + embed.group(1), re.I).search(
                    text, embed.end())
                i = close.start() if close else n
                continue
            if embed:
                # A `<script>` body is JavaScript and a `<style>` body is CSS.
                # Blank them as such: an import inside `/* … */` in an inline
                # script is commented out, and a census must not count it.
                body_start = embed.end()
                close = re.compile(r"</\s*" + embed.group(1), re.I).search(text, body_start)
                body_end = close.start() if close else n
                inner = strip_comments(text[body_start:body_end],
                                       mode="css" if embed.group(1).lower() == "style" else "js")
                out[body_start:body_end] = list(inner)
                i = body_end
                continue
            if (ch == "<" and text[i + 1:i + 2].isalpha()) or text.startswith("</", i):
                in_tag = True
            i += 1
            continue
        else:
            if mode == "js" and text.startswith("//", i):
                end = text.find("\n", i)
                end = n if end < 0 else end
                wipe(i, end)
                i = end
                continue
            if text.startswith("/*", i):
                end = text.find("*/", i + 2)
                end = n if end < 0 else end + 2
                wipe(i, end)
                i = end
                continue
            if (mode == "js" and ch == "/"
                    and (prev in _REGEX_MAY_FOLLOW
                         or (prev == "w" and word in _KEYWORD_BEFORE_REGEX))):
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
                        j += 1
                        break
                    elif c == "\n":
                        break
                    j += 1
                i = j
                prev, word = "/", ""
                continue

        if stack and stack[-1][0] == "expr":
            if ch == "{":
                stack[-1][1] += 1
            elif ch == "}":
                if stack[-1][1] == 0:
                    stack.pop()         # back into the template body
                    prev, word = "}", ""
                    i += 1
                    continue
                stack[-1][1] -= 1

        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            prev, word = "w", text[i:j]
            i = j
            continue

        if not ch.isspace():
            prev, word = ch, ""
        i += 1
    return "".join(out)


def scan():
    """path -> {query: [importer, ...]}. A bare import has query ''."""
    seen = collections.defaultdict(lambda: collections.defaultdict(list))
    for f in tracked():
        text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        text = strip_comments(text, html=f.endswith(".html"))
        matches = (list(IMPORT_RE.finditer(text))
                   + list(SCRIPT_RE.finditer(text))
                   + list(LINK_RE.finditer(text))
                   + list(LINK_REV_RE.finditer(text)))
        if f.endswith("sw.js"):
            matches += list(PRECACHE_RE.finditer(text))
        for m in matches:
            spec = m.group(1)
            path = resolve(f, spec)
            if path is None:
                continue
            _, _, query = spec.partition("?")
            seen[path][query].append(f)
    return seen


def main() -> int:
    limit = None
    if "--max" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--max") + 1])

    seen = scan()
    forked = {p: q for p, q in seen.items() if len(q) > 1}
    total_specs = sum(len(q) for q in seen.values())

    print(f"modules {len(seen)}  ·  specifiers {total_specs}  ·  FORKED {len(forked)}")
    if forked:
        print()
        for path in sorted(forked):
            print(f"    {path}")
            for query in sorted(forked[path]):
                label = "(bare)" if not query else "?" + query
                where = ", ".join(sorted(set(forked[path][query])))
                print(f"        {label:<34} {where}")

    if limit is not None and len(forked) > limit:
        print(f"\nFAIL: {len(forked)} forked, ceiling is {limit}.")
        print("Every listed module is instantiated twice in the browser, with two")
        print("copies of its state. Pick ONE specifier per module and use it everywhere.")
        return 1
    return 0


if __name__ == "__main__":
    # `| head` closes the pipe; not an error worth a traceback.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
