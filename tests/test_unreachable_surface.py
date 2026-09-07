"""Working code with no door, found by a script (`P3-15`).

The hand audit of 2026-08-30 produced the 21 `H` rows, and the row's `Verify:`
line is that a script rediscovers its findings **from a clean checkout with no
hints**. One of those findings is still open in the tree — `H04`, a complete
embedding-model manager with zero pixels — so it is asserted against the real
repository. `H01` and `H10` are fixed, so their *shape* is asserted against a
fixture instead: a route with no caller must still be found, or the checker
only works on defects that happen to remain. `H10`'s own case is kept and
inverted — the cleanup routes must NOT appear now — because a test that pinned
a defect argues for the bug if it is left facing the same way.

The rest break the checker in the specific ways it can silently stop working,
and every one of them is a mistake this file's author actually made:

  * a flat walk of `app.routes` returns 69 of 505 while looking like it tried;
  * a literal path search cannot match a template-string caller;
  * an `ALLOWED` prefix with no reason is an exemption pretending to be a
    decision.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-unreachable.py"
WIRING = ROOT / ".pantheon" / "check-wiring.py"


def run(args=(), cwd=ROOT, timeout=300):
    return subprocess.run([sys.executable, str(cwd / ".pantheon" / "check-unreachable.py"), *args],
                          cwd=cwd, capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def report():
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


# ── the row's Verify line ───────────────────────────────────────────────────

def test_it_finds_H04_the_embedding_manager_with_zero_pixels(report):
    """`routes/embedding_routes.py`: a catalogue with download, progress poll
    and delete-with-refusal, all admin-gated, and not one pixel anywhere."""
    assert "/api/embeddings/models" in report
    assert "/api/embeddings/endpoint" in report


def test_H10_is_no_longer_in_the_report_because_it_was_wired(report):
    """Inverted 2026-09-07, when `H10` shipped.

    This asserted that the checker still found `GET /api/cleanup/preview` with
    no frontend caller, which was true for as long as the defect existed. The
    Settings → System panel now calls both halves, so the honest version of
    this test is the opposite claim: the routes must NOT appear. A test that
    pins a defect has to be turned around when the defect is fixed, or it
    starts arguing for the bug — and deleting it instead would give up a
    regression guard that costs nothing to keep."""
    assert "/api/cleanup/preview" not in report
    assert not re.search(r"POST\s+/api/cleanup\b", report)


def test_the_walk_recurses_or_it_finds_nothing(report):
    """The single most load-bearing sentence in the row: a flat walk of
    `app.routes` returns 69 because this FastAPI keeps included routers nested,
    and three of the audit's best findings are in the half a flat walk omits.

    The first implementation here recursed into `route.app` and `route.router`,
    both of which are `None` on this version's `_IncludedRouter` — so it
    recursed, found nothing, and reported 23 routes while looking correct.
    """
    match = re.search(r"routes (\d+) \(via (\w+)\)", report)
    assert match, report[:400]
    total, source = int(match.group(1)), match.group(2)
    assert source == "app", "fell back to the source scan; the app did not import"
    assert total > 300, (
        f"only {total} routes found. A flat walk returns ~69 on this codebase "
        "and the recursion has to follow `original_router`."
    )


# ── path normalisation: why a literal search is useless ─────────────────────

def _checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_check_unreachable", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("route,caller", [
    ("/api/gallery/{image_id}/rename", "${API_BASE}/api/gallery/${id}/rename"),
    ("/api/email/pending/{sid}/approve", "/api/email/pending/${encodeURIComponent(id)}/approve"),
    ("/api/session/{sid}", "`/api/session/${s.id}`"),
    ("/api/x/", "/api/x"),
])
def test_a_route_and_its_template_string_caller_normalise_the_same(route, caller):
    """These two share no useful substring, and they are the same route. That is
    the whole reason the hand audit needed three passes."""
    mod = _checker()
    assert mod.normalise(route) == mod.normalise(caller.strip("`"))


def test_two_different_routes_do_not_collapse_into_one():
    """Over-normalising is the failure in the other direction: every route
    matching every caller reports a clean tree."""
    mod = _checker()
    assert mod.normalise("/api/gallery/{id}") != mod.normalise("/api/gallery/{id}/rename")
    assert mod.normalise("/api/a/{x}") != mod.normalise("/api/b/{x}")


# ── the allowlist ───────────────────────────────────────────────────────────

def test_every_allowed_prefix_names_its_caller():
    """"Something else probably uses this" is how a dead route stays in the tree
    for a year. Each entry has to say who."""
    mod = _checker()
    assert mod.ALLOWED
    for prefix, reason in mod.ALLOWED.items():
        assert prefix.startswith("/"), prefix
        assert len(reason) > 20, f"{prefix} has no real reason"


def test_the_report_says_it_is_an_inventory_and_not_an_accusation(report):
    """A route with no frontend caller may be reached by an API token, a CLI, a
    webhook sender or the agent's own `app_api`. A checker that calls those dead
    teaches people to ignore it."""
    assert "inventory" in report.lower()


# ── the checker, broken on purpose ──────────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    dst = tmp_path / "repo"
    (dst / ".pantheon").mkdir(parents=True)
    (dst / "routes").mkdir()
    (dst / "static").mkdir()
    shutil.copy2(CHECKER, dst / ".pantheon" / "check-unreachable.py")
    # No importable app here, so the source scan is what runs — which is also
    # the path a half-configured checkout takes, and it needs to work.
    (dst / "routes" / "widget_routes.py").write_text(
        "from fastapi import APIRouter\n"
        "def setup():\n"
        "    router = APIRouter()\n"
        "    @router.get('/api/widget/list')\n"
        "    async def list_widgets(): ...\n"
        "    @router.post('/api/widget/{wid}/rename')\n"
        "    async def rename(wid: str): ...\n"
        "    return router\n",
        encoding="utf-8",
    )
    (dst / "static" / "app.js").write_text(
        "fetch(`${API_BASE}/api/widget/list`);\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    return dst


def test_the_fallback_scan_finds_a_route_with_no_caller(repo):
    """`H01`'s shape, which the real tree no longer has: one route is called
    from the frontend and one is not, and only the second is reported."""
    r = run(cwd=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "/api/widget/{wid}/rename" in r.stdout
    assert "/api/widget/list" not in r.stdout, \
        "a route the frontend calls was reported as unreachable"


def test_a_template_string_caller_counts_as_a_caller(repo):
    """The `${API_BASE}` form is how this frontend writes every URL. If it did
    not resolve, every route would be reported and the list would be useless."""
    (repo / "static" / "app.js").write_text(
        "fetch(`${API_BASE}/api/widget/${id}/rename`);\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    r = run(cwd=repo)
    assert "/api/widget/{wid}/rename" not in r.stdout


def test_the_ceiling_fails_when_the_count_grows(repo):
    assert run(["--max-routes", "0"], cwd=repo).returncode == 1
    assert run(["--max-routes", "1"], cwd=repo).returncode == 0


def test_the_real_tree_is_within_the_ceiling_ci_pins():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "check-unreachable.py --max-routes" in ci, "the checker is not in CI"
    ceiling = int(ci.split("check-unreachable.py --max-routes")[1].split()[0])
    r = run(["--max-routes", str(ceiling), "--quiet"])
    assert r.returncode == 0, \
        f"the tree exceeds the ceiling CI pins ({ceiling}):\n{r.stdout}{r.stderr}"


# ── check-wiring's three blind spots, which P3-15 required closing first ────

def _wiring():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_check_wiring", WIRING)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_comment_stripping_does_not_eat_the_file():
    """The measured disaster: `re.sub(r"/\\*.*?\\*/", "", src, flags=re.S)` took
    `static/js/gallery.js` from 144,034 characters to 64,919, because a `/*`
    inside a string opened a comment that ran thousands of lines. Every
    `id="..."` in the span went with it and the checker reported 153 unresolved
    ids that are created three lines from where they are looked up.
    """
    mod = _wiring()
    for name in ("static/js/gallery.js", "static/js/chat.js", "static/app.js"):
        raw = mod.read(name)
        if not raw:
            continue
        stripped = mod.code_only(raw)
        assert len(stripped) == len(raw), \
            f"{name}: {len(raw)} chars became {len(stripped)}"
        assert stripped.count('id="') == raw.count('id="')


def test_a_comment_is_not_a_lookup():
    mod = _wiring()
    src = 'const a = 1;\n// document.getElementById("ghost-id")\n/* getElementById("also-ghost") */\n'
    out = mod.code_only(src)
    assert "ghost-id" not in out and "also-ghost" not in out
    assert "const a = 1;" in out


def test_a_regex_literal_containing_a_slash_star_survives():
    """`/` is division or a pattern depending on what precedes it, and getting
    that wrong is how the naive stripper ate half a file."""
    mod = _wiring()
    src = "const re = /a\\/*b/; const id = 'kept-id';\n"
    assert "kept-id" in mod.code_only(src)


def test_an_id_reached_through_a_literal_collection_is_seen():
    """Blind spot 3, and the shape that hid the audit's highest-harm finding —
    the agent reporting it had opened a panel with no button behind it."""
    mod = _wiring()
    src = """
      const RAILS = { research: 'rail-research', ghost: 'rail-ghost-panel' };
      function show(which) { return el(RAILS[which]); }
    """
    assert mod.indirect_lookups(src) == {"rail-research", "rail-ghost-panel"}


def test_an_iterated_collection_counts_only_when_the_loop_variable_is_looked_up():
    """The over-reporting failure. "A lookup somewhere in the next 400
    characters" swept up `args: ["-y", "caldav-mcp"]` from an MCP preset table,
    and the first version of the rule took UNRESOLVED from 2 to 511."""
    mod = _wiring()
    bound = "const IDS = ['rail-a', 'rail-b'];\nIDS.forEach(id => el(id));\n"
    assert mod.indirect_lookups(bound) == {"rail-a", "rail-b"}

    unbound = ("const PRESETS = { caldav: { args: ['-y', 'caldav-mcp'] } };\n"
               "const other = 1;\nel(someComputedThing);\n")
    assert mod.indirect_lookups(unbound) == set(), \
        "a package name in an unrelated table was read as an element id"


def test_a_menu_label_is_not_an_element_id():
    """Requiring kebab shape for INDIRECT candidates. Without it the scan swept
    up `Calendar`, `Controls` and `Done` sitting in the same object as a real
    id."""
    mod = _wiring()
    src = "const M = { a: 'Calendar', b: 'Done', c: 'rail-real' };\nel(M[k]);\n"
    assert mod.indirect_lookups(src) == {"rail-real"}


@pytest.fixture(scope="module")
def wiring_report():
    r = subprocess.run([sys.executable, str(WIRING)], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_static_app_js_is_actually_scanned(wiring_report):
    """It was not, for the life of the checker — the application's own wiring,
    outside the scan. A drift metric that does not read the biggest file is a
    different number, not a floor.

    Asserted through the REAL RUN, on ids only `app.js` contributes. An earlier
    version called `tracked()` directly and checked `static/app.js` was in the
    list — which stayed true when `main()` was changed to ignore it, because the
    test never went near `main()`. Testing the ingredient rather than the recipe,
    for the sixth time in this project.

    `mode-toggle` and `notes-fullscreen-toggle` are the two the roadmap
    predicted this would surface, by name and line.
    """
    assert "mode-toggle" in wiring_report
    assert "notes-fullscreen-toggle" in wiring_report


def test_the_indirect_path_is_actually_used(wiring_report):
    """Same trap, other blind spot: `indirect_lookups()` can be correct and
    never called. `notes-panel` is reachable only through a literal collection,
    so it is reported only if `main()` uses that path."""
    assert "notes-panel" in wiring_report


def test_the_unresolved_count_is_the_one_ci_pins(wiring_report):
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # The job NAME also quotes the flag ("Wiring ratchet (check-wiring.py --max 9)"),
    # so match the `run:` line rather than the first occurrence — a mirror of the
    # number in a title is exactly how one goes half-stale.
    ceiling = int(re.search(r"run: python3 \.pantheon/check-wiring\.py --max (\d+)", ci).group(1))
    found = int(re.search(r"UNRESOLVED (\d+)", wiring_report).group(1))
    assert found <= ceiling, f"{found} unresolved against a ceiling of {ceiling}"
