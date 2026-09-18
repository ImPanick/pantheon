# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P11-02b` / `P11-02d` — the auth map, and the checker that stops it rotting.

Both rows asked for a table of where authorization is decided. Both rows also
demonstrate why a table alone is not enough: `P11-02b` carried **84** sites
while its own phase preamble said 103 thirty lines above, and `P11-02d` names
`chat_routes.py:338/367` as the place chat does its admin check — two lines
that hold `_candidate_index` and `_message_plain_text`. Nobody re-derived
either, and nobody could have, because nothing re-derived anything.

So `.pantheon/P11-AUTH-MAP.md` is held against the source by
`.pantheon/check-auth-map.py`, and these tests drive that checker's functions
rather than reading it (`Law 20`). Two halves:

  * the **mechanism** half runs the scanners over one-file fixture trees, so a
    claim like "an aliased import is still the same gate" is proved by a gate
    written for the purpose rather than by the repo happening to contain one;
  * the **product** half mutates the shipped map and asserts the checker
    notices — a site dropped, a site invented, a gate mis-stated, a hole left
    unfiled — and then asserts the shipped map, unmutated, is clean.

Every one of these fails on the tree before this row, because neither the
checker nor the map existed.
"""

import importlib.util
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / ".pantheon" / "check-auth-map.py"
MAP = ROOT / ".pantheon" / "P11-AUTH-MAP.md"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _checker():
    """The real checker module. Not `__main__`, so `main()` does not run."""
    spec = importlib.util.spec_from_file_location("check_auth_map", CHECKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checker():
    return _checker()


@pytest.fixture(scope="module")
def map_text():
    return MAP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shipped(checker, map_text):
    """The checker's verdict on the tree as it stands, computed once."""
    found, _counts = checker.problems(ROOT, map_text, max_other=_ci_ceiling())
    return found


@pytest.fixture(scope="module")
def sites(checker):
    return checker.require_admin_sites(ROOT)


def _ci_ceiling() -> int:
    found = re.findall(r"check-auth-map\.py\s+--max\s+(\d+)", WORKFLOW.read_text(encoding="utf-8"))
    assert len(found) == 1, (
        f"ci.yml states {len(found)} ceilings for check-auth-map; exactly one, "
        "or a site can hide behind the looser of two."
    )
    return int(found[0])


def _fixture_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """A one-or-two-file git repo the scanners can be pointed at.

    A fixture rather than the repo: a checker whose only evidence is "it passes
    on the tree it was written for" is the same drift one layer up.
    """
    for name, body in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


# ── the mechanism ───────────────────────────────────────────────────────────

def test_a_new_require_admin_site_is_found(checker, tmp_path):
    """Add a gate; the scanner reports it with its route and its function."""
    root = _fixture_tree(tmp_path, {"routes/new_routes.py": """
        from core.middleware import require_admin

        def setup():
            router = APIRouter(prefix="/api/new")

            @router.post("/danger")
            def do_danger(request):
                require_admin(request)
                return {}
    """})
    found = checker.require_admin_sites(root, ["routes/new_routes.py"])
    assert [(s.func, s.kind, s.route) for s in found] == [
        ("do_danger", "direct", "POST /api/new/danger")
    ]


def test_an_aliased_import_is_still_the_same_gate(checker, tmp_path):
    """`import require_admin as _require_admin` is the gap between 102 and 107.

    `routes/webhook/webhook_routes.py` does exactly this, and a grep for
    `require_admin(` finds none of its five gates.
    """
    root = _fixture_tree(tmp_path, {"routes/aliased.py": """
        from core.middleware import require_admin as _require_admin

        def setup():
            router = APIRouter(prefix="/api")

            @router.delete("/thing")
            def drop_thing(request):
                _require_admin(request)
    """})
    found = checker.require_admin_sites(root, ["routes/aliased.py"])
    assert [(s.func, s.route) for s in found] == [("drop_thing", "DELETE /api/thing")]


def test_a_router_level_dependency_is_one_site_not_none(checker, tmp_path):
    root = _fixture_tree(tmp_path, {"routes/dep.py": """
        from fastapi import Depends
        from core.middleware import require_admin

        def setup():
            router = APIRouter(prefix="/api/x", dependencies=[Depends(require_admin)])
    """})
    found = checker.require_admin_sites(root, ["routes/dep.py"])
    assert [(s.func, s.kind, s.route) for s in found] == [("setup", "depends", "")]


