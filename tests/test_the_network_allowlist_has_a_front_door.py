# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-09`. `src/networks.py` has been enforcing since `P16-16` — it is
consulted inside `check_outbound_url` and `outbound_fetch` **before DNS** — and
it had no panel, no route of its own and no validation.

`grep networks` returned nothing in `static/js/`, nothing in `routes/`. The
generic settings POST accepted the key only because it iterates
`DEFAULT_SETTINGS`, so an unparseable CIDR was stored, then dropped by
`Network.__init__`'s `except ValueError` with a `logger.warning` nobody watches,
and the operator got a 200 with their own text echoed back and a network that
classified nothing. **An allowlist the operator has no supported way to write is
not operator-set**, which is the premise `P17-02` is named after.

Lenient on read, strict on write, and the asymmetry is deliberate: a file that
loaded yesterday must load today (`Law 1`), and a typo in one entry must not take
the other four down with it — but at the moment somebody is *writing* the value,
silence is the defect.
"""
import ipaddress

import pytest

from src.networks import (
    DEFAULT_TRUST,
    TRUST_LEVELS,
    Network,
    declared_networks,
    matches_for,
    validate_networks,
)


# ── the validator ───────────────────────────────────────────────────────────

def test_a_well_formed_declaration_has_no_problems():
    assert validate_networks([
        {"name": "home", "cidrs": ["192.168.1.0/24"], "trust": "trusted"},
        {"name": "lab", "hosts": ["nas.local"], "trust": "limited"},
    ]) == []


def test_an_unparseable_cidr_is_refused_rather_than_dropped():
    """The whole row in one assertion. This value used to be accepted with a 200."""
    problems = validate_networks([{"name": "lab", "cidrs": ["10.9.0.0/48"]}])
    assert len(problems) == 1
    assert "10.9.0.0/48" in problems[0]
    assert "lab" in problems[0]


def test_the_loader_still_accepts_what_the_validator_refuses():
    """Strict on write, lenient on read. If `Network.__init__` started raising,
    one bad entry in an existing settings file would take the whole list down —
    and a file that loaded yesterday has to load today (`Law 1`)."""
    net = Network(name="lab", cidrs=["10.9.0.0/48", "10.9.0.0/16"])
    assert [str(c) for c in net.cidrs] == ["10.9.0.0/16"], (
        "the loader now rejects the whole entry instead of dropping the bad CIDR")


def test_every_problem_is_reported_not_just_the_first():
    """A form that reports one typo per round trip is a form people give up on."""
    problems = validate_networks([
        {"name": "a", "cidrs": ["nope"], "trust": "godmode"},
        {"name": "b", "cidrs": ["also-nope"]},
    ])
    assert len(problems) >= 3, problems


def test_a_duplicate_name_is_reported_because_the_second_is_unreachable():
    """`network_for` returns the first match, so a duplicate means one of the two
    can never be selected and nothing would say which."""
    problems = validate_networks([
        {"name": "lab", "cidrs": ["10.0.0.0/8"]},
        {"name": "LAB", "cidrs": ["192.168.0.0/16"]},
    ])
    assert any("repeats the name" in p for p in problems), problems


def test_a_network_that_matches_nothing_is_reported():
    """It is not an error the loader would notice, and it matches nothing — so a
    run scoped to it refuses every address, which looks like a bug in whatever
    was being scoped rather than in the declaration."""
    problems = validate_networks([{"name": "lab"}])
    assert any("matches nothing" in p for p in problems), problems


def test_an_unnamed_entry_is_reported():
    problems = validate_networks([{"cidrs": ["10.0.0.0/8"]}])
    assert any("no name" in p for p in problems), problems


@pytest.mark.parametrize("trust", list(TRUST_LEVELS))
def test_every_declared_trust_level_is_accepted(trust):
    assert validate_networks([
        {"name": "x", "cidrs": ["10.0.0.0/8"], "trust": trust}]) == []


def test_an_invented_trust_level_is_refused():
    problems = validate_networks([
        {"name": "x", "cidrs": ["10.0.0.0/8"], "trust": "godmode"}])
    assert any("godmode" in p for p in problems), problems


@pytest.mark.parametrize("value,shape", [
    ("not json at all", "list of objects"),
    ({"name": "x"}, "must be a list"),
    (7, "must be a list"),
])
def test_a_value_of_the_wrong_shape_says_so(value, shape):
    problems = validate_networks(value)
    assert problems and shape.split()[-1] in " ".join(problems).lower()


def test_json_text_is_accepted_because_that_is_what_a_form_posts():
    assert validate_networks('[{"name": "home", "cidrs": ["192.168.1.0/24"]}]') == []


# ── the preview ─────────────────────────────────────────────────────────────

def test_the_preview_answers_against_what_is_on_screen_not_what_is_saved():
    """`network_for` reads the saved setting. The panel needs to ask about a value
    the operator has not committed to yet — that is the whole point of showing it
    before they save."""
    proposed = [{"name": "home", "cidrs": ["192.168.1.0/24"]}]
    assert matches_for(proposed, "192.168.1.71") == "home"
    assert matches_for(proposed, "8.8.8.8") is None
    assert declared_networks() == [], (
        "this test would be vacuous if something were already declared")


def test_the_preview_matches_a_listed_host_as_well_as_a_cidr():
    proposed = [{"name": "lab", "hosts": ["nas.local"]}]
    assert matches_for(proposed, "nas.local") == "lab"
    assert matches_for(proposed, "NAS.LOCAL") == "lab", "host matching is case-sensitive"


def test_the_preview_and_the_enforcer_agree():
    """Two answers to "is this address in this network" would be the same rule in
    two places, and the second one goes stale (`Law 13`). `matches_for` builds the
    same `Network` objects `declared_networks` does — this pins that they cannot
    diverge."""
    spec = {"name": "home", "cidrs": ["192.168.1.0/24"], "hosts": ["nas.local"]}
    net = Network(name=spec["name"], cidrs=spec["cidrs"], hosts=spec["hosts"])
    for probe in ("192.168.1.71", "192.168.2.1", "nas.local", "other.local", ""):
        expected = net.name if net.contains(probe) else None
        assert matches_for([spec], probe) == expected, probe


def test_a_disabled_network_still_previews_so_the_operator_can_see_why():
    """A disabled network is excluded from `declared_networks`, so it classifies
    nothing — but the panel is showing the operator the row they are looking at,
    and answering "no match" for a row that visibly contains the address is how a
    person concludes the feature is broken."""
    assert matches_for(
        [{"name": "home", "cidrs": ["192.168.1.0/24"], "enabled": False}],
        "192.168.1.71") == "home"


# ── the wiring ──────────────────────────────────────────────────────────────
#
# The rules above are tested by running them. These test that something calls
# them — the ingredient-not-the-recipe failure has landed four times in this
# project, most recently on a detector nothing invoked. Read with `ast` where
# there is Python to parse, and with comments stripped where there is not, so a
# comment naming the function is never mistaken for a call (`Law 20`).

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _named_calls(fn, name):
    return [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == name]


def _route_fn(module_rel, fn_name):
    tree = ast.parse((_REPO / module_rel).read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == fn_name), None)
    assert fn is not None, f"{fn_name} is gone from {module_rel}"
    return fn


def _networks_branch(fn):
    """The `if key == "networks":` block inside a route function.

    Located by its *test expression*, not by proximity in the unparsed text. An
    earlier version of these tests searched a 400-character window after the
    `validate_networks` call for a `raise`, and a mutation that deleted the raise
    survived — the next validation block along has one, and the window reached
    it. Proximity is not reachability.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "key ==" in test and "networks" in test:
            return node
    return None


