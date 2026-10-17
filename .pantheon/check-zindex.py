#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""check-zindex.py — every z-index in the product belongs to a named tier.

`P1-10`. The row asked to *"normalise z-index to 7 named tiers"* and measured
**259 declarations, 64 distinct values** in `static/style.css`, range −1 to
1,000,000. Re-measured 2026-10-17, and three of those four numbers had moved:

  * **355** hard-coded literals, not 259, and the scope is the reason — the row
    says *"`static/style.css` only"*, and **76** of them are not in it. They are
    in 29 files, `slashCommands.js` (12), `document.js` (6),
    `emailLibrary.js` (6), `notes.js` (5) and `settings.js` (5) among them.

    *That count was 349 until this file stopped blanking comments by hand.* The
    first draft carried `re.sub(r"/\*.*?\*/", ...)` plus a `//` rule, which is
    `B290`'s defect for the fourth time: it blanked live code in a dozen JS
    modules and hid **6** real sites, and under-reported the derived ones by 4.
    `tests/test_one_comment_blanker.py` failed it the same day. See
    `_strip_comments` below;
  * **74** distinct values;
  * range **−1 to 2,147,483,646** — `static/app.js`'s drop shield, two short of
    `INT32_MAX`, with `#toast.toast` at 2,147,483,000 just under it.

And one thing the row could not have known, which is the most useful fact here:
**64 further sites are already derived** rather than literal. `topPortalZ()`,
`nextToolWindowZ()` and `topToolWindowZ()` in `static/js/toolWindowZOrder.js`
read the live stack, so the top of the ladder is computed per open
window and cannot be written down. That is why the population is **430 sites,
355 of them literal** — and why a tier table alone can never be the whole
answer: the window stack's height is a runtime value.

**What this checker does, and what it deliberately does not.**

It partitions every literal into one of seven tiers plus `below`, which is not
a tier but the absence of one. The boundaries are the gaps the values already
form — 8→10, 48→50, 155→170, 500→1000, 9999→10000, 10500→12000 — so the table
describes the stylesheet rather than reorganising it. Nothing is renumbered:
a value that moves is a stacking change no one here can see, and the row's own
`Verify:` line is *"nothing moves visually"*.

So this is a **ratchet, not a remap** (`P3-20`: the ratchet is the value, not
the number). It fails when a literal lands outside every tier, and when a *new*
distinct value appears — a new magic number — while reusing an existing one is
free. Collapsing the 74 values onto 7 is the other half of `P1-10` and it needs
eyes: two elements that differ today would tie, and a tie is resolved by DOM
order, which `static/js/ui.js`'s own comment calls unpredictable.

**Why `top` has no ceiling.** `B1056` put the toast at 2,147,483,000 on purpose:
the modal bring-to-front counter climbs unbounded, so any finite literal is
eventually overtaken, and `tests/test_portal_dropdown_z_js.py` already forbids
the `100000` that was tried first (`#4720`). The honest fix is to bound the
counter — until then the nuclear value is the correct one, and this file says so
rather than flagging it.

    python3 .pantheon/check-zindex.py              # verify
    python3 .pantheon/check-zindex.py --report     # the full inventory
    python3 .pantheon/check-zindex.py --json

Exits 0 when every literal is in a tier and no new distinct value has appeared.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Vendored bundles are not ours to tier. `swagger-ui.css` alone carries 19.
VENDOR_PREFIX = ("static/lib/",)

#: A value produced by a shared helper or counter. These are sites, not
#: literals: the point of them is that no number is written down.
DERIVED = re.compile(
    r"topPortalZ\s*\(|nextToolWindowZ\s*\(|topToolWindowZ\s*\(|toolWindowZ\s*\(|_fxZ\b|_zCounter\b"
)

CONTEXT = re.compile(r"z-index|zIndex", re.I)
NUM = re.compile(r"-?\d+")

