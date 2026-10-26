# SPDX-License-Identifier: AGPL-3.0-or-later
"""No test writes down a cache-buster the product is serving today.

`B814`. Ten tests had been pinned to a `?v=<wave>` literal — `B772` recorded
the ninth, `test_offline_shell_manifest.py` was the tenth — and each went red
the moment a wave moved its module's specifier: a red test that looks like a
regression, costs a diagnosis, and teaches the next agent that bumping a buster
breaks the suite. Three were live when this rule landed
(`test_first_run_tours_are_gated.py`, `test_one_visibility_table_for_the_tools.py`,
`test_startup_session_bootstrap_js.py`); each now reads the specifier out of the
static file that imports the module, which is safe because
`check-specifiers.py` fails the build when two importers disagree.

The rule: no string in test CODE carries a dated `?v=` value that a tracked
file under `static/` also carries. Prose is exempt — a docstring or comment that
quotes a past buster to explain a fix is describing history, not depending on
it (`Law 20`: read the code, not the file).
"""
import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: A wave string: `?v=` then a date, then the wave's name (`20261009approvalcensus`).
#: `?v=1` in a synthetic fixture is not one — no wave will ever move it.
_WAVE = re.compile(r"\?v=(20\d{6}[A-Za-z0-9._-]*)")

#: Tests whose subject genuinely IS a specific buster string, with the reason.
#: Empty: the one `B814` expected here (`test_a_module_fetched_twice_is_a_second_module.py`)
#: holds only synthetic values now.
_SUBJECT_IS_THE_STRING: dict = {}


def _tracked(prefix: str) -> list:
    out = subprocess.run(["git", "ls-files", prefix], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return out


def live_busters() -> set:
    """Every dated `?v=` value a tracked file under `static/` carries."""
    found = set()
    for rel in _tracked("static"):
        if not rel.endswith((".js", ".mjs", ".html", ".css")):
            continue
        found.update(_WAVE.findall((ROOT / rel).read_text(encoding="utf-8", errors="replace")))
    return found


def pinned_in(source: str) -> list:
    """`(line, value)` for each dated `?v=` in a string constant that is code."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            for m in _WAVE.finditer(node.value):
                out.append((node.lineno + node.value[:m.start()].count("\n"), m.group(1)))
    return sorted(set(out))


def test_no_test_pins_a_buster_the_product_serves():
    live = live_busters()
    offenders = []
    for rel in _tracked("tests"):
        if not rel.endswith(".py") or rel in _SUBJECT_IS_THE_STRING:
            continue
        for line, value in pinned_in((ROOT / rel).read_text(encoding="utf-8")):
            if value in live:
                offenders.append(f"{rel}:{line}  ?v={value}")
    assert not offenders, (
        "a test writes down a cache-buster the product serves today, and goes red "
        "the next time a wave moves it:\n  " + "\n  ".join(offenders)
        + "\n\nRead the specifier out of the static file that imports the module "
          "(`check-specifiers.py` keeps every importer equal), as "
          "`test_startup_session_bootstrap_js.py` does.")


def test_the_rule_is_not_a_tautology():
    """A rule that finds nothing because it looks at nothing is no rule."""
    live = live_busters()
    assert len(live) >= 2, live
    value = sorted(live)[0]
    code = f'SPEC = "./x.js?v={value}"\n'
    prose = f'"""It once said ?v={value}, which is why."""\n# and ?v={value}\n'
    assert pinned_in(code) == [(1, value)]
    assert pinned_in(prose) == []


def test_the_allow_list_has_no_stale_entries():
    live = live_busters()
    stale = [rel for rel in _SUBJECT_IS_THE_STRING
             if not any(v in live for _, v in pinned_in((ROOT / rel).read_text(encoding="utf-8")))]
    assert not stale, f"{stale} no longer pins a live buster — remove the entry"