def test_a_local_reimplementation_is_not_counted_as_require_admin(checker, tmp_path):
    """`routes/shell_routes.py` writes its own. It is a different finding.

    Counting it in § A would say the gate is `require_admin` when it is not,
    and `B543` is the whole point: only the real one honours `auth_disabled()`.
    It belongs in rule C's ratchet instead, and it lands there.
    """
    root = _fixture_tree(tmp_path, {"routes/own.py": """
        def _require_admin(request):
            if not request.app.state.auth_manager.is_admin(request.state.current_user):
                raise HTTPException(403, "Admin only")

        def setup():
            router = APIRouter(prefix="/api/own")

            @router.post("/run")
            def run(request):
                _require_admin(request)
    """})
    assert checker.require_admin_sites(root, ["routes/own.py"]) == []
    others = checker.other_admin_gates(root, ["routes/own.py"])
    assert len(others) == 1 and "is_admin" in others[0]


def test_the_ratchet_ignores_require_admins_own_call(checker, tmp_path):
    """`core/middleware.py` calls `is_admin`. That call IS `require_admin`."""
    root = _fixture_tree(tmp_path, {"core/middleware.py": """
        def require_admin(request):
            auth_mgr = request.app.state.auth_manager
            if not auth_mgr.is_admin(request.state.current_user):
                raise HTTPException(403, "Admin only")
    """})
    assert checker.other_admin_gates(root, ["core/middleware.py"]) == []


def test_an_auth_call_one_helper_away_is_still_an_auth_call(checker, tmp_path):
    """The closure, which is why nine of the fifteen files are not unknowns.

    `assistant_routes.py` resolves the caller in a one-line `_owner()`; a
    per-handler grep calls all six of its routes ungated.
    """
    root = _fixture_tree(tmp_path, {"routes/indirect.py": """
        from src.auth_helpers import get_current_user

        def setup():
            router = APIRouter(prefix="/api/ind")

            def _owner(request):
                return get_current_user(request)

            @router.get("/mine")
            def mine(request):
                return {"owner": _owner(request)}
    """})
    found = checker.routes_in(root, "routes/indirect.py")
    assert [(r.key, sorted(r.auth)) for r in found] == [
        ("GET /api/ind/mine", ["get_current_user"])
    ]


def test_a_route_with_no_auth_call_reports_none(checker, tmp_path):
    root = _fixture_tree(tmp_path, {"routes/bare.py": """
        def setup():
            router = APIRouter(prefix="/api/bare")

            @router.post("/clear-cache")
            def clear_cache():
                return {"ok": True}
    """})
    found = checker.routes_in(root, "routes/bare.py")
    assert [(r.key, sorted(r.auth)) for r in found] == [("POST /api/bare/clear-cache", [])]


def test_the_exemption_is_matched_on_path_alone(checker):
    """`B542`'s premise, taken from `app.py` rather than asserted.

    `_is_auth_exempt(path)` takes one argument. `/api/auth/settings` is on the
    list so the pre-login page can read keybinds, and the POST that writes every
    app setting shares the path.
    """
    exact, patterns = checker.auth_exempt(ROOT)
    assert "/api/auth/settings" in exact
    assert "/api/auth/login" in exact
    assert checker.is_exempt("/api/auth/settings", exact, patterns)
    assert not checker.is_exempt("/api/auth/users", exact, patterns)
    # The `/static` prefix is a prefix, not an exact match.
    assert checker.is_exempt("/static/js/app.js", exact, patterns)


def test_site_keys_are_unique_so_the_map_can_omit_line_numbers(sites):
    """The map's whole design rests on this, so it is asserted rather than hoped."""
    keys = [s.key for s in sites]
    assert len(keys) == len(set(keys))


# ── the shipped map ─────────────────────────────────────────────────────────

def test_the_shipped_map_matches_the_tree(shipped):
    assert shipped == [], "\n".join(shipped)


