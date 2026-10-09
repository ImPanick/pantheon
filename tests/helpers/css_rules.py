# SPDX-License-Identifier: AGPL-3.0-or-later
r"""One CSS rule walker for the suite: `css_rules` and `decl`.

`Law 20` option 2 — a stylesheet cannot be driven under node, so a claim about
the cascade is made by *finding the rule first and asserting inside it*. The
suite has two shapes for that and they are not equal:

  * `tests/test_one_focus_ring_css.py` matches innermost rules with
    `([^{}]+)\{([^{}]*)\}`. It needs no brace balancing and it is the shape to
    copy whenever the enclosing at-rule does not matter.
  * when it does matter — "which container query drops this control" — the
    at-rule's prelude has to come back with the rule, and 28 test files have
    each written their own walk to get it. `tests/test_one_js_function_extractor
    .py`'s `STILL_BALANCES_BY_HAND` is the list; its own docstring calls each
    one a real site and a separate row.

`fx8-census` is the row that made it one. `D-2026-10-09-01` §4 wrote the
twenty-ninth copy in `tests/test_the_phone_can_reach_what_the_turn_does.py`,
whose docstring said it followed the focus-ring shape and did not, and
`test_no_new_hand_rolled_js_function_cutter_appears` caught it — which is what
that tripwire is for (`B87` → `B230` → `B310` for the comment blanker,
`P8-25` → `B290` → `B876` for the function cutter: each fix was right and none
of them stopped the next copy, because the walk looks obviously right when you
write it). So the walk lives here once, and this module is the exempt owner of
the job the way `tests/helpers/js_source.py` is the exempt owner of cutting a
JavaScript function out of a module.

**What this is not.** It is not a CSS parser. It balances braces over text whose
comments are already gone — callers pass `tests.helpers.source_text.blank(path)`
— and it checks the one premise that a brace walk over a stylesheet needs
rather than assuming it: that no string literal in the sheet contains a brace.
Measured on `static/style.css`, 2026-10-09: none does, across 49,257 lines. A
sheet where one did would make this walk wrong silently, so it raises instead.
"""
import re

#: A quoted string in CSS. `url()` without quotes cannot hold a brace.
_QUOTED = re.compile(r"""(['"])((?:[^\\\n]|\\.)*?)\1""")


def _check_premise(css: str) -> None:
    for m in _QUOTED.finditer(css):
        if "{" in m.group(2) or "}" in m.group(2):
            raise AssertionError(
                "a string literal in this stylesheet contains a brace "
                f"({m.group(0)!r} at line {css.count(chr(10), 0, m.start()) + 1}), "
                "so balancing braces over the text is not safe — teach this "
                "walker the literal rather than reading past it (`B290`).")


def css_rules(css: str, _depth: int = 0) -> list:
    """`(selector, body)` for every innermost rule, at-rules walked into.

    A rule inside an at-rule comes back with the at-rule's prelude on the
    front, as ``"@container chatbar (max-width: 420px) { .mode-toggle"``, so a
    caller can ask *which* query a declaration is in and `"@" not in selector`
    means unconditional. Nesting is followed to any depth.
    """
    if not _depth:
        _check_premise(css)
    out, i, n = [], 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace < 0:
            break
        selector = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        if depth:
            raise AssertionError(f"unbalanced braces after {selector[:60]!r}")
        body = css[brace + 1:j - 1]
        if selector.startswith("@") and "{" in body:
            out.extend((f"{selector} {{ {sel}", sub)
                        for sel, sub in css_rules(body, _depth + 1))
        else:
            out.append((selector, body))
        i = j
    return out


def decl(body: str, prop: str):
    """The value of `prop` in one rule body, or `None`.

    Anchored on a declaration boundary, so `outline-offset` can never answer
    for `outline` (`tests/test_one_focus_ring_css.py`'s rule, lifted).
    """
    m = re.search(rf"(?:^|[{{;])\s*{re.escape(prop)}\s*:\s*([^;}}]+)", body, re.M)
    return m.group(1).strip() if m else None
