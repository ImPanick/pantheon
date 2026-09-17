# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`B161` — the browser and the server say the same word for the same file.

**Measured before the change** (2026-09-16, by reading the four maps and driving
`document_processor.attachment_language` beside them)::

    .toml       server toml      chat.js —      document.js toml   library toml
    .markdown   server markdown  chat.js —      document.js —      library —
    .kt         server kotlin    chat.js —      document.js —      library —
    .swift      server swift     chat.js —      document.js —      library —
    .h          server c         chat.js —      document.js c      library c
    .rst        server rst       chat.js —      document.js —      library —
    .gradle     server gradle    chat.js —      document.js —      library —
    .ipynb      server json      chat.js —      document.js —      library —

Four maps, not three. `B161` names `chat.js`'s import banner (21 entries),
`document.js`'s *Import from device* (36) and `documentLibrary.js`'s library
import (40); `chat.js` had a **fourth**, `_attachLang` (29 entries), on the path
that opens an attachment as a document — and it was the only one that knew
`.markdown` and `.cs` while being the only one that did not know `.toml`,
`.ini`, `.log` or `.tsv`. So the same bytes could get four different languages
depending on which button opened them.

**What this file asserts, and in which of the two ways.** The agreement is
DRIVEN: the real `attachment_language` in Python and the real
`attachmentLanguage.js` in node are asked the same 150-odd names and their
answers compared, and the real `libraryImportFiles` is run against a stubbed
`fetch` so the language a document is actually stored with is read off the
request. The absence of a fifth map is a claim about SOURCE, so it is made
against source with comments blanked (`B87`, `Law 20`) — every module in this
area documents the map it used to own.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness" / "attachment_language.js"
JS = ROOT / "static" / "js" / "attachmentLanguage.js"
CHECKER = ROOT / ".pantheon" / "check-attachment-language.py"
CLIENT = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _h(mode: str, *args):
    proc = subprocess.run(["node", str(HARNESS), mode, *args],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _blank(src: str) -> str:
    """Comments out, newlines kept so line numbers still mean something."""
    return blank_text(src)


def _client_modules() -> list[Path]:
    return sorted(p for p in CLIENT.rglob("*.js")
                  if "static/lib/" not in p.as_posix())


def _sweep() -> list[str]:
    """Every name both sides are asked about. Derived from the server's own
    registers — typing a list here would be the fifth copy."""
    from src.document_processor import INGESTIBLE_EXTS, LANGUAGE_ALIASES

    exts = sorted(set(LANGUAGE_ALIASES) | set(INGESTIBLE_EXTS))
    names = [f"notes{e}" for e in exts]
    names += [f"NOTES{e.upper()}" for e in exts]
    names += list(exts)
    names += ["README", "archive.tar.gz", "notes.", ".bashrc", "report.2024",
              "x.verylongsuffix", "a.c++", "a.f#", "dir/notes.py", ""]
    return names


# ---------------------------------------------------------------------------
# the two implementations, driven
# ---------------------------------------------------------------------------

def test_the_browser_and_the_server_answer_the_same_word():
    """`B161`'s `Verify`. Both real functions, over a sweep derived from the
    server's registers rather than written out — so the day an alias is added
    the sweep covers it without this file being touched."""
    from src.document_processor import PROSE_LANGUAGES, attachment_language

    names = _sweep()
    out = _h("answer", json.dumps(names))["answers"]
    mismatches = []
    for name in names:
        want = attachment_language(name)
        got = out[name]
        if got["language"] != want:
            mismatches.append(f"{name!r}: server {want!r}, browser {got['language']!r}")
        elif got["prose"] != (want in PROSE_LANGUAGES):
            mismatches.append(f"{name!r}: the two disagree about prose for {want!r}")
    assert not mismatches, "\n".join(mismatches)
    # The six the row is named after, stated as facts rather than left implicit
    # inside the sweep — and asked of BOTH sides, by name.
    named = ["config.toml", "notes.markdown", "Main.kt", "App.swift",
             "list.h", "build.gradle"]
    got = _h("answer", json.dumps(named))["answers"]
    for name, want in zip(named, ["toml", "markdown", "kotlin", "swift", "c", "gradle"]):
        assert attachment_language(name) == want, name
        assert got[name]["language"] == want, (name, got[name])


def test_the_registers_in_the_browser_are_the_registers_in_python():
    """The generated half. Read out of the evaluated module, not out of the
    file, so a block that is present but unreachable would still fail."""
    from src.document_processor import LANGUAGE_ALIASES, PROSE_LANGUAGES

    out = _h("answer", "[]")
    assert out["aliases"] == dict(LANGUAGE_ALIASES)
    assert sorted(out["prose"]) == sorted(PROSE_LANGUAGES)


def test_prose_is_the_empty_language_and_nothing_else_is():
    """What all three client maps meant by mapping `.txt` and `.log` to `''`,
    kept exactly (`Law 1`) and now derived from `PROSE_LANGUAGES` — the same set
    that decides the server's code fence."""
    out = _h("answer", json.dumps(["a.txt", "a.log", "a.text", "README", "a.toml",
                                   "a.py", "a.markdown"]))["answers"]
    assert out["a.txt"]["document"] == ""
    assert out["a.log"]["document"] == ""
    assert out["a.text"]["document"] == ""
    assert out["README"]["document"] == ""
    assert out["a.toml"]["document"] == "toml"
    assert out["a.py"]["document"] == "python"
    assert out["a.markdown"]["document"] == "markdown"


# ---------------------------------------------------------------------------
# the call sites, driven
# ---------------------------------------------------------------------------

def test_a_library_import_stores_the_language_the_server_would_have_named():
    """The real `libraryImportFiles`, run against a stubbed `fetch`. The largest
    of the four maps lived inside this function; what matters is not that it is
    gone but that the request it builds now carries the server's answer."""
    from src.document_processor import attachment_language

    names = ["a.toml", "a.markdown", "a.kt", "a.swift", "a.h", "a.txt", "a.py"]
    posted = _h("library", json.dumps(names))
    by_name = {p["name"]: p for p in posted}
    for name in names:
        want = attachment_language(name)
        want = "" if want in {"text", "log"} else want
        assert by_name[name]["language"] == want, by_name[name]


def test_a_converted_file_is_labelled_with_what_it_became():
    """`Law 1`. `.docx` goes through mammoth and lands as markdown, so its
    language describes the conversion and not the file — the one thing the old
    map knew that the server cannot. The spreadsheet branch writes `csv` itself
    and never consulted the map, which is why `.xlsx` needs no entry."""
    posted = {p["name"]: p for p in _h("library", json.dumps(["a.docx", "a.xlsx"]))}
    assert posted["a.docx"]["language"] == "markdown"
    assert posted["a.xlsx"]["language"] == "csv"


def test_the_editor_keeps_every_mode_it_had():
    """`Law 1`, the other direction. `.scss` is `scss` to the server and the
    browser's editor has a CSS mode and no SCSS one, so the document is still
    stored as `css` — routed, not relabelled. Asserted against `document.js`'s
    own capability lists, read out of the file, so an entry that stops earning
    its place fails here."""
    src = _blank((CLIENT / "document.js").read_text(encoding="utf-8"))
    known = set(re.findall(r"'([a-z0-9+#]+)'", " ".join(
        re.findall(r"return \[\n?(.*?)\]\.includes\(lang\)", src, flags=re.S)
        + re.findall(r"const renderable = \[(.*?)\];", src, flags=re.S))))
    assert {"css", "ini", "csv", "html"} <= known, known
    out = _h("answer", json.dumps(["a.scss", "a.sass", "a.less", "a.cfg",
                                   "a.conf", "a.tsv", "a.vue", "a.svelte"]))["answers"]
    for name, family in [("a.scss", "css"), ("a.sass", "css"), ("a.less", "css"),
                         ("a.cfg", "ini"), ("a.conf", "ini"), ("a.tsv", "csv"),
                         ("a.vue", "html"), ("a.svelte", "html")]:
        assert out[name]["document"] == family, (name, out[name])
        assert out[name]["language"] != family, (
            f"{name}: the server's word and the editor's mode must stay distinct")
        assert family in known, f"{family} is not a mode document.js has"


# ---------------------------------------------------------------------------
# no fifth map (`Law 14`), asserted against source with comments blanked
# ---------------------------------------------------------------------------

_EXT_KEY = re.compile(r"""['"]\.[a-z0-9]{1,10}['"]\s*:\s*['"][a-z0-9+#]*['"]""", re.I)


def _ext_maps() -> list[str]:
    found = []
    for path in _client_modules():
        rel = path.relative_to(ROOT).as_posix()
        src = _blank(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"\{[^{}]*\}", src, flags=re.S):
            if len(_EXT_KEY.findall(m.group(0))) >= 3:
                found.append(f"{rel}:{src[:m.start()].count(chr(10)) + 1}")
    return found


def test_no_client_module_holds_an_extension_to_language_map():
    """`Law 14`, and the ratchet the row is really asking for: a hand-copied
    list is not wrong today, it is wrong about the next language added. Four
    such maps existed before this row; the one that is left is the generated
    block, which a checker keeps equal to the Python."""
    maps = _ext_maps()
    assert maps == ["static/js/attachmentLanguage.js:43"], maps


def test_every_import_path_asks_the_shared_module():
    """The four call sites, counted where they are, so a fifth import path that
    invents its own answer is visible. Driven behaviour is the tests above; this
    is the thing behaviour cannot show — that no OTHER site exists."""
    calls = {}
    for path in _client_modules():
        src = _blank(path.read_text(encoding="utf-8"))
        n = len(re.findall(r"\bdocumentLanguage\(", src))
        if n:
            calls[path.relative_to(ROOT).as_posix()] = n
    assert calls == {
        "static/js/attachmentLanguage.js": 1,   # the definition
        "static/js/chat.js": 2,                 # import banner + open-attachment
        "static/js/document.js": 1,             # Import from device
        "static/js/documentLibrary.js": 1,      # library import
    }, calls


# ---------------------------------------------------------------------------
# the checker, which is what makes a generated constant safe
# ---------------------------------------------------------------------------

def _checker(tree: Path = ROOT, *args):
    proc = subprocess.run([sys.executable, str(tree / ".pantheon" / CHECKER.name), *args],
                          cwd=str(tree), capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout + proc.stderr


def _worktree(tmp_path: Path) -> Path:
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120).stdout.split()
    dest = tmp_path / "tree"
    for rel in files:
        if not (rel.endswith(".py") or rel.endswith(".js")):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / rel).read_bytes())
    return dest


