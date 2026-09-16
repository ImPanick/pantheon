# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B96` / `B97` / `B98` — what a switch means, at the four places one is typed.

Three rows, one question asked from three sides.

`B96` is *does the switch mean what the operator typed*: two of them did not.
`AUTH_ENABLED=0` left authentication **enabled**, and `PANTHEON_SINGLE_USER=false`
left single-user mode **on** — and the second was worse than the row knew,
because the value was read into a module constant nothing consulted, so no
spelling turned it off at all (filed as `B150`).

`B97` is *whose string is this*: 16 truthiness sites outside the environment,
three vocabularies between them, and two private half-helpers neither reachable
from the other's callers. Four boundaries now have four named owners and they
are deliberately not the same rule.

`B98` is *can the checker see a resolver written across two statements*: it
could not, and the measurement that proves it is the pair of counts — nine holds
recorded against eight sites reachable, so one exemption was holding nothing.

Everything here drives a real resolver or runs the real checker over a real
repository. Nothing asserts on source text (`Law 20`), and nothing reloads
`src.constants` or `src.settings` (`B18`, `B130` — 41 modules import from the
first by value and a reload is not undoable).
"""
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CHECKER = _REPO / ".pantheon" / "check-env-declared.py"
_HARNESS = _REPO / "tests" / "harness" / "env_backed_flag_panel.js"


def _load_checker(root: Path | None = None):
    spec = importlib.util.spec_from_file_location("env_boundary_checker", _CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if root is not None:
        module.ROOT = root
        module.ENV_EXAMPLE = root / ".env.example"
        module.SETTINGS_SOURCE = root / "src" / "settings.py"
        module._corpus.cache_clear()
    return module


_REAL: list = []


def _real_checker():
    """One real-tree checker module for the whole file (`B220`).

    Six tests here each built their own and each paid the full scan. The module
    memoises its parse per file, so sharing one instance turns five of those
    six into lookups. Every test that changes it does so through `monkeypatch`.
    """
    if not _REAL:
        _REAL.append(_load_checker())
    return _REAL[0]


@pytest.fixture
def repo(tmp_path):
    """A one-file git repository the checker can be pointed at."""
    def build(files: dict):
        for name, text in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (tmp_path / ".env.example").touch()
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
        return _load_checker(tmp_path)
    return build


# ══ B96 — the two switches that meant the opposite ═════════════════════════

AUTH_OFF_SPELLINGS = ("0", "false", "no", "off", " OFF ", "False")
AUTH_ON_SPELLINGS = ("1", "true", "yes", "on", "", "   ", "maybe", "enabled")


@pytest.mark.parametrize("raw", AUTH_OFF_SPELLINGS)
def test_every_disabling_spelling_of_auth_enabled_disables_auth(monkeypatch, raw):
    """The row's headline. Measured 2026-09-15 before the fix: `AUTH_ENABLED=0`
    left authentication ENABLED, because only the literal `false` disabled it.
    An operator typed the disabling value and the switch was on."""
    import src.owner_identity as O
    monkeypatch.setattr(O, "_warned_auth_spelling", True)
    monkeypatch.setenv("AUTH_ENABLED", raw)
    assert O.auth_disabled() is True, raw


@pytest.mark.parametrize("raw", AUTH_ON_SPELLINGS)
def test_auth_stays_on_for_every_other_value(monkeypatch, raw):
    """`Law 1`, and the direction this switch has to fail in: blank, unset and a
    word outside the vocabulary all keep authentication. Nothing that was
    authenticated becomes unauthenticated by accident."""
    import src.owner_identity as O
    monkeypatch.setenv("AUTH_ENABLED", raw)
    assert O.auth_disabled() is False, raw


def test_auth_unset_keeps_authentication(monkeypatch):
    import src.owner_identity as O
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    assert O.auth_disabled() is False


def test_the_upgrade_says_so_before_it_does_it(monkeypatch, caplog):
    """`B96` requires the change announced. The three spellings whose meaning
    changed warn; the one that already worked is silent, so the log fires only
    on hosts this actually affects."""
    import src.owner_identity as O
    for raw in ("0", "no", "off"):
        monkeypatch.setattr(O, "_warned_auth_spelling", False)
        monkeypatch.setenv("AUTH_ENABLED", raw)
        with caplog.at_level(logging.WARNING, logger="src.owner_identity"):
            caplog.clear()
            assert O.auth_disabled() is True
        assert any("AUTH_ENABLED" in r.message for r in caplog.records), raw

    monkeypatch.setattr(O, "_warned_auth_spelling", False)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    with caplog.at_level(logging.WARNING, logger="src.owner_identity"):
        caplog.clear()
        assert O.auth_disabled() is True
    assert not caplog.records, "`false` already disabled auth — nothing changed for it"


@pytest.mark.parametrize("raw", ("0", "false", "no", "off", "FALSE"))
def test_every_disabling_spelling_of_single_user_turns_it_off(monkeypatch, raw):
    """The second switch. Before the fix only the literal `0` was recognised,
    so `PANTHEON_SINGLE_USER=false` left single-user mode on."""
    import routes.calendar_routes as C
    monkeypatch.setenv("PANTHEON_SINGLE_USER", raw)
    assert C._single_user_mode() is False, raw


@pytest.mark.parametrize("raw", ("1", "true", "yes", "on", "", "nonsense"))
def test_single_user_stays_on_for_everything_else(monkeypatch, raw):
    import routes.calendar_routes as C
    monkeypatch.setenv("PANTHEON_SINGLE_USER", raw)
    assert C._single_user_mode() is True, raw


class _AnonymousRequest:
    """A request that resolved to no user — the state `_require_user` falls
    back for. `require_user` is monkeypatched to return `""`, which is what it
    genuinely returns in all three anonymous modes."""
    cookies: dict = {}
    headers: dict = {}


def test_the_single_user_switch_is_actually_consulted(monkeypatch):
    """**The half the row did not know about.** `_SINGLE_USER_MODE` was computed
    at import and referenced nowhere in the tree, so the documented
    `PANTHEON_SINGLE_USER=0` did nothing: an unauthenticated calendar write
    landed on `FALLBACK_OWNER` whatever the operator set. Driven through
    `_require_user`, which is the one place the fallback is handed out."""
    from fastapi import HTTPException
    import routes.calendar_routes as C
    monkeypatch.setattr(C, "require_user", lambda request: "")
    monkeypatch.setattr(C, "_warned_single_user_spelling", True)

    monkeypatch.setenv("PANTHEON_SINGLE_USER", "1")
    assert C._require_user(_AnonymousRequest()) == C.FALLBACK_OWNER

    monkeypatch.setenv("PANTHEON_SINGLE_USER", "false")
    with pytest.raises(HTTPException) as caught:
        C._require_user(_AnonymousRequest())
    assert caught.value.status_code == 401

    monkeypatch.setenv("PANTHEON_SINGLE_USER", "0")
    with pytest.raises(HTTPException):
        C._require_user(_AnonymousRequest())


def test_an_authenticated_caller_is_untouched_by_the_switch(monkeypatch):
    """`Law 1`. The switch governs the anonymous fallback and nothing else."""
    import routes.calendar_routes as C
    monkeypatch.setattr(C, "require_user", lambda request: "ada")
    monkeypatch.setenv("PANTHEON_SINGLE_USER", "0")
    assert C._require_user(_AnonymousRequest()) == "ada"


def test_the_single_user_upgrade_says_so_too(monkeypatch, caplog):
    from fastapi import HTTPException
    import routes.calendar_routes as C
    monkeypatch.setattr(C, "require_user", lambda request: "")
    monkeypatch.setattr(C, "_warned_single_user_spelling", False)
    monkeypatch.setenv("PANTHEON_SINGLE_USER", "false")
    with caplog.at_level(logging.WARNING, logger="routes.calendar_routes"):
        caplog.clear()
        with pytest.raises(HTTPException):
            C._require_user(_AnonymousRequest())
    assert any("PANTHEON_SINGLE_USER" in r.message for r in caplog.records)


# ══ B97 — four boundaries, four owners, deliberately not one rule ══════════

def test_the_four_boundaries_do_not_answer_the_same_way():
    """The row's whole argument, driven. An operator, our own front end and a
    model are three different producers, and `y`/`enabled` is the case that
    separates them: a model writes those words unprompted, an operator does not,
    and `B91` settled deliberately that the environment does not take them."""
    from src.env_flags import env_truthy, request_truthy, tool_arg_truthy
    for word in ("y", "enable", "enabled"):
        assert env_truthy(word) is None, word
        assert request_truthy(word) is None, word
        assert tool_arg_truthy(word) is True, word


@pytest.mark.parametrize("word", ("1", "true", "yes", "on"))
def test_every_on_word_is_on_at_every_boundary(word):
    from src.env_flags import env_truthy, request_truthy, tool_arg_truthy
    assert env_truthy(word) is True
    assert request_truthy(word) is True
    assert tool_arg_truthy(word) is True


@pytest.mark.parametrize("word", ("0", "false", "no", "off"))
def test_every_off_word_is_off_at_the_two_operator_facing_boundaries(word):
    from src.env_flags import env_truthy, request_truthy, tool_arg_truthy
    assert env_truthy(word) is False
    assert request_truthy(word) is False
    # The model boundary has no off-list to preserve: all three sites it
    # replaces were `in (...)` tests, so anything that is not a yes is a no.
    assert tool_arg_truthy(word) is False


def test_plan_mode_one_used_to_mean_no_and_now_means_yes():
    """`B97`'s headline example. `plan_mode` is a safety mode and `plan_mode=1`
    from a form post read as *off* — the same string that read as *on* three
    lines away through `routes/model_routes._truthy`."""
    from src.env_flags import request_flag
    assert request_flag("1") is True
    assert request_flag("true") is True
    assert request_flag("false") is False
    assert "1".lower() != "true", "precondition: this is the spelling that lost"


def test_request_flag_answers_with_the_sites_own_default():
    from src.env_flags import request_flag
    assert request_flag(None) is False
    assert request_flag(None, True) is True
    assert request_flag("", True) is True
    assert request_flag("gibberish", True) is True
    assert request_flag("off", True) is False, "a recognised word beats the default"


@pytest.mark.parametrize("raw", [" true ", "\tTRUE\n", " On", "FALSE ", " 0 "])
def test_the_request_rule_folds_case_and_strips_the_way_the_others_do(raw):
    """`B91` found one site of 38 that never stripped, and `CLEANUP_ENABLED=" true"`
    was silently off because of it. A form post carries whatever a client put in
    the field, so the same trap is live at this boundary."""
    from src.env_flags import request_flag
    assert request_flag(raw) is (raw.strip().lower() in ("1", "true", "yes", "on"))


def test_a_real_bool_from_fastapi_is_believed_and_a_string_never_is():
    """`?full=1` is already a `bool` by the time the route sees it, which is why
    the two email sites had to test `is True` before parsing. `bool("false")` is
    the trap `B20` named and the reason a string is judged on its spelling."""
    from src.env_flags import request_flag
    assert request_flag(True) is True and request_flag(False) is False
    assert bool("false") is True, "precondition: the trap being avoided"
    assert request_flag("false") is False


def test_the_two_private_half_helpers_now_answer_the_same_question():
    """`routes/model_routes._truthy` was the widest HTTP rule in the tree and
    thirteen sites did not use it. Driven through the real function."""
    from routes.model_routes import _truthy
    from src.env_flags import request_flag
    for raw in ("true", "1", "yes", "on", "false", "0", "no", "off", "", "x", None):
        assert _truthy(raw) is request_flag(raw), raw


def test_the_tri_state_http_parser_keeps_its_third_answer():
    """`P3-22`. `supports_tools` must answer `None` for a word nobody meant —
    guessing `False` silently takes native tool support away from an endpoint
    that had it — and that is exactly why `request_truthy` is three-valued."""
    from routes.model_routes import _parse_supports_tools
    assert _parse_supports_tools("yes") is True
    assert _parse_supports_tools("off") is False
    assert _parse_supports_tools("banana") is None
    assert _parse_supports_tools(None) is None
    assert _parse_supports_tools(1) is True and _parse_supports_tools(0) is False
    assert _parse_supports_tools(7) is None


def test_the_two_gates_are_held_and_are_still_strict():
    """`Law 1`, the half that keeps this from being a loosening sweep. Every
    other HTTP field widened; these two grant tools, so `allow_web_search=1`
    still does not grant web search."""
    from src.tool_policy import tool_toggle_enabled, web_search_enabled_for_turn
    assert tool_toggle_enabled("true") is True
    for raw in ("1", "yes", "on"):
        assert tool_toggle_enabled(raw) is False, raw
        assert web_search_enabled_for_turn(raw) is False, raw
    assert web_search_enabled_for_turn("true") is True


def test_the_model_vocabulary_is_the_union_of_the_three_it_replaces():
    """Derived, not invented — `B91`'s method applied to the second boundary.
    Every token below was accepted by at least one of the three sites, so
    adopting one rule cannot lose a spelling any of them took."""
    from src.env_flags import tool_arg_truthy
    for word in ("on", "true", "1", "yes", "enable", "enabled", "y"):
        assert tool_arg_truthy(word) is True, word
    for word in ("nope", "", "maybe", None):
        assert tool_arg_truthy(word) is False, word
    assert tool_arg_truthy(True) is True and tool_arg_truthy(0) is False


def test_the_spam_flag_still_takes_a_typed_bool_and_a_number():
    """`src/builtin_actions.py` split this three ways by hand before `B97`;
    the shared rule has to keep both typed branches or the model's `true` JSON
    literal stops working."""
    from src.env_flags import tool_arg_truthy
    assert tool_arg_truthy(True) is True
    assert tool_arg_truthy(1.0) is True
    assert tool_arg_truthy(0) is False


def test_the_frontmatter_boundary_keeps_its_own_owner():
    """The fourth owner is a YAML-1.1 scalar parser and stays one — lifting its
    `true`/`yes` branch into `env_flags` would be the second form of a thing
    that already exists (`Law 14`). Driven so the boundary is pinned as a
    behaviour rather than named in a comment."""
    from services.memory.skill_format import _parse_scalar
    assert _parse_scalar("true") is True and _parse_scalar("yes") is True
    assert _parse_scalar("false") is False and _parse_scalar("no") is False
    assert _parse_scalar("on") == "on", "YAML 1.1 is not the environment's set"


# ══ B98 — the resolver written across two statements ═══════════════════════

_SPLIT = '''import os
def resolve():
    raw = os.environ.get("SPLIT_FLAG", "")
    return raw.strip().lower() == "true"
'''


def test_a_resolver_split_across_two_statements_is_visible(repo):
    """`B98`'s row, as a property. The shipped rule saw one comparison at a
    time, so a variable between the read and the judgement hid the site
    completely."""
    mod = repo({"app.py": _SPLIT})
    found = mod.spellings()
    assert any("SPLIT_FLAG" in line for line in found), found


def test_a_hold_beside_the_read_holds_the_judgement(repo):
    """All nine `B91` exemptions are written beside the *read*, because that is
    where the variable's name is. A rule that only looked above the comparison
    would report every one of them as unexempted."""
    mod = repo({"app.py": '''import os
def resolve():
    # env-spelling: this one keeps its own rule, and here is why.
    raw = os.environ.get("SPLIT_FLAG", "")
    return raw.strip().lower() == "true"
'''})
    assert mod.spellings() == []


def test_a_hold_beside_the_comparison_still_holds(repo):
    mod = repo({"app.py": '''import os
def resolve():
    raw = os.environ.get("SPLIT_FLAG", "")
    # env-spelling: held at the comparison instead.
    return raw.strip().lower() == "true"
'''})
    assert mod.spellings() == []


def test_a_blank_check_is_not_a_truthiness_rule(repo):
    """`""` has to be in `_TRUTH_TOKENS` — three real off-lists contain it — but
    `x == ""` is asking *did anyone set this*, which `env_truthy` answers with
    `None`. 44 places in this tree ask it, and the dataflow pass reaches
    `companion/pairing.py` where one of them is."""
    mod = repo({"app.py": '''import os
def resolve():
    value = os.environ.get("BLANK_FLAG")
    return value == ""
'''})
    assert mod.spellings() == []


def test_an_alias_of_os_environ_is_still_the_environment(repo):
    """The fourth shape of the blind spot, found while building the pass.
    `src/host_docker_access.py` binds `env = os.environ` and reads
    `env.get(NAME)`, so nothing in this checker had ever seen the site — and it
    is a `FORBIDDEN.md` Part 2 control."""
    mod = repo({"app.py": '''import os
NAME = "ALIAS_FLAG"
def resolve(environ=None):
    env = os.environ if environ is None else environ
    return env.get(NAME, "").strip().lower() == "true"
'''})
    assert any("ALIAS_FLAG" in line for line in mod.spellings()), mod.spellings()


def test_the_pass_does_not_leak_one_functions_locals_into_another(repo):
    """The bug that made the first draft report 104 findings against 9 real
    ones: `ast.walk` on a module does not stop at a nested function, so every
    local in the file shared one namespace and an unrelated `unit == "on"`
    inherited a variable read twelve hundred lines away."""
    mod = repo({"app.py": '''import os
def reader():
    raw = os.environ.get("ELSEWHERE_FLAG", "")
    return raw

def unrelated(raw):
    return raw.strip().lower() == "true"
'''})
    assert mod.spellings() == []


def test_an_enum_test_that_happens_to_use_a_vocabulary_word_is_left_alone(repo):
    """`level == "off"` is a SafeSearch level, `auto_submitted != "no"` is RFC
    3834 and `x-ratelimit-remaining == "0"` is a count. A rule that read those
    as truthiness is noise nobody reads, which is the failure mode `B20` named
    for the rules it did not widen."""
    mod = repo({"app.py": '''def a(level):
    return level == "off"

def b(headers):
    return headers.get("x-ratelimit-remaining") == "0"

def c(action):
    return action in ("enable", "disable")
'''})
    assert mod.rival_vocabularies() == []
    assert mod.spellings() == []


def test_a_fourth_private_truthy_fails_the_build(repo):
    """`B97`'s *fails on a fourth*. Every one of the five vocabularies the row
    counted was written as a small helper answering *is this yes*, and that is
    the shape a model argument's or a frontmatter line's provenance cannot be
    recovered from — so the helper is what gets caught."""
    mod = repo({"app.py": '''def _truthy(value):
    return str(value).strip().lower() in ("true", "1", "yes", "on")
'''})
    found = mod.rival_vocabularies()
    assert len(found) == 1 and "_truthy" in found[0], found


def test_a_fourth_vocabulary_may_be_held_with_its_reason(repo):
    mod = repo({"app.py": '''def _truthy(value):
    # flag-spelling: this one is somebody else's convention, and here is why.
    return str(value).strip().lower() in ("true", "1", "yes", "on")
'''})
    assert mod.rival_vocabularies() == []


def test_a_form_field_judged_inline_fails_the_build(repo):
    """The BOUNDARY rule, on the shape all thirteen sites had."""
    mod = repo({"app.py": '''from fastapi import Form
async def route(plan_mode: str = Form("")):
    return str(plan_mode).lower() == "true"
'''})
    found = mod.boundaries()
    assert len(found) == 1 and "request field" in found[0], found


def test_a_body_field_judged_inline_fails_the_build(repo):
    mod = repo({"app.py": '''async def route(form_data):
    return str(form_data.get("incognito", "")).lower() == "true"
'''})
    assert len(mod.boundaries()) == 1, mod.boundaries()


def test_the_boundary_rule_is_quiet_once_the_owner_is_called(repo):
    mod = repo({"app.py": '''from fastapi import Form
from src.env_flags import request_flag
async def route(plan_mode: str = Form("")):
    return request_flag(plan_mode)
'''})
    assert mod.boundaries() == []


def test_a_gate_may_keep_its_own_request_rule_with_its_reason(repo):
    mod = repo({"app.py": '''from fastapi import Form
async def route(allow_bash: str = Form("")):
    # flag-spelling: widening this would grant a tool, not honour an intent.
    return str(allow_bash).lower() == "true"
'''})
    assert mod.boundaries() == []


_BOTH_LAYERS = """import os
from fastapi import Form
async def route(plan_mode: str = Form("")):
    raw = plan_mode or os.environ.get("PLAN_MODE_DEFAULT", "")
    return raw.strip().lower() == "true"
