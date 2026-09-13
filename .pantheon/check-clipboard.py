#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B59` — a copy button that silently does nothing on the deployment we ship for.

**The rule is about a failure, not about tidiness.** `navigator.clipboard` is
`undefined` outside a secure context, and `Law 17` calls plain `http` on a LAN
the normal way to reach this app. So `navigator.clipboard.writeText(x)` with no
fallback is not a style preference — it is a button that throws on the property
access, copies nothing, and says nothing, on the deployment shape this fork is
built for.

It was not hypothetical. `admin.js`'s API-token copy button was exactly that
shape, on the one control in the app that shows a token **once**.

**What counts as guarded.** A call site is fine if the code around it also
reaches `uiModule.copyText` — the one helper — or does its own `execCommand`
fallback. Either means somebody thought about the non-secure case. A bare
`isSecureContext` check does **not** count: it avoids the exception and still
leaves nothing on the clipboard, which is the same button doing nothing with
better manners.

**A ceiling, not a zero.** `B59` was filed saying three implementations; there
are far more, and a nineteen-file sweep belongs in its own change where the
diff can be read (`P1-15`'s reasoning, applied here). So this is a ratchet: the
number may fall and may never rise, which is what stops the next copy button
from being written the broken way while the backlog is worked down.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The one helper. Its own internals are the implementation the rule points at.
HELPER = "static/js/ui.js"

# `writeText` only. `navigator.clipboard.write([ClipboardItem])` copies an
# image, and `execCommand` cannot — there is no legacy path to fall back to,
# so the three image-copy sites in `editor/keyboard-shortcuts.js` are exempt
# by the shape of the problem rather than by a name in a list.
CALL = re.compile(r"navigator\s*\.\s*clipboard\s*\.\s*writeText\s*\(")
# Evidence that the non-secure path was considered, in the code around a call.
# `copyToClipboard` counts because it delegates to `copyText`; a site that
# prefers the helper and keeps a raw call for the case where `uiModule` is
# absent has considered this.
GUARDS = ("execCommand", "copyText", "copyToClipboard")
# How far to look. A copy handler is small; forty lines covers the ones in this
# tree with room to spare, and a wider window starts crediting a fallback that
# belongs to a different button.
WINDOW = 40


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "static/js"], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
    return [f for f in out if f.endswith(".js") and "/lib/" not in f]


def unguarded() -> list[tuple[str, int, str]]:
    found = []
    for rel in tracked():
        if rel == HELPER:
            continue
        try:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if not CALL.search(line):
                continue
            lo = max(0, i - WINDOW)
            hi = min(len(lines), i + WINDOW + 1)
            window = "\n".join(lines[lo:hi])
            if any(g in window for g in GUARDS):
                continue
            found.append((rel, i + 1, line.strip()[:90]))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0,
                    help="ceiling for unguarded clipboard calls (may fall, never rise)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    problems = unguarded()
    print(f"clipboard  call sites unguarded {len(problems)} (max {args.max})"
          f"  ·  helper {HELPER}")
    if problems and args.list:
        for rel, line, text in problems:
            print(f"    {rel}:{line}  {text}")
    if len(problems) > args.max:
        print()
        print("A clipboard call with no fallback is a button that does nothing over")
        print("plain http on a LAN — no exception a person sees, no message, no copy.")
        print(f"Use `uiModule.copyText` from {HELPER}, which tries the synchronous")
        print("path first so the copy happens inside the user's gesture.")
        for rel, line, text in problems:
            print(f"    {rel}:{line}  {text}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
