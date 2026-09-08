# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-05` — every model that was tried, and what each one said.

When the selected model fails and another answers, the stream carries the whole
chain: each candidate, its index, and the status it failed with. Exactly one
field of it reached a reader — `reason`, inside a **six-second toast** — and the
reply then sat under a role line reading "llama (fallback)" with no way to say
what happened to the model that was actually selected.

Two gaps, and the second is the one worth naming: the chain was attached **only
when a later candidate answered**. When *every* candidate failed — the case
where knowing what was tried matters most — the terminal error carried one
status and nothing else.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from src.llm_core import _failure_chain

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "chatRenderer.js"


# ── the chain on the wire ─────────────────────────────────────────────────────


def test_the_chain_is_one_shape_built_once():
    chain = _failure_chain([
        {"candidate_index": 0, "model": "gpt-4o", "status": 502, "reason": "bad gateway"},
        {"candidate_index": 1, "model": "claude", "status": 429, "reason": "rate limited"},
    ])
    assert chain == [
        {"candidate_index": 0, "model": "gpt-4o", "status": 502},
        {"candidate_index": 1, "model": "claude", "status": 429},
    ]


def test_the_sentence_about_the_first_failure_is_not_in_the_chain():
    # `reason` is a sentence about one hop. The chain is a list of statuses, and
    # a sentence per hop would be a paragraph where a glance is wanted.
    chain = _failure_chain([{"model": "m", "status": 500, "reason": "a long sentence"}])
    assert "reason" not in chain[0]


@pytest.mark.parametrize("failures", [None, [], [None], ["nonsense"], [{}]])
def test_junk_does_not_become_a_hop(failures):
    for hop in _failure_chain(failures):
        assert isinstance(hop, dict)


def test_the_terminal_error_carries_the_chain_too():
    # The gap that matters. The chain was attached at the one site that reports
    # a *successful* fallback, so "everything failed" reported a single status.
    core = (_REPO / "src" / "llm_core.py").read_text(encoding="utf-8")
    # Sliced to the end of the dict, not to the next `return` — "All model
    # candidates **return**ed no substantive output" contains that word, so the
    # obvious slice ended three characters in and asserted about nothing.
    start = core.index('"error": "All model candidates returned no substantive output"')
    terminal = core[start:core.index("}) + ", start)]
    assert '"failures": _failure_chain(failures)' in terminal


def test_the_successful_fallback_uses_the_same_builder():
    core = (_REPO / "src" / "llm_core.py").read_text(encoding="utf-8")
    # Three: the definition and the two call sites. Counting the bare name
    # would also match the definition, so the number is stated with what it
    # counts rather than left to be guessed at.
    assert core.count("_failure_chain(failures)") == 3
    assert core.count("def _failure_chain(failures)") == 1
    assert '"candidate_index": failure["candidate_index"],' not in core, (
        "the inlined copy is back, which is how the two sites came to disagree"
    )


# ── the chain is saved ────────────────────────────────────────────────────────


_ROUTES = (_REPO / "routes" / "chat_routes.py").read_text(encoding="utf-8")


def test_both_stream_branches_capture_the_chain():
    # Chat mode and agent mode each have their own fallback handler, and a chain
    # captured in one and not the other is a reply that explains itself in chat
    # and not in agent.
    assert _ROUTES.count('"failures": data.get("failures") or [],') == 2
    assert _ROUTES.count("_fallback_chain = None") == 2


def test_every_save_path_carries_it():
    assert _ROUTES.count("fallback_chain=_fallback_chain,") == 3


class _FakeSession:
    def __init__(self):
        self.messages = []
        self.model = "m"

    def add_message(self, message):
        self.messages.append(message)


class _FakeManager:
    def __init__(self):
        self.saved = 0

    def save_sessions(self):
        self.saved += 1


def _save(monkeypatch, **kwargs):
    import core.database as database
    from routes.chat_helpers import save_assistant_response
    monkeypatch.setattr(database, "update_session_last_accessed", lambda sid: None,
                        raising=False)
    sess, manager = _FakeSession(), _FakeManager()
    save_assistant_response(sess, manager, "fallback-test", "the answer",
                            {"model": "llama"}, **kwargs)
    assert sess.messages
    return sess.messages[-1].metadata


def test_a_fallback_reply_is_saved_with_its_chain(monkeypatch):
    md = _save(monkeypatch, fallback_chain={
        "selected_model": "gpt-4o", "answered_by": "llama",
        "failures": [{"model": "gpt-4o", "status": 502}],
    })
    assert md["fallback_chain"]["answered_by"] == "llama"
    assert md["fallback_chain"]["failures"][0]["status"] == 502