def test_the_settings_route_actually_validates_networks():
    """It accepted the key for one reason only — the loop iterates
    `DEFAULT_SETTINGS` — and did nothing else with it."""
    fn = _route_fn("routes/auth_routes.py", "set_settings")
    branch = _networks_branch(fn)
    assert branch is not None, (
        "set_settings has no branch guarded on the networks key — a call sitting "
        "under `if False:` is dead code that still parses")
    calls = _named_calls(branch, "validate_networks")
    assert len(calls) == 1, "the networks branch does not call validate_networks"
    assert calls[0].args, "validate_networks is called with nothing to validate"
    assert isinstance(calls[0].args[0], ast.Name), (
        "validate_networks is called with a literal rather than the posted value")


def test_a_refused_value_raises_rather_than_being_stored():
    """A validator whose result is computed and dropped is this project's most
    repeated defect. The `raise` has to be **inside the same branch** as the
    call, guarded by its result — not merely somewhere after it."""
    fn = _route_fn("routes/auth_routes.py", "set_settings")
    branch = _networks_branch(fn)
    assert branch is not None

    raises = [n for n in ast.walk(branch) if isinstance(n, ast.Raise)]
    assert raises, "the networks branch computes problems and never raises"
    for r in raises:
        assert "HTTPException" in ast.unparse(r)
        assert "400" in ast.unparse(r), "a refused declaration is a 400, not a 500"

    # And the raise is conditional on what the validator returned, rather than
    # unconditional or guarded by something else.
    guarded = [g for g in ast.walk(branch)
               if isinstance(g, ast.If)
               and any(isinstance(n, ast.Raise) for n in ast.walk(g))]
    assert guarded, "the raise is not inside a condition"
    names = set()
    for g in guarded:
        names |= {n.id for n in ast.walk(g.test) if isinstance(n, ast.Name)}
    assigned = {t.id for a in ast.walk(branch) if isinstance(a, ast.Assign)
                for t in a.targets if isinstance(t, ast.Name)}
    assert names & assigned, (
        f"the raise is guarded by {names or 'nothing'}, none of which the "
        f"validator assigned ({assigned})")