#: The seven tiers, plus `below`. Each is `(name, low, high, what it is for)`.
#: The boundaries are the gaps the existing values form, so this table reports
#: the stylesheet rather than rearranging it.
TIERS = (
    ("below",   -1,    -1,          "behind the content — a backdrop, a hit-target under everything"),
    ("base",     0,     8,          "in-flow layering inside one component"),
    ("raised",  10,    48,          "a raised part of a component — a handle, a badge, an overlay strip"),
    ("sticky",  50,   155,          "chrome that stays put — rails, sticky headers, the composer"),
    ("popover", 170,  500,          "anchored popovers and the modal base (`.modal` sits at 250)"),
    ("window", 1000,  9999,         "tool windows and dialogs, where the bring-to-front counter lives"),
    ("overlay", 10000, 10500,       "portaled above every window — dropdowns, dock chips, tour hints"),
    ("top",     12000, 2147483646,  "the toast and the drag shields, out of reach of the window counter"),
)

#: Every distinct literal in the tree on 2026-10-17, by tier. A value already
#: here may be reused anywhere; a value not here is a new magic number and fails.
#: This is the ratchet: the population cannot grow, and shrinking it needs no
#: edit here because the check is one-directional.
BASELINE = {
    "below":   (-1,),
    "base":    (0, 1, 2, 3, 4, 5, 6, 7, 8),
    "raised":  (10, 11, 12, 14, 18, 20, 25, 30, 40, 41, 48),
    "sticky":  (50, 60, 80, 100, 101, 120, 150, 155),
    "popover": (170, 200, 210, 240, 245, 250, 260, 261, 270, 280, 300, 304, 305, 390, 400, 500),
    "window":  (1000, 1001, 5000, 9000, 9998, 9999),
    "overlay": (10000, 10001, 10002, 10003, 10004, 10005, 10006, 10010, 10020,
                10030, 10031, 10050, 10060, 10100, 10500),
    "top":     (12000, 12050, 99998, 99999, 100000, 1000000, 2147483000, 2147483646),
}

#: Sites recorded on 2026-10-17, so a conversion to `topPortalZ()` shows up as
#: progress rather than as drift. Literals may fall; they may not rise.
BASELINE_LITERALS = 355
BASELINE_DERIVED = 64


