# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1369` — the context window carries its own provenance.

`get_context_length_known` returned `(ctx, known)` and `known` was True for two
different things: a window an endpoint actually reported, and a **substring
match on the model's name** in `KNOWN_CONTEXT_WINDOWS`. The measurement that
filed this row:

    budget_context_for_model("http://127.0.0.1:9/v1", "gemma-4-26b")  →  262144

with nothing listening on that port, because `"gemma"` is a key in the table.
Every caller that scales something off the window — the agent's trim budget,
the context wheel, the tool suite's room — therefore could not tell a
measurement from a guess about a name, which is at least adjacent to
`D-2026-10-07-02` §1's rule that a capability is never read off a model's name.

**Nothing about what the product *does* changes here, and that is deliberate.**
`budget_context_for_model` still treats a name-table window as proven; whether
it should is the owner's call and the row says so. What changes is that the
answer is askable, and that the run receipt records it — so a narrowed turn can
be read back afterwards and the question answered, which it could not be.

Three cases are worth naming:

  * **`known` is not a second field that can drift.** It is exactly
    `basis != BASIS_FALLBACK`, asserted over every branch rather than left as
    two fields a future edit could set inconsistently (`Law 7`).
  * **When the table out-bids the endpoint, the basis follows the number that
    won.** `_query_context_length` returns `max(api_ctx, known)`, so an endpoint
    answering 8k for a model the table says holds 200k returns the table's
    200k — and labelling that `reported`, because an endpoint did answer, would
    have been the easy mistake. It is the one place the distinction is subtle.
  * **The strictness is the point.** A caller still returning a 2-tuple raises,
    loudly, rather than having its basis defaulted — a silently-unknown
    provenance is this row's own defect wearing a different hat.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import src.model_context as mc
from src.tool_index import ToolSuite, plan_tool_suite

ROOT = Path(__file__).resolve().parent.parent


# `B1022`: the model probes and lookups go through `paced_http` now, so the
# fakes stand in at that seam (`paced_http.get_sync` / `post_sync`) rather
# than at `httpx.get` / `httpx.post`, which those calls no longer use.

@pytest.fixture(autouse=True)
def _clean_cache():
    mc._context_cache.clear()
    mc._catalog_ctx_cache.clear()
    yield
    mc._context_cache.clear()
    mc._catalog_ctx_cache.clear()


# ── the vocabulary ─────────────────────────────────────────────────────────


def test_there_are_exactly_three_bases_and_they_are_ordered_by_what_they_prove():
    assert mc.CONTEXT_BASES == (mc.BASIS_REPORTED, mc.BASIS_KNOWN_TABLE,
                                mc.BASIS_FALLBACK)
    assert len(set(mc.CONTEXT_BASES)) == 3


# ── the measurement that filed the row ─────────────────────────────────────