def test_the_check_endpoint_answers_both_questions_from_python():
    """One endpoint, because a CIDR matcher written in JavaScript would be the
    same rule in two languages — which is `Law 13`, and is exactly how `B65` hid
    for months."""
    fn = _route_fn("routes/auth_routes.py", "check_networks")
    assert _named_calls(fn, "validate_networks"), "the check endpoint does not validate"
    assert _named_calls(fn, "matches_for"), "the check endpoint cannot answer the probe"


def test_the_check_endpoint_is_admin_only():
    """It reads nothing secret, but it reveals the shape of the operator's
    network and every other settings route here is admin-gated."""
    fn = _route_fn("routes/auth_routes.py", "check_networks")
    src = ast.unparse(fn)
    assert "is_admin" in src and "403" in src


def test_the_panel_exists_and_is_reachable():
    """UPDATED 2026-09-18 by `P9-02`, which found this row's own drift.

    The tab used to be a hand-written button in `static/index.html` beside a
    registry that described every other panel — and this panel was the one the
    registry did not know about, so Settings search could not find the network
    allowlist by any word, including "networks". `renderSettingsNav()` now draws
    every tab from `static/js/settings/registry.js`, so the entry **is** the
    button and the admin gate is a field rather than a class somebody remembered
    to type. The panel is still markup, and is still asserted here.
    """
    html = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
    registry = (_REPO / "static" / "js" / "settings" / "registry.js").read_text(encoding="utf-8")
    assert 'data-settings-panel="networks"' in html, "the tab opens nothing"
    assert "id: 'networks'" in registry, "there is no way to open the panel"
    entry = registry.split("id: 'networks'", 1)[1].split("}),", 1)[0]
    assert "adminOnly: true" in entry, "the networks tab is not admin-gated"
    assert "label: 'Networks'" in entry, "the nav button's text comes from here now"
    # `settings.js` activates this panel itself (`onSettingsPanelActivated`
    # lazy-imports `networks.js`). Routing it through the admin controller —
    # which every other Administration panel uses — would send the click to
    # `window.adminModule.open('networks')`, and `admin.js` has no case for it.
    assert "controller: 'admin'" not in entry, (
        "an admin controller would send this click somewhere that does not draw it"
    )


def test_opening_the_tab_loads_the_module():
    """Comments stripped first: `settings.js` explains the panel in prose right
    beside the import, and a substring test would pass with the import deleted —
    which is the trap that bit `B65`'s own test."""
    src = (_REPO / "static" / "js" / "settings.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
    assert re.search(r"tab === 'networks'", code), "no activation branch for the tab"
    branch = code[code.index("tab === 'networks'"):]
    branch = branch[:branch.index("}")+1] if "}" in branch else branch
    assert "./networks.js" in branch, "the networks branch does not import the module"


def test_every_element_the_panel_reaches_for_is_in_the_markup():
    """A typo in an id is a panel that silently does nothing — which is the exact
    failure this whole row is about, moved to the front end."""
    js = (_REPO / "static" / "js" / "networks.js").read_text(encoding="utf-8")
    html = (_REPO / "static" / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r"\$\('([a-z0-9-]+)'\)", js))
    assert ids, "the scan found no element lookups; it has lost its subject"
    missing = sorted(i for i in ids if f'id="{i}"' not in html)
    assert missing == [], f"the panel reaches for ids that are not in the markup: {missing}"


def test_the_panel_does_not_reimplement_cidr_matching():
    """`Law 13`. Every question about membership goes to Python. A netmask
    calculation appearing here means the rule now lives in two languages and the
    second copy is the one that goes stale."""
    js = (_REPO / "static" / "js" / "networks.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines() if not ln.lstrip().startswith("//"))
    for smell in (">>>", "0xffffffff", "netmask", "parseInt(o", "<< 24", "255.255"):
        assert smell not in code, f"the panel looks like it is matching CIDRs itself: {smell!r}"
    assert "/api/auth/networks/check" in code, "the panel does not ask the server"