def test_an_ordinary_reply_saves_no_chain(monkeypatch):
    assert "fallback_chain" not in _save(monkeypatch)
    assert "fallback_chain" not in _save(monkeypatch, fallback_chain=None)
    # A chain with nothing that answered is not a fallback that happened.
    assert "fallback_chain" not in _save(
        monkeypatch, fallback_chain={"answered_by": None, "failures": []})


# ── the chain on screen ───────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def hops(tmp_path_factory):
    """Execute the real hop builder, lifted out by source.

    `chatRenderer.js` imports half the app; the two functions under test are
    pure. Re-implementing them in the test would be a test of my copy.
    """
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    src = _MODULE.read_text(encoding="utf-8")
    start = src.index("export function fallbackChainHops(")
    end = src.index("\n/**\n * The footer pill popover, once.")
    body = src[start:end].replace("export function", "function")
    d = tmp_path_factory.mktemp("fallbackchain")
    (d / "case.mjs").write_text(body + """
const chain = JSON.parse(process.argv[2]);
const built = fallbackChainHops(chain);
console.log(JSON.stringify({ hops: built, summary: fallbackChainSummary(built) }));
""", encoding="utf-8")
    return d


def _render(hops: Path, chain):
    proc = subprocess.run(["node", "case.mjs", json.dumps(chain)], cwd=hops,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_the_chain_reads_the_way_the_row_asks_for(hops):
    out = _render(hops, {
        "selected_model": "gpt-4o", "answered_by": "llama",
        "failures": [{"model": "gpt-4o", "status": 502},
                     {"model": "claude", "status": 429}],
    })
    assert [h["label"] for h in out["hops"]] == [
        "gpt-4o ✗502", "claude ✗429", "llama ✓"]


def test_the_model_that_answered_is_the_one_marked(hops):
    out = _render(hops, {"answered_by": "llama",
                         "failures": [{"model": "gpt-4o", "status": 502}]})
    assert [h["ok"] for h in out["hops"]] == [False, True]


def test_a_failure_with_no_status_says_so_rather_than_inventing_one(hops):
    out = _render(hops, {"answered_by": "llama",
                         "failures": [{"model": "gpt-4o"}]})
    assert out["hops"][0]["label"] == "gpt-4o ✗?"


def test_a_nameless_candidate_is_not_a_hop(hops):
    out = _render(hops, {"answered_by": "llama",
                         "failures": [{"status": 502}, {"model": "claude", "status": 429}]})
    assert [h["model"] for h in out["hops"]] == ["claude", "llama"]


def test_a_chain_that_never_answered_still_lists_what_was_tried(hops):
    # The terminal-error case. Nothing answered, so there is no tail — and the
    # list of what was tried is the whole of the information.
    out = _render(hops, {"answered_by": None,
                         "failures": [{"model": "gpt-4o", "status": 502},
                                      {"model": "claude", "status": 429}]})
    assert [h["label"] for h in out["hops"]] == ["gpt-4o ✗502", "claude ✗429"]
    assert all(h["ok"] is False for h in out["hops"])


def test_the_pill_says_how_many_were_tried_first(hops):
    one = _render(hops, {"answered_by": "llama",
                         "failures": [{"model": "gpt-4o", "status": 502}]})
    two = _render(hops, {"answered_by": "llama",
                         "failures": [{"model": "gpt-4o", "status": 502},
                                      {"model": "claude", "status": 429}]})
    assert one["summary"] == "Fallback · 1 tried first"
    assert two["summary"] == "Fallback · 2 tried first"


def test_junk_from_the_wire_produces_no_hops(hops):
    for chain in ({}, {"failures": "nonsense"}, {"failures": None}):
        assert _render(hops, chain)["hops"] == []


# ── both surfaces ─────────────────────────────────────────────────────────────


def test_the_live_stream_keeps_the_chain_and_the_toast():
    chat = (_REPO / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert "holder._fallbackChain = {" in chat
    assert "uiModule.showToast('Fallback: '" in chat, (
        "the toast is the signal in the moment; the pill is the record after it"
    )


def test_a_reloaded_reply_still_has_the_chain():
    renderer = _MODULE.read_text(encoding="utf-8")
    assert renderer.count("_fallbackChain = metadata.fallback_chain") == 2


def test_the_pill_goes_through_the_one_popover():
    renderer = _MODULE.read_text(encoding="utf-8")
    assert "bindFooterPopover(pill, 'fallback-chain-detail'" in renderer
    assert renderer.count("export function bindFooterPopover") == 1


def test_the_model_names_are_escaped_before_they_reach_the_page():
    # Model names come from endpoint configuration, which an admin types.
    renderer = _MODULE.read_text(encoding="utf-8")
    block = renderer[renderer.index("const chain = msgElement._fallbackChain;"):]
    block = block[:block.index("footer.appendChild(actions);")]
    assert "esc(fallbackChainSummary(hops))" in block
    assert "row.textContent = hop.label;" in block, (
        "the rows are built with innerHTML instead of textContent"
    )
