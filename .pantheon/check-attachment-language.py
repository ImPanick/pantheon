#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B161` — the browser and the server say the same word for the same file.

`B100` replaced the server's two hand-written lists — a 27-entry
``language_map`` for the ``[Type: …]`` label and a separate 24-entry
``code_extensions`` for the code fence — with one derivation:
``document_processor.attachment_language(name)``. A suffix **is** its language
unless it is not a word; ``LANGUAGE_ALIASES`` holds only the residues where that
is false, and the fence is ``language not in PROSE_LANGUAGES``.

The browser kept three copies of the old shape, in ``chat.js``,
``document.js`` and ``documentLibrary.js``, and none of them knew ``.toml``,
``.markdown``, ``.kt``, ``.swift`` or ``.h`` — so a file the composer labelled
``toml`` was offered as plain text by the document editor it opened in.

**The client cannot import a Python register**, which is why this file exists.
The rule is implemented once in JS (``static/js/attachmentLanguage.js``) and the
two registers it reads are **generated** from the Python ones; this checker is
what makes that safe. It asks three questions and derives both sides of each:

  1. **The generated block is what the generator would write today.** Byte for
     byte, from `src/document_processor.py`'s own AST. ``--write`` regenerates
     it, so the fix for a failure is one command and never a hand edit.

  2. **The rule itself agrees, not just the registers.** A second copy of a
     *list* is cheaper to keep true than a second copy of a *rule* only if
     something checks the rule, so every name in a swept set — every alias key,
     every ingestible extension, and the structural cases (no suffix, a bare
     dotfile, upper case, a suffix that is not a word, a suffix too long to be
     one) — is put through BOTH implementations and the answers compared. This
     is the half a generated constant does not give you.

  3. **`EDITOR_LANGUAGE` has not become a second language register.** The
     browser routes a handful of languages to the one its editor already has a
     mode and a toolbar for (``scss`` edits as ``css``). Every key must be a
     language the derivation can actually produce, and no key may name one the
     server would answer differently for the same file.

Question 2 needs node. Without it the answer is unknown rather than yes, and it
says so instead of passing quietly — the same thing `release-gate.py` does with
`node --check`.

Usage:  python3 .pantheon/check-attachment-language.py [--write] [--list]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "src" / "document_processor.py"
# `B232`. The extractor registers live with their extractors — one register per
# extractor is the rule ``INGESTIBLE_EXTS`` is stated as a union to keep — so
# the generator reads all three modules rather than a copy of them.
OFFICE_PY = ROOT / "src" / "markitdown_runtime.py"
PDF_PY = ROOT / "src" / "pdf_runtime.py"
JS = ROOT / "static" / "js" / "attachmentLanguage.js"

BEGIN = "// ---- generated from src/document_processor.py ----"
END = "// ---- end generated ----"


# ---------------------------------------------------------------------------
# side A — the Python registers, read out of the file rather than imported
# ---------------------------------------------------------------------------

def _literal(node: ast.AST):
    """`ast.literal_eval`, plus the one call form this module uses.

    ``PROSE_LANGUAGES = frozenset({...})`` is a Call, so `literal_eval` refuses
    it. Unwrapping exactly `frozenset(...)` and `set(...)` is narrower than
    importing the module, which would run it.
    """
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {"frozenset", "set"} and len(node.args) == 1):
        return set(ast.literal_eval(node.args[0]))
    return ast.literal_eval(node)