def test_a_dead_port_and_a_famous_name_still_answer_but_now_say_which(monkeypatch):
    """The row's own probe, re-run. The window is unchanged — behaviour is not
    what this row changes — but it now says the number came from the name."""
    monkeypatch.setattr(mc, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(mc, "is_local_endpoint", lambda url: True)

    def no_server(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(mc.paced_http, "get_sync", no_server)

    # Derived from the table's own matcher, not from a key spelled here: the
    # row quotes `"gemma"` and the key is actually `gemma-4`, which is the
    # substring match being the whole point.
    expected = mc._lookup_known("gemma-4-26b")
    assert expected, "the name table no longer matches this model; pick another"
    ctx, known, basis = mc.get_context_length_basis("http://127.0.0.1:9/v1", "gemma-4-26b")
    assert (ctx, known) == (expected, True), (
        "the window moved; this row was explicitly not a behaviour change")
    assert basis == mc.BASIS_KNOWN_TABLE, (
        "a window matched from the model's name is reported as measured")


def test_a_reporting_endpoint_is_labelled_reported(monkeypatch):
    monkeypatch.setattr(mc, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(mc, "is_local_endpoint", lambda url: True)

    class _R:
        is_success = True

        @staticmethod
        def json():
            return [{"n_ctx": 24576}]

    monkeypatch.setattr(mc.paced_http, "get_sync", lambda url, **k: _R())
    ctx, known, basis = mc.get_context_length_basis("http://127.0.0.1:8080/v1", "nameless-model")
    assert (ctx, known, basis) == (24576, True, mc.BASIS_REPORTED)


def test_nothing_anywhere_is_labelled_fallback(monkeypatch):
    monkeypatch.setattr(mc, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(mc, "is_local_endpoint", lambda url: False)
    monkeypatch.setattr(mc, "_lookup_known", lambda model: None)

    def no_server(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(mc.paced_http, "get_sync", no_server)
    ctx, known, basis = mc.get_context_length_basis("https://nowhere.example/v1", "mystery")
    assert (ctx, known, basis) == (mc.DEFAULT_CONTEXT, False, mc.BASIS_FALLBACK)


def test_an_api_or_proxy_endpoint_with_a_name_hit_is_still_the_name(monkeypatch):
    """The `api`/`proxy` branch returns the table's window **without calling the
    endpoint at all** — a large aggregator's `/models` is expensive, so the
    table is preferred. That makes it the branch most easily mislabelled
    `reported`, and nothing reached it until a mutation survived here."""
    monkeypatch.setattr(mc, "_configured_endpoint_kind", lambda url: "proxy")
    monkeypatch.setattr(mc, "is_local_endpoint", lambda url: False)
    monkeypatch.setattr(mc, "_lookup_known", lambda model: 200_000)

    def no_server(*a, **k):
        raise AssertionError("the api/proxy branch must not call the endpoint")

    monkeypatch.setattr(mc.paced_http, "get_sync", no_server)
    ctx, known, basis = mc.get_context_length_basis("https://aggregator.example/v1", "famous")
    assert (ctx, known) == (200_000, True)
    assert basis == mc.BASIS_KNOWN_TABLE


@pytest.mark.parametrize(
    "api_ctx,table,expect_ctx,expect_basis",
    [
        # The table out-bids a cloud endpoint that under-reports, so the number
        # RETURNED came from the model's name even though a server did answer.
        # Labelling this `reported` is the one subtle mistake available here,
        # and a mutation that made it survived until this case existed.
        (8_192, 200_000, 200_000, mc.BASIS_KNOWN_TABLE),
        # The endpoint reports more than the table knows: its number wins, and
        # it is a measurement.
        (400_000, 200_000, 400_000, mc.BASIS_REPORTED),
    ],
)
def test_the_basis_follows_the_number_that_won(monkeypatch, api_ctx, table,
                                               expect_ctx, expect_basis):
    monkeypatch.setattr(mc, "_configured_endpoint_kind", lambda url: None)
    monkeypatch.setattr(mc, "is_local_endpoint", lambda url: False)
    monkeypatch.setattr(mc, "_lookup_known", lambda model: table)

    class _R:
        is_success = True

        @staticmethod
        def json():
            return {"data": [{"id": "dual", "context_length": api_ctx}]}

    monkeypatch.setattr(mc.paced_http, "get_sync", lambda url, **k: _R())
    ctx, known, basis = mc.get_context_length_basis("https://cloud.example/v1", "dual")
    assert (ctx, known, basis) == (expect_ctx, True, expect_basis)


# ── the two fields cannot drift apart ──────────────────────────────────────


@pytest.mark.parametrize("basis", mc.CONTEXT_BASES)
def test_known_is_exactly_whether_the_basis_proves_anything(monkeypatch, basis):
    """`Law 7`. Not two fields a later edit can set inconsistently."""
    monkeypatch.setattr(
        mc, "_query_context_length",
        lambda url, model: (4242, basis != mc.BASIS_FALLBACK, basis))
    monkeypatch.setattr(mc, "is_local_endpoint", lambda url: True)
    ctx, known, got = mc.get_context_length_basis("http://x/v1", "m")
    assert got == basis
    assert known is (basis != mc.BASIS_FALLBACK)
    # And the two-value facade still answers the same thing, so no caller moved.
    assert mc.get_context_length_known("http://x/v1", "m") == (ctx, known)


def test_every_return_in_the_query_carries_a_basis_from_the_vocabulary():
    """Read from the source, because a branch added later is the way a third
    spelling gets in. Thirteen `return` statements, every one of them labelled."""
    import ast

    src = (ROOT / "src" / "model_context.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    func = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_query_context_length")
    returns = [n for n in ast.walk(func) if isinstance(n, ast.Return)]
    assert len(returns) >= 8, f"only {len(returns)} returns found; the walk is wrong"
    allowed = {"BASIS_REPORTED", "BASIS_KNOWN_TABLE", "BASIS_FALLBACK"}
    for node in returns:
        assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 3, (
            f"a return in _query_context_length is not a 3-tuple "
            f"(line {node.lineno})")
        # Only the basis names, because the third element may be a conditional
        # (`BASIS_REPORTED if result == api_ctx else BASIS_KNOWN_TABLE`) whose
        # other Names are the window being compared.
        names = {n.id for n in ast.walk(node.value.elts[2])
                 if isinstance(n, ast.Name) and n.id.startswith("BASIS_")}
        assert names and names <= allowed, (
            f"the basis at line {node.lineno} is not one of {sorted(allowed)}: {names}")
        # And no bare string: the vocabulary is the constants, not their values.
        literals = {n.value for n in ast.walk(node.value.elts[2])
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not literals, (
            f"the basis at line {node.lineno} is a literal {literals}; use the constant")


# ── the budget, and the receipt ────────────────────────────────────────────


def test_the_budget_helper_and_the_old_one_agree_on_the_number(monkeypatch):
    """One branch, two spellings — the row's own warning about binding a flag
    to a value from a *different* lookup (#4122)."""
    for basis in mc.CONTEXT_BASES:
        mc._context_cache.clear()
        monkeypatch.setattr(
            mc, "_query_context_length",
            lambda url, model, _b=basis: (7777, _b != mc.BASIS_FALLBACK, _b))
        monkeypatch.setattr(mc, "is_local_endpoint", lambda url: True)
        plain = mc.budget_context_for_model("http://x/v1", "m")
        value, got = mc.budget_context_basis("http://x/v1", "m")
        assert value == plain, f"{basis}: {value} != {plain}"
        if basis == mc.BASIS_FALLBACK:
            assert (value, got) == (0, mc.BASIS_FALLBACK)
        else:
            assert (value, got) == (7777, basis)


def test_a_probe_error_returns_the_callers_fallback_and_says_it_proves_nothing(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(mc, "get_context_length_basis", boom)
    assert mc.budget_context_basis("http://x/v1", "m", fallback=1234) == (
        1234, mc.BASIS_FALLBACK)


def test_the_suite_record_carries_the_basis_to_the_receipt():
    suite = plan_tool_suite(
        ["a", "b"], cost=lambda n: 1, room=100,
        window=32768, window_known=True, window_basis=mc.BASIS_KNOWN_TABLE)
    assert suite.window_basis == mc.BASIS_KNOWN_TABLE
    assert suite.as_record()["basis"] == mc.BASIS_KNOWN_TABLE
    # And on the narrowing branch, which is the one a reader cares about.
    narrow = plan_tool_suite(
        ["a", "b", "c"], cost=lambda n: 50, room=60,
        window=0, window_known=False, window_basis=mc.BASIS_FALLBACK)
    assert narrow.partial and narrow.as_record()["basis"] == mc.BASIS_FALLBACK


def test_the_suite_only_ever_holds_a_basis_from_the_vocabulary():
    """`src/tool_index.py` carries the field but not the list, so this is the
    coupling — asserted, rather than a second copy of three strings."""
    assert ToolSuite().window_basis == "", (
        "an unset basis is empty, which is a different statement from `fallback`")
    for basis in mc.CONTEXT_BASES:
        assert ToolSuite(window_basis=basis).as_record()["basis"] == basis


def test_the_event_payload_keeps_the_basis(monkeypatch):
    """`src/events.record_run_config` — the slot the row names."""
    import src.events as events

    captured = {}
    monkeypatch.setattr(events, "record_event",
                        lambda *a, **k: captured.update(k) or True)
    suite = plan_tool_suite(["a"], cost=lambda n: 1, room=10, window=8192,
                            window_known=True, window_basis=mc.BASIS_REPORTED)
    events.record_run_config(session_id="s", owner="o", suite=suite.as_record())
    payload = captured.get("detail") or {}
    stored = (payload.get("suite") or {}) if isinstance(payload, dict) else {}
    assert stored.get("basis") == mc.BASIS_REPORTED, (sorted(captured), stored)
    # The slot the row names: beside `window_known`, not instead of it.
    assert stored.get("window_known") is True and stored.get("window") == 8192