"""


def test_a_value_from_both_layers_is_reported_once_by_the_environment_rule(repo):
    """A field that falls back to a variable belongs to the environment rule.
    Reporting it twice would hand the operator two findings and two different
    remedies for one line, and the `# env-spelling:` hold beside the read would
    silence only one of them."""
    mod = repo({"app.py": _BOTH_LAYERS})
    assert len(mod.spellings()) == 1, mod.spellings()
    assert mod.boundaries() == [], mod.boundaries()


def test_a_mail_body_is_not_a_request_body(repo):
    """The rule names the receivers it trusts rather than matching on the word
    `body`, because a rule that guessed would start reading mail."""
    mod = repo({"app.py": '''def classify(message_body):
    return str(message_body.get("flagged", "")).lower() == "true"
'''})
    assert mod.boundaries() == []


_INERT = """import os
_SINGLE_USER_MODE = os.environ.get("PANTHEON_SINGLE_USER", "1") != "0"

def require_user():
    return "owner@localhost"
"""

_LIVE = """import os
_SINGLE_USER_MODE = os.environ.get("PANTHEON_SINGLE_USER", "1") != "0"

def require_user():
    if not _SINGLE_USER_MODE:
        raise RuntimeError("401")
    return "owner@localhost"
"""


def test_a_variable_read_into_a_name_nothing_reads_is_reported(repo):
    """`B150`, and the exact line `B96` was filed against. Every other rule here
    answers a question about the *read* — is it documented, is it mentioned, can
    the line execute, what does the comparison mean — and all four said yes
    while `PANTHEON_SINGLE_USER=0` did nothing for the life of the file."""
    mod = repo({"app.py": _INERT})
    found = mod.inert_reads()
    assert len(found) == 1 and "_SINGLE_USER_MODE" in found[0], found


def test_a_variable_something_actually_consults_is_not_reported(repo):
    mod = repo({"app.py": _LIVE})
    assert mod.inert_reads() == []


def test_a_variable_another_module_imports_is_not_reported(repo):
    """Module constants are imported across files, so a single-file walk would
    report every one of them."""
    mod = repo({"app.py": _INERT,
                "other.py": "from app import _SINGLE_USER_MODE\nprint(_SINGLE_USER_MODE)\n"})
    assert mod.inert_reads() == []


# ══ The real tree ══════════════════════════════════════════════════════════

def test_the_real_tree_has_no_unexempted_spelling_boundary_or_vocabulary():
    mod = _real_checker()
    assert mod.spellings() == []
    assert mod.boundaries() == []
    assert mod.rival_vocabularies() == []
    assert mod.inert_reads() == []


def test_every_hold_is_a_hold_on_a_site_the_rules_can_reach():
    """`B98`'s measurement, kept as a ratchet. The finding was that
    `exempt_spellings` counted **nine** environment holds while `spellings`
    could reach **eight** sites — so one exemption was decoration, and deleting
    it would have failed no build. Removing a hold must now break something."""
    mod = _real_checker()
    holds = mod.exempt_spellings()
    assert holds, "precondition: there are holds to check"
    reachable = _env_sites_reachable(mod)
    assert len(holds) <= reachable, (
        f"{len(holds)} holds recorded but only {reachable} sites are reachable — "
        "an exemption on a site no rule can see is holding nothing (`B98`)")


def _env_sites_reachable(mod) -> int:
    """How many environment truthiness sites the rule reaches, held or not."""
    import ast
    count = 0
    for rel in mod._tracked("*.py"):
        if rel.startswith(mod.SKIP_PREFIXES) or rel == "src/env_flags.py":
            continue
        try:
            tree = ast.parse((mod.ROOT / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        consts = mod._module_consts(tree)
        seen = set()
        for scope, origins in mod._scopes_with_origins(tree, consts):
            for node in mod._own_body(scope):
                values = mod._truthiness_values(node)
                if values is None:
                    continue
                names = {n for kind, n in mod._origins_in(
                    node.left, consts, origins, origins.get("__environs__", set()))
                    if kind == "env"}
                if names and (rel, node.lineno) not in seen:
                    seen.add((rel, node.lineno))
                    count += 1
    return count


def test_the_undeclared_ratchet_is_not_loose():
    """`B98`. The ceiling stood at 74 while the real count was 72 — two names of
    slack is two undocumented variables a change could add with nothing saying
    so. A ratchet left loose is where the next regression hides."""
    mod = _real_checker()
    missing = set(mod.literal_reads()) - set(mod.declared()) - set(mod.NOT_OURS)
    default = _checker_default_max()
    assert len(missing) == default, (
        f"{len(missing)} undeclared against a ceiling of {default}")
    workflow = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f"--max {default}" in workflow, "CI and the checker must agree on the ceiling"


def _checker_default_max() -> int:
    """The ceiling the checker applies when nobody passes one — read by running
    it, not by parsing its source.

    `B220`. Still *run*, in this process rather than in a new one: `main()` is
    the entry point CI calls and it prints the same header. The spawn cost 43.6s
    a call and this file made two of them."""
    import contextlib
    import io
    import re
    mod = _real_checker()
    argv = sys.argv
    buffer = io.StringIO()
    try:
        sys.argv = ["check-env-declared.py"]
        with contextlib.redirect_stdout(buffer):
            mod.main()
    finally:
        sys.argv = argv
    match = re.search(r"UNDECLARED \d+ \(max (\d+)\)", buffer.getvalue())
    assert match, buffer.getvalue()
    return int(match.group(1))


# ══ B151 — the two scans disagree, and now they say so ═════════════════════

def test_the_undeclared_scan_sees_a_variable_read_through_an_environ_alias(repo):
    """`B151`. `env = os.environ` followed by `env.get("X")` was invisible to
    `literal_reads`, which is the scan the UNDECLARED ratchet counts, while
    `B98`'s dataflow pass resolved the same alias for SPELLING and BOUNDARY.
    Two scans, one tree, opposite answers, and nothing said so in either
    docstring."""
    mod = repo({"app.py": (
        "import os\n"
        "def resolve():\n"
        "    env = os.environ\n"
        "    return env.get('ALIASED_FLAG', '')\n"
    )})
    assert "ALIASED_FLAG" in mod.literal_reads()


def test_the_conditional_alias_the_real_site_is_written_with_is_seen(repo):
    """`src/host_docker_access.py:42` spells it `env = os.environ if environ is
    None else environ`, which is the shape `B98` found and the reason this rule
    resolves an `IfExp` rather than only a bare name."""
    mod = repo({"app.py": (
        "import os\n"
        "def resolve(environ=None):\n"
        "    env = os.environ if environ is None else environ\n"
        "    return env.get('CONDITIONAL_FLAG', '')\n"
    )})
    assert "CONDITIONAL_FLAG" in mod.literal_reads()


def test_a_dict_that_merely_contains_an_environment_read_is_not_an_alias(repo):
    """**The measurement that decided the row.** Reusing `_environ_aliases`
    here — the pass `B98` already built, and the obvious thing to reach for —
    takes UNDECLARED from 71 to 88 in the real tree, and all 17 added names are
    false. This is the shape that produces fifteen of them: a config dict built
    from an environment read becomes an "alias", and every `cfg["imap_password"]`
    below it reads as an environment variable named `imap_password`.

    The wide pass is still right for what it answers — which comparisons
    SPELLING may judge, where a false positive costs one held site — and it
    stays wide. The narrow one feeds a count an operator reads off `ci.yml`."""
    mod = repo({"app.py": (
        "import os\n"
        "def build():\n"
        "    cfg = {'imap_host': os.environ.get('REAL_VARIABLE', '')}\n"
        "    return cfg.get('imap_password', '')\n"
    )})
    names = set(mod.literal_reads())
    assert "REAL_VARIABLE" in names
    assert "imap_password" not in names, names
    # The wide pass has not been narrowed to buy this; it still calls `cfg` an
    # alias, because for its own question that is the safe direction.
    import ast
    scope = [n for n in ast.walk(ast.parse((mod.ROOT / "app.py").read_text()))
             if isinstance(n, ast.FunctionDef)][0]
    assert "cfg" in mod._environ_aliases(scope)
    assert "cfg" not in mod._environ_names(scope)


def test_a_variable_written_into_a_child_environment_is_not_a_read(repo):
    """`routes/cookbook_routes.py` copies the environment and writes
    `env["PYTHONUTF8"] = "1"` into it before handing it to a subprocess. That is
    a variable we set for a child, not one an operator sets for us, so it does
    not belong in a file that documents what an operator may configure — which
    is why only a `Load` subscript counts."""
    mod = repo({"app.py": (
        "import os\n"
        "def spawn():\n"
        "    env = os.environ.copy()\n"
        "    env['CHILD_ONLY'] = '1'\n"
        "    return env.get('READ_BACK', '')\n"
    )})
    names = set(mod.literal_reads())
    assert "CHILD_ONLY" not in names, names
    assert "READ_BACK" in names


def test_the_alias_rule_does_not_leak_one_functions_locals_into_another(repo):
    """`B98` reported 104 findings against 9 real ones the first time a pass
    here ignored scope. An `env` that is the environment in one function must
    not make an `env` in another one the environment too."""
    mod = repo({"app.py": (
        "import os\n"
        "def real():\n"
        "    env = os.environ\n"
        "    return env.get('GENUINE', '')\n"
        "def unrelated(env):\n"
        "    return env.get('NOT_THE_ENVIRONMENT', '')\n"
    )})
    names = set(mod.literal_reads())
    assert "GENUINE" in names
    assert "NOT_THE_ENVIRONMENT" not in names, names


def test_the_widening_does_not_move_the_ratchet_in_the_real_tree():
    """The objection to widening was that the ceiling is a number an operator
    reads off `ci.yml` and a scan that suddenly sees more names would move it
    without a line of product code changing. Measured rather than argued: the
    tree has three strict-alias sites and this adds **zero** names."""
    mod = _real_checker()
    missing = set(mod.literal_reads()) - set(mod.declared()) - set(mod.NOT_OURS)
    assert len(missing) == _checker_default_max()


def test_the_module_constant_asymmetry_is_still_the_other_one(repo):
    """`B151` closes one of the two asymmetries and leaves the other standing
    on purpose. `literal_reads` still does not resolve a module-level constant;
    `_env_name_of` does, and says why. Pinned so a future widening of *that*
    half is a deliberate act with its own measurement."""
    mod = repo({"app.py": (
        "import os\n"
        "NAME = 'CONSTANT_NAMED'\n"
        "def resolve():\n"
        "    env = os.environ\n"
        "    return env.get(NAME, '')\n"
    )})
    assert "CONSTANT_NAMED" not in mod.literal_reads()


# ══ B153 — the fifth producer, and whose convention it is ══════════════════

def test_the_fifth_producer_has_a_written_owner():
    """`B97` named four boundaries and gave each one owner. Counting them found
    a fifth producer with one site and no owner: `services/hwfit/image_models.py`
    reads `str(candidate.get("private")).lower() == "true"` off a third-party
    API's JSON. One site is not a vocabulary and a fifth rule would be `Law 14`;
    what was missing is the written answer to *whose convention is this*."""
    mod = _real_checker()
    owner = mod.FOREIGN_PRODUCERS.get(
        ("services/hwfit/image_models.py", "_variant_score"))
    assert owner, sorted(mod.FOREIGN_PRODUCERS)
    assert "huggingface" in owner.lower()


def test_the_register_is_not_a_fifth_rule():
    """`Law 14`. The four boundaries stay four — the register records producers
    that already have an owner and the owner is not us, which is what
    `NOT_OURS` does for `PATH`."""
    mod = _real_checker()
    assert len(mod.BOUNDARY_OWNERS) == 4
    assert not (set(mod.FOREIGN_PRODUCERS) & mod._OWNER_FUNCTIONS)


def test_the_sqlalchemy_hold_is_in_the_register_too():
    """`B153` names `core/database.py`'s `?uri=true` as the precedent it
    follows, so that hold is registered rather than left as the one foreign
    producer nobody wrote down."""
    mod = _real_checker()
    owner = mod.FOREIGN_PRODUCERS.get(("core/database.py", "_sqlite_db_path"))
    assert owner and "SQLAlchemy" in owner


def test_the_registered_site_still_reads_the_word_the_note_describes():
    """The register is a claim about code, and `B98`'s finding was that a hold
    nothing checks stops being load-bearing without anyone noticing."""
    mod = _real_checker()
    assert mod.stale_foreign_producers() == []


def test_a_register_entry_that_outlived_its_call_site_fails_the_run(repo, monkeypatch, capsys):
    """Driven through `main`, so it fails the build and not only the report."""
    mod = repo({"app.py": "def scorer(c):\n    return 1 if c else 0\n",
                "gone.py": "def nothing():\n    return 0\n"})
    monkeypatch.setattr(mod, "FOREIGN_PRODUCERS", {
        ("app.py", "scorer"): "somebody else's API",
    })
    monkeypatch.setattr(sys, "argv", ["check-env-declared.py"])
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "no yes/no comparison left here" in out
    assert "FOREIGN 1 registered, 1 stale (max 0)" in out


def test_a_register_entry_naming_a_function_that_is_gone_fails_too(repo, monkeypatch):
    mod = repo({"app.py": "def scorer(c):\n    return str(c).lower() == 'true'\n"})
    monkeypatch.setattr(mod, "FOREIGN_PRODUCERS", {
        ("app.py", "renamed_away"): "somebody else's API",
    })
    assert any("the function is gone" in line
               for line in mod.stale_foreign_producers())


def test_a_registered_site_that_still_compares_is_quiet(repo, monkeypatch):
    mod = repo({"app.py": "def scorer(c):\n    return str(c).lower() == 'true'\n"})
    monkeypatch.setattr(mod, "FOREIGN_PRODUCERS", {
        ("app.py", "scorer"): "somebody else's API",
    })
    assert mod.stale_foreign_producers() == []


def test_the_producer_really_does_send_a_json_boolean():
    """The register's claim, driven rather than asserted. `private` arrives
    already decoded — `json.loads` turns the API's `true` into a Python `True`
    before this line sees it — so there is no yes/no *string* here to have a
    vocabulary about, and that is the whole reason the site is exempt rather
    than converted."""
    from services.hwfit.image_models import _variant_score
    private = json.loads('{"id": "a/b-gguf", "private": true}')
    public = json.loads('{"id": "a/b-gguf", "private": false}')
    assert isinstance(private["private"], bool)
    assert _variant_score(private, "a/b", "gguf") \
        == _variant_score(public, "a/b", "gguf") - 10000
    # Absent is public, which is what the API means by omitting it.
    assert _variant_score({"id": "a/b-gguf"}, "a/b", "gguf") \
        == _variant_score(public, "a/b", "gguf")


# ══ B220 — the checker was the plateau ═════════════════════════════════════

def test_every_rule_reads_each_file_through_one_cached_parse():
    """`B220`. Seven passes each re-read and re-parsed all 360 tracked `.py`
    files: measured 43.6s per invocation, against a suite that shells out to it
    eight times. The fix is a cache and a hoist, never a narrowing — this pins
    that every pass goes through the one reader, so a new rule that opens the
    file itself is a deliberate act."""
    mod = _load_checker()   # a cold instance: this test measures the cache
    mod.spellings()
    first = mod._parsed.cache_info()
    assert first.currsize > 200, first
    mod.boundaries()
    mod.rival_vocabularies()
    mod.inert_reads()
    after = mod._parsed.cache_info()
    assert after.currsize == first.currsize, (first, after)
    assert after.hits > first.hits, (first, after)


def test_the_shared_origin_maps_are_the_same_answer_computed_once():
    """SPELLING, BOUNDARY and VOCABULARY each rebuilt the same file's origin
    maps. Sharing them is only safe because nothing writes to them, so this
    drives all three and asserts the maps come back unchanged."""
    mod = _real_checker()
    rel = "routes/chat_routes.py"
    before = mod._origins_for(rel)
    snapshot = [
        {k: (frozenset(v) if isinstance(v, (set, frozenset)) else dict(v))
         for k, v in origins.items()}
        for _scope, origins in before
    ]
    mod.spellings()
    mod.boundaries()
    mod.rival_vocabularies()
    after = mod._origins_for(rel)
    assert after is before, "three rules must share one pass, not rebuild it"
    for expected, (_scope, origins) in zip(snapshot, after):
        assert set(expected) == set(origins)
        for key, value in expected.items():
            got = origins[key]
            assert (frozenset(got) if isinstance(got, (set, frozenset)) else dict(got)) \
                == value, key


def test_the_rules_still_answer_exactly_what_they_answered_before():
    """The only property that matters about a speed-up: the verdict is
    unchanged. `Law 1` — a checker made faster by seeing less is a defect, not
    a fix."""
    mod = _real_checker()
    assert mod.spellings() == []
    assert mod.boundaries() == []
    assert mod.rival_vocabularies() == []
    assert mod.inert_reads() == []
    assert mod.mixed_layers() == []
    assert mod.unreachable(mod.shipped_defaults()) == []
    assert mod.unreferenced(mod.declared()) == []
    assert sorted(set(mod.NOT_OURS) - set(mod.literal_reads())) == []


def test_a_rule_does_not_rebuild_an_origin_map_another_rule_already_built():
    """`B220`, and the 27.4s. `rival_vocabularies` called
    `_origin_map(tree, consts, {})` **once per function in the file** — sixty
    identical module-level maps for a sixty-function module — and SPELLING and
    BOUNDARY each built the same file's maps again on top of that.

    Counted rather than timed, because a timing assertion is a flaky test: once
    the shared pass has run for a file, a rule that asks about that file again
    must build nothing. Before the fix this number was in the thousands."""
    mod = _real_checker()
    mod.spellings()          # warms `_origins_for` for every tracked file
    calls = []
    real = mod._origin_map
    try:
        mod._origin_map = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        mod.rival_vocabularies()
        mod.boundaries()
    finally:
        mod._origin_map = real
    assert calls == [], f"{len(calls)} origin maps rebuilt for work already done"