def test_the_map_must_name_every_site(checker, map_text, sites):
    """Drop one row and the checker names the site the map forgot."""
    victim = next(s for s in sites if s.file == "routes/vault/vault_routes.py")
    cut = "\n".join(
        line for line in map_text.splitlines()
        if not line.startswith(f"| `{victim.file}` | `{victim.func}` |")
    )
    found, _ = checker.problems(ROOT, cut, max_other=_ci_ceiling())
    assert any(victim.func in p and "is in no tier table" in p for p in found), found


def test_the_map_may_not_name_a_site_that_is_gone(checker, map_text):
    """A row for a gate that no longer exists is the other half of the same rot."""
    anchor = "| `routes/vault/vault_routes.py` | `unlock` |"
    ghost = ("| `routes/vault/vault_routes.py` | `retired_gate` | "
             "`POST /api/vault/retired` | a gate that was deleted |\n")
    found, _ = checker.problems(ROOT, map_text.replace(anchor, ghost + anchor),
                                max_other=_ci_ceiling())
    assert any("retired_gate" in p and "no `require_admin` there any more" in p
               for p in found), found


def test_a_route_gate_claim_is_checked_against_the_source(checker, map_text):
    """Claiming a gate the route does not have is the failure this file exists for."""
    mutated = map_text.replace(
        "| `POST /api/tts/clear-cache` | `clear_tts_cache` | `middleware` |",
        "| `POST /api/tts/clear-cache` | `clear_tts_cache` | `middleware + require_admin` |",
    )
    assert mutated != map_text
    found, _ = checker.problems(ROOT, mutated, max_other=_ci_ceiling())
    assert any("POST /api/tts/clear-cache" in p and "the source says" in p
               for p in found), found


def test_an_unintended_route_must_name_a_bug_row(checker, map_text):
    """`no` with no `Bxxx` is an unfiled hole sitting quietly in a table."""
    mutated = map_text.replace("no — `B540`. An instance-wide", "no. An instance-wide")
    assert mutated != map_text
    found, _ = checker.problems(ROOT, mutated, max_other=_ci_ceiling())
    assert any("names no `Bxxx`" in p for p in found), found


def test_a_tier_total_that_does_not_add_up_fails(checker, map_text, sites):
    """`Law 8` — derived state is checked by a script, never by eye."""
    counts = {tier: 0 for tier in checker.TIERS}
    parsed = checker.parse_map(map_text)
    for row in parsed.sites.values():
        counts[row["tier"]] += 1
    real = counts["superuser"]
    mutated = map_text.replace(f"| `superuser` | {real} |", f"| `superuser` | {real - 1} |")
    assert mutated != map_text
    found, _ = checker.problems(ROOT, mutated, max_other=_ci_ceiling())
    assert any("tier summary" in p for p in found), found


def test_a_tier_count_restated_in_prose_is_checked_too(checker, map_text):
    """The map argues from these numbers, so a right table under a wrong
    paragraph is the same drift wearing a different hat."""
    mutated = map_text.replace("45 operator sites", "44 operator sites")
    assert mutated != map_text
    found, _ = checker.problems(ROOT, mutated, max_other=_ci_ceiling())
    assert any("in prose" in p for p in found), found


def test_the_derived_line_is_derived(checker, map_text, sites):
    direct = sum(1 for s in sites if s.kind == "direct")
    mutated = map_text.replace(f"derived: direct {direct}", f"derived: direct {direct - 4}")
    assert mutated != map_text
    found, _ = checker.problems(ROOT, mutated, max_other=_ci_ceiling())
    assert any("`derived:` line" in p for p in found), found


def test_the_other_gates_line_is_derived(checker, map_text):
    """The map's whole argument — four gates, one of them honouring
    `auth_disabled()` — rests on this count, so it is computed, not typed."""
    mutated = re.sub(r"derived-others: \d+ across", "derived-others: 1 across", map_text)
    assert mutated != map_text
    found, _ = checker.problems(ROOT, mutated, max_other=_ci_ceiling())
    assert any("`derived-others:` line" in p for p in found), found


def test_the_ci_ceiling_has_no_slack(checker):
    """`B520`'s remedy: assert the invariant, never the instance.

    The checker fails when the population rises above the ceiling; this fails
    when the ceiling sits above the population. Neither test names a number,
    and together they pin the two equal — so the day these gates start moving
    onto `P11-02`'s roles, the ratchet has to come down with them.
    """
    assert _ci_ceiling() <= len(checker.other_admin_gates(ROOT))