def _module_sets(path: Path, wanted: set[str]) -> dict:
    """Named literal sets and simple set unions of them, from one module's AST.

    ``OFFICE_EXTS = MARKITDOWN_EXTS | NATIVE_OFFICE_EXTS`` and
    ``INGESTIBLE_EXTS = TEXT_EXTS | OFFICE_EXTS | PDF_EXTS`` are the shape this
    project states its registers in on purpose — a union is an identity that
    cannot drift where a listed copy can — so a reader that only understands
    literals sees neither of them. Resolving `|` over names already read is the
    whole extension, and it is deliberately not an evaluator: anything else
    (a call, a comprehension, a name from another module) is skipped and the
    caller finds the key missing.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, object] = {}

    def resolve(node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            left, right = resolve(node.left), resolve(node.right)
            if left is None or right is None:
                return None
            return set(left) | set(right)
        if isinstance(node, ast.Name):
            value = out.get(node.id)
            return set(value) if isinstance(value, (set, frozenset, list)) else None
        try:
            return _literal(node)
        except (ValueError, SyntaxError, TypeError):
            return None

    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        value = resolve(node.value)
        if value is None:
            continue
        # Everything readable is kept while the walk runs, because a union names
        # its operands; only the wanted keys survive the filter below.
        out[name] = value
    return {k: v for k, v in out.items() if k in wanted}


def python_side() -> dict:
    tree = ast.parse(PY.read_text(encoding="utf-8"), filename=str(PY))
    out: dict[str, object] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        if name not in {"LANGUAGE_ALIASES", "PROSE_LANGUAGES", "TEXT_EXTS",
                        "INGESTIBLE_EXTS"}:
            continue
        try:
            out[name] = _literal(node.value)
        except (ValueError, SyntaxError, TypeError):
            pass
    # `B232`: the two extractor registers, from the modules that own them, and
    # the union chat ingest actually asks. ``INGESTIBLE_EXTS`` is a BinOp in
    # `document_processor.py` so the literal read above never saw it; it is
    # derived here from the same three operands the module derives it from,
    # which is what makes a drift between the browser's answer and the server's
    # impossible rather than unlikely.
    out.update(_module_sets(OFFICE_PY, {"OFFICE_EXTS"}))
    out.update(_module_sets(PDF_PY, {"PDF_EXTS"}))
    if out.get("TEXT_EXTS") and out.get("OFFICE_EXTS") and out.get("PDF_EXTS"):
        out["INGESTIBLE_EXTS"] = (set(out["TEXT_EXTS"]) | set(out["OFFICE_EXTS"])
                                  | set(out["PDF_EXTS"]))
    src = PY.read_text(encoding="utf-8")
    m = re.search(r"_LANGUAGE_TOKEN\s*=\s*re\.compile\(r\"([^\"]*)\"\)", src)
    out["token"] = m.group(1) if m else None
    return out


def _attachment_language(name: str, aliases: dict, token: str) -> str:
    """`document_processor.attachment_language`, reimplemented here on purpose.

    Importing the module would pull in `charset_normalizer` and the rest of the
    ingest stack for a nine-line rule, and a checker that cannot run without the
    app's dependencies is a checker CI skips. The identity with the shipped
    function is not assumed — `tests/test_attachment_language_is_one_answer.py`
    drives the real one over the same sweep.
    """
    import os.path
    lowered = (name or "").lower()
    _, ext = os.path.splitext(lowered)
    if not ext and lowered.startswith("."):
        ext = os.path.basename(lowered)
    if not ext:
        return "text"
    alias = aliases.get(ext)
    if alias:
        return alias
    tok = ext[1:]
    return tok if re.match(token, tok) else "text"


# ---------------------------------------------------------------------------
# the generated block
# ---------------------------------------------------------------------------

def _js_literal(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_block(side: dict) -> str:
    aliases: dict = side["LANGUAGE_ALIASES"]
    prose = sorted(side["PROSE_LANGUAGES"])
    lines = [BEGIN,
             "// Regenerate with:  python3 .pantheon/check-attachment-language.py --write",
             "// Hand edits here are reverted by the checker, which fails the gate first.",
             f"export const LANGUAGE_ALIASES = {{"]
    for ext, lang in aliases.items():
        lines.append(f"  {_js_literal(ext)}: {_js_literal(lang)},")
    lines.append("};")
    lines.append(f"export const PROSE_LANGUAGES = new Set({_js_literal(prose)});")
    lines.append(f"const LANGUAGE_TOKEN = /{side['token']}/;")
    # `B232`. The extractor registers, so the browser can ask WHICH door a file
    # goes through without keeping a list of its own. Sorted, because a set has
    # no order and a generated block that reshuffles is a diff nobody can read.
    for name in ("TEXT_EXTS", "OFFICE_EXTS", "PDF_EXTS", "INGESTIBLE_EXTS"):
        value = side.get(name)
        if value is None:
            continue
        lines.append(
            f"export const {name} = new Set({_js_literal(sorted(value))});")
    lines.append(END)
    return "\n".join(lines)


def current_block(text: str) -> str | None:
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        return None
    return text[start:end + len(END)]


# ---------------------------------------------------------------------------
# question 2 — the rule, driven in both languages
# ---------------------------------------------------------------------------

def sweep(side: dict) -> list[str]:
    """Every file name both implementations are asked about.

    Derived, never typed out: the alias keys are where the suffix is NOT the
    language, the ingestible extensions are every file the product will actually
    read, and the tail is the structural cases the rule has branches for.
    """
    exts = sorted(set(side["LANGUAGE_ALIASES"])
                  | set(side.get("INGESTIBLE_EXTS") or ())
                  | set(side.get("TEXT_EXTS") or ()))
    names = [f"notes{e}" for e in exts]
    names += [f"NOTES{e.upper()}" for e in exts]          # case
    names += [e for e in exts]                            # bare dotfile
    names += [
        "README",            # no suffix at all
        "archive.tar.gz",    # only the last suffix counts
        "notes.",            # a dot and nothing after it
        ".bashrc",           # dotfile whose name reads like a word
        "report.2024",       # a suffix that is not a word
        "x.verylongsuffix",  # a suffix too long to be one
        "a.c++", "a.f#",     # the two punctuation characters the token allows
        "a.TOML",            # the gap this row is named after
        "a.markdown", "a.kt", "a.swift", "a.h", "a.rst", "a.gradle",
        "dir/notes.py",      # a separator, which a browser File name never has
        "",                  # nothing at all
    ]
    return names


def js_answers(names: list[str]) -> dict[str, list[str]] | None:
    if not shutil.which("node"):
        return None
    script = (
        "import { attachmentLanguage, isProseLanguage } from '%s';\n"
        "const names = JSON.parse(process.argv[1]);\n"
        "console.log(JSON.stringify(Object.fromEntries(names.map(n => {\n"
        "  const l = attachmentLanguage(n);\n"
        "  return [n, [l, isProseLanguage(l)]];\n"
        "}))));" % JS
    )
    proc = subprocess.run(["node", "--input-type=module", "--eval", script,
                           "--", json.dumps(names)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "node failed")
    return json.loads(proc.stdout)


def editor_languages() -> dict[str, str]:
    """`EDITOR_LANGUAGE` read out of the JS with comments blanked (`B87`)."""
    text = JS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    m = re.search(r"\bconst\s+EDITOR_LANGUAGE\s*=\s*\{(.*?)\n\};", text, flags=re.S)
    if not m:
        return {}
    return dict(re.findall(r"""['"]?([\w+#.-]+)['"]?\s*:\s*['"]([^'"]*)['"]""",
                           m.group(1)))


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="regenerate the generated block in the JS module")
    ap.add_argument("--list", action="store_true",
                    help="print every swept name and the answer both sides give")
    args = ap.parse_args()

    problems: list[str] = []
    side = python_side()
    if not side.get("LANGUAGE_ALIASES") or not side.get("PROSE_LANGUAGES") \
            or not side.get("token"):
        print("src/document_processor.py: LANGUAGE_ALIASES / PROSE_LANGUAGES / "
              "_LANGUAGE_TOKEN could not be read — nothing to check against.")
        return 1

    text = JS.read_text(encoding="utf-8")
    want = render_block(side)
    have = current_block(text)

    if args.write:
        if have is None:
            print(f"{JS.relative_to(ROOT)}: no generated block to replace "
                  f"({BEGIN!r} … {END!r}).")
            return 1
        JS.write_text(text.replace(have, want, 1), encoding="utf-8")
        print(f"wrote {JS.relative_to(ROOT)}")
        return 0

    # 1 — the generated block
    if have is None:
        problems.append(
            f"{JS.relative_to(ROOT)}: the generated block is gone. It is the only "
            "thing keeping the browser's answer tied to the server's.")
    elif have != want:
        problems.append(
            f"{JS.relative_to(ROOT)}: the generated block is not what "
            "src/document_processor.py says today. Run "
            "`python3 .pantheon/check-attachment-language.py --write`.")

    # 2 — the rule, both sides, over a derived sweep
    names = sweep(side)
    checked = 0
    try:
        js = js_answers(names)
    except RuntimeError as exc:
        problems.append(f"{JS.relative_to(ROOT)}: will not load in node ({exc})")
        js = None
    if js is None and shutil.which("node"):
        pass
    elif js is None:
        print("  ! node is not on PATH — the RULE was not compared, only the "
              "registers. This is the half that catches a divergence the "
              "generated block cannot.")
    else:
        prose = set(side["PROSE_LANGUAGES"])
        for name in names:
            want_lang = _attachment_language(name, side["LANGUAGE_ALIASES"],
                                             side["token"])
            got = js.get(name)
            checked += 1
            if args.list:
                print(f"{name:<24} py={want_lang:<12} js={got}")
            if got is None:
                problems.append(f"the client answered nothing for {name!r}")
            elif got[0] != want_lang:
                problems.append(
                    f"{name!r}: the server says `{want_lang}` and the browser says "
                    f"`{got[0]}`. One of the two rules has drifted.")
            elif bool(got[1]) != (want_lang in prose):
                problems.append(
                    f"{name!r}: the two disagree about whether `{want_lang}` is "
                    "prose, which is the fence decision.")

    # 3 — the editor table is not a second language register
    producible = set()
    for ext in side["LANGUAGE_ALIASES"]:
        producible.add(_attachment_language(f"x{ext}", side["LANGUAGE_ALIASES"],
                                            side["token"]))
    for ext in (side.get("INGESTIBLE_EXTS") or ()):
        producible.add(_attachment_language(f"x{ext}", side["LANGUAGE_ALIASES"],
                                            side["token"]))
    editors = editor_languages()
    for key, value in editors.items():
        if key == value:
            problems.append(
                f"EDITOR_LANGUAGE maps `{key}` to itself — delete the entry.")
        if value in editors:
            problems.append(
                f"EDITOR_LANGUAGE maps `{key}` to `{value}`, which is itself a key. "
                "One hop only; a chain is a register pretending to be a table.")
        if key in side["LANGUAGE_ALIASES"].values():
            problems.append(
                f"EDITOR_LANGUAGE has `{key}`, which is an alias target — the "
                "server already decided that one, and overriding it here is the "
                "second answer this file exists to prevent.")

    print(f"aliases {len(side['LANGUAGE_ALIASES'])}  ·  prose "
          f"{len(side['PROSE_LANGUAGES'])}  ·  names compared {checked}  ·  "
          f"editor routes {len(editors)}  ·  PROBLEMS {len(problems)}")
    for p in problems:
        print(f"  {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