#: The repository's one comment blanker, loaded rather than reimplemented.
#:
#: `B290`, and the first draft of this file was the fourth copy of the defect it
#: names: `re.sub(r"/\*.*?\*/", ...)` cannot tell a comment from a string, so
#: `input.accept = 'image/*,video/*'` in `static/js/gallery.js` opens a
#: "comment" that the next `*/` anywhere in the file closes — 7,277 lines of
#: live code across 15 modules, blanked. `tests/test_one_comment_blanker.py`
#: caught it the same day (`Law 14`), which is what that test is for.
#:
#: It blanks in place, so every offset and line number this file reports is the
#: line number in the file. `mode_for` picks js / css / html from the name, and
#: in `html` mode it blanks `<script>` bodies as JavaScript — so a `z-index`
#: written inline in markup is still a site, and only the comments around it go.
def _load_blanker():
    import importlib.util

    path = ROOT / ".pantheon" / "check-specifiers.py"
    spec = importlib.util.spec_from_file_location("_zindex_check_specifiers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BLANKER = _load_blanker()


def _strip_comments(text: str, path) -> str:
    """`text` with its comments replaced by spaces, offsets unchanged."""
    return _BLANKER.strip_comments(text, mode=_BLANKER.mode_for(Path(path)))


def sites_in(rel: str) -> list:
    """Every z-index site in one file, classified.

    Written against the *context* rather than against each spelling, because
    there are at least seven: `z-index: n`, `z-index:n !important`,
    `.style.zIndex = 'n'`, `= n`, `= String(expr)`, `setProperty('z-index', 'n',
    'important')`, and `style="z-index:n"` inside a template literal. Finding
    the word and then the first number after the separator covers all of them;
    enumerating the spellings is how one gets missed.
    """
    path = ROOT / rel
    raw = path.read_text(encoding="utf-8", errors="ignore")
    text = _strip_comments(raw, path)
    found = []
    for match in CONTEXT.finditer(text):
        tail = text[match.end():match.end() + 90]
        sep = re.match(r"\s*(?::|=(?!=)|'\s*,)", tail)
        if not sep:
            continue
        rest = tail[sep.end():]
        stop = re.search(r"[;}\n]|,\s*'important'", rest)
        window = (rest[:stop.start()] if stop else rest).strip()
        line = text[:match.start()].count("\n") + 1
        common = {"file": rel, "line": line, "text": window[:60]}
        if DERIVED.search(window):
            found.append({**common, "kind": "derived"})
        elif "var(" in window:
            found.append({**common, "kind": "var"})
        elif (number := NUM.search(window)) is None:
            # `transform`, `String(z)`, `''` — the property named beside another
            # or cleared. Not a value at all.
            found.append({**common, "kind": "none"})
        else:
            found.append({**common, "kind": "literal", "value": int(number.group(0)),
                          "important": bool(re.search(r"!\s*important|'important'", window))})
    return found


def population() -> list:
    out = []
    for path in sorted(ROOT.glob("static/**/*")):
        if not path.is_file() or path.suffix not in {".css", ".js", ".html"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in VENDOR_PREFIX):
            continue
        out.extend(sites_in(rel))
    return out


def tier_of(value: int):
    for name, low, high, _ in TIERS:
        if low <= value <= high:
            return name
    return None


def main() -> int:
    sites = population()
    literals = [s for s in sites if s["kind"] == "literal"]
    derived = [s for s in sites if s["kind"] == "derived"]
    values = collections.Counter(s["value"] for s in literals)

    if "--json" in sys.argv:
        print(json.dumps({"sites": sites, "tiers": [t[:3] for t in TIERS]},
                         indent=1, sort_keys=True))
        return 0

    print(f"z-index — {len(sites)} sites we own in "
          f"{len({s['file'] for s in sites})} files "
          f"({len(literals)} literal, {len(derived)} derived from the live stack, "
          f"{sum(1 for s in sites if s['kind'] == 'var')} var(), "
          f"{sum(1 for s in sites if s['kind'] == 'none')} not a value)\n")
    width = max(len(name) for name, *_ in TIERS)
    for name, low, high, what in TIERS:
        inside = sorted(v for v in values if low <= v <= high)
        print(f"  {name:<{width}}  {low:>6} … {high:<10}  "
              f"{len(inside):>2} values  {sum(values[v] for v in inside):>3} sites   {what}")

    problems = []

    orphans = sorted(v for v in values if tier_of(v) is None)
    if orphans:
        problems.append(f"{len(orphans)} value(s) in no tier: {orphans} — either "
                        f"they belong in a tier or a tier's range is wrong")

    for name, *_ in TIERS:
        known = set(BASELINE.get(name, ()))
        low, high = next((lo, hi) for n, lo, hi, _ in TIERS if n == name)
        fresh = sorted(v for v in values if low <= v <= high and v not in known)
        if fresh:
            problems.append(
                f"{name}: new magic number(s) {fresh} — pick a value the tier "
                f"already uses ({sorted(known)[:6]}…) or add it to BASELINE with "
                f"the reason it needs its own layer")

    if len(literals) > BASELINE_LITERALS:
        where = collections.Counter(s["file"] for s in literals)
        problems.append(
            f"{len(literals)} hard-coded literals, up from {BASELINE_LITERALS} — "
            f"the population may shrink, not grow. Heaviest: "
            f"{', '.join(f'{f} ({n})' for f, n in where.most_common(3))}")
    elif len(literals) < BASELINE_LITERALS:
        print(f"\n  literals {len(literals)} < baseline {BASELINE_LITERALS} — "
              f"{BASELINE_LITERALS - len(literals)} converted; lower BASELINE_LITERALS "
              f"to hold the gain")

    if "--report" in sys.argv:
        print("\n  every literal, by tier:")
        for name, low, high, _ in TIERS:
            rows = sorted((s for s in literals if low <= s["value"] <= high),
                          key=lambda s: (s["value"], s["file"], s["line"]))
            if not rows:
                continue
            print(f"\n    {name}")
            for s in rows:
                mark = " !important" if s["important"] else ""
                print(f"      {s['value']:>11}  {s['file']}:{s['line']}{mark}")

    if problems:
        print(f"\nz-index FAILED — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  E {problem}")
        return 1
    print(f"\nz-index OK — {len(literals)} literals, {len(values)} distinct, all "
          f"inside {len(TIERS) - 1} named tiers plus `below`, and no new magic number. "
          f"{len(derived)} further sites take their z from the live stack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