def test_the_checker_passes_on_this_tree():
    code, out = _checker()
    assert code == 0, out


@pytest.mark.parametrize("where,old,new,expect", [
    # A language added on the server and not regenerated: the register drifts.
    ("src/document_processor.py", '".ipynb": "json",', '".ipynb": "json", ".erl": "erlang",',
     "generated block"),
    # The prose set is the fence decision, and it is generated too.
    ("src/document_processor.py", 'PROSE_LANGUAGES = frozenset({"text", "log"})',
     'PROSE_LANGUAGES = frozenset({"text", "log", "rst"})', "generated block"),
    # And the half a generated constant cannot give you: the RULE drifting while
    # both registers stay identical.
    ("static/js/attachmentLanguage.js", "if (!ext) return 'text';",
     "if (!ext) return 'plaintext';", "the browser says"),
    ("static/js/attachmentLanguage.js",
     "return LANGUAGE_TOKEN.test(token) ? token : 'text';",
     "return token;", "the browser says"),
])
def test_the_checker_fails_when_the_two_drift(tmp_path, where, old, new, expect):
    tree = _worktree(tmp_path)
    assert _checker(tree)[0] == 0, "the copy must be clean before it is mutated"
    src = (tree / where).read_text(encoding="utf-8")
    assert old in src, f"anchor missing in {where}"
    (tree / where).write_text(src.replace(old, new, 1), encoding="utf-8")
    code, out = _checker(tree)
    assert code == 1, f"nothing failed:\n{out}"
    assert expect in out, out


def test_the_editor_table_cannot_become_a_second_register(tmp_path):
    """The one way `EDITOR_LANGUAGE` could rot into the thing this row removed:
    an entry naming a language the server already decided."""
    tree = _worktree(tmp_path)
    js = tree / "static" / "js" / "attachmentLanguage.js"
    src = js.read_text(encoding="utf-8")
    js.write_text(src.replace("  scss: 'css',", "  scss: 'css',\n  kotlin: 'java',", 1),
                  encoding="utf-8")
    code, out = _checker(tree)
    assert code == 1, f"nothing failed:\n{out}"
    assert "alias target" in out, out
