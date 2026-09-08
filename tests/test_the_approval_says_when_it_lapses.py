# SPDX-License-Identifier: AGPL-3.0-or-later
r"""`P4-21` — the ten-minute deadline nobody was told about.

Every approval card has a ten-minute life. The TTL was computed on every one of
them and sent on none, so the card sat there looking live, and answering it after
the deadline produced a 409 reading *"This tool approval could not be consumed."*

That sentence was the same for **four** different things, and only one of them
is fixable by asking again:

  * the card lapsed — ask again and approve the new one;
  * the id is not on file — already answered, or superseded in this chat;
  * it belongs to a different account or chat;
  * the decision value is not one this card offers.

`consume` returned a bare `None` for all four, which is the same shape as
`P4-17`'s verifier and `P4-12`'s approved flag: a value that cannot say which of
several unlike things happened. It reports through an out-parameter, so the four
existing callers keep the contract they had.

**`expired` is reported only to the owner of the pending action.** The ownership
check inside `consume` exists so a leaked or guessed id cannot invalidate
somebody else's pending action; telling a stranger "that one expired" would make
the same id an oracle for whether it was ever real.
"""

import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from src.tool_approvals import ToolApprovalStore
from src.tool_capabilities import capabilities_for_action

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "chatRenderer.js"


def _store(ttl=600):
    return ToolApprovalStore(ttl_seconds=ttl)


def _pending(store, *, owner="alice", session="s-1"):
    return store.create(
        owner=owner, session_id=session, origin_run_id="run-1",
        tool_name="bash", content="rm -rf /tmp/scratch", workspace=None,
        external_untrusted_context_seen=False,
        capabilities=capabilities_for_action("bash", "rm -rf /tmp/scratch"),
    )


# ── the deadline reaches the card ─────────────────────────────────────────────


def test_the_card_carries_its_deadline():
    store = _store()
    payload = _pending(store).public_payload(reason="because")
    assert payload["expires_at"] > time.time()
    assert payload["ttl_seconds"] == 600


def test_the_deadline_is_absolute_and_not_a_countdown():
    # A card is rebuilt from history minutes after it was made. A
    # remaining-seconds figure baked in at render time would start again from
    # ten minutes every reload, which is a worse lie than saying nothing.
    store = _store()
    pending = _pending(store)
    first = pending.public_payload(reason="because")["expires_at"]
    time.sleep(0.05)
    again = pending.public_payload(reason="because")["expires_at"]
    assert first == again


def test_a_shorter_ttl_is_reported_as_the_shorter_one():
    # The store takes a TTL; the card must not quote the default.
    payload = _pending(_store(ttl=30)).public_payload(reason="because")
    assert payload["ttl_seconds"] == 30


# ── the four ways it fails ────────────────────────────────────────────────────


def test_a_lapsed_card_says_it_lapsed():
    store = _store(ttl=1)
    pending = _pending(store)
    time.sleep(1.1)
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="approve", owner="alice",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == "expired"


def test_an_id_nobody_has_heard_of_is_not_called_expired():
    store = _store()
    outcome: dict = {}
    assert store.consume("not-a-real-id", decision="approve", owner="alice",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == "unknown"


def test_somebody_elses_card_says_so_and_not_more():
    store = _store()
    pending = _pending(store)
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="approve", owner="mallory",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == "not_yours"
    # …and it is still there for its owner, because a stranger's click must not
    # consume it.
    assert store.consume(pending.approval_id, decision="approve", owner="alice",
                         session_id="s-1") is not None


def test_a_lapsed_card_does_not_tell_a_stranger_it_was_ever_real():
    # The oracle. The ownership check exists so a guessed id cannot invalidate
    # somebody's pending action; "that one expired" would leak the same fact
    # the check is there to withhold.
    store = _store(ttl=1)
    pending = _pending(store)
    time.sleep(1.1)
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="approve", owner="mallory",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == "unknown", (
        "a stranger was told a real approval had existed"
    )


def test_another_chats_lapsed_card_is_not_reported_to_this_one():
    # Same owner, different chat. `session_id` is half of the ownership check
    # for the same reason `owner` is — the id travels in a URL and a card in one
    # thread must not be answerable, or even acknowledged, from another.
    store = _store(ttl=1)
    pending = _pending(store, owner="alice", session="s-1")
    time.sleep(1.1)
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="approve", owner="alice",
                         session_id="a-different-chat", outcome=outcome) is None
    assert outcome["reason"] == "unknown"


def test_a_decision_the_card_does_not_offer_says_that():
    store = _store()
    pending = _pending(store)
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="perhaps", owner="alice",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == "bad_decision"


def test_a_caller_that_asks_for_no_reason_gets_the_contract_it_had():
    # Four callers reach `consume` and none of them passes `outcome`.
    store = _store(ttl=1)
    pending = _pending(store)
    time.sleep(1.1)
    assert store.consume(pending.approval_id, decision="approve", owner="alice",
                         session_id="s-1") is None


def test_a_successful_consume_still_succeeds_and_says_nothing():
    store = _store()
    pending = _pending(store)
    outcome: dict = {}
    grant = store.consume(pending.approval_id, decision="approve", owner="alice",
                          session_id="s-1", outcome=outcome)
    assert grant is not None
    assert outcome == {}, "a working approval reported a failure reason"


def test_a_consumed_card_answered_twice_is_not_called_expired():
    # The commonest of the four in practice: two clicks, or a reload and a
    # click. It is gone because it worked, and "expired" would be wrong.
    store = _store()
    pending = _pending(store)
    assert store.consume(pending.approval_id, decision="approve", owner="alice",
                         session_id="s-1") is not None
    outcome: dict = {}
    assert store.consume(pending.approval_id, decision="approve", owner="alice",
                         session_id="s-1", outcome=outcome) is None
    assert outcome["reason"] == "unknown"


# ── what the person is told ───────────────────────────────────────────────────


@pytest.mark.parametrize("reason, must_contain", [
    ("expired", "expired"),
    ("unknown", "no longer on file"),
    ("not_yours", "different account or chat"),
    ("bad_decision", "not a choice"),
])
def test_each_reason_gets_its_own_sentence(reason, must_contain):
    from routes.chat_helpers import approval_consume_message
    assert must_contain in approval_consume_message(reason)


def test_only_the_fixable_one_tells_you_what_to_do():
    from routes.chat_helpers import approval_consume_message
    assert "Ask again" in approval_consume_message("expired")


@pytest.mark.parametrize("reason", [None, "", "something new"])
def test_a_reason_nobody_wrote_a_sentence_for_keeps_the_old_one(reason):
    from routes.chat_helpers import approval_consume_message
    assert approval_consume_message(reason) == "This tool approval could not be consumed."


def test_the_route_asks_for_the_reason_and_uses_it():
    routes = (_REPO / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    assert "outcome=_approval_outcome," in routes
    assert 'approval_consume_message(_approval_outcome.get("reason"))' in routes
    assert routes.count('"This tool approval could not be consumed."') == 0, (
        "the one-size-fits-all sentence is still hard-coded in the route"
    )


# ── the line on the card ──────────────────────────────────────────────────────


pytestmark_node = pytest.mark.skipif(not shutil.which("node"),
                                     reason="node binary not on PATH")


@pytest.fixture(scope="module")
def expiry_line(tmp_path_factory):
    """Run the real `approvalExpiryLine` against a two-property fake element.

    `chatRenderer.js` imports half the app, so the function is lifted out by
    source rather than by import — and the test then executes it, which is the
    part that matters. A copy of the logic here would be a test of my copy.
    """
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    src = _MODULE.read_text(encoding="utf-8")
    start = src.index("export function approvalExpiryLine(")
    end = src.index("\nexport function renderAskUserCard(", start)
    body = src[start:end].replace("export function", "function", 1)
    d = tmp_path_factory.mktemp("expiryline")
    (d / "case.mjs").write_text(body + """
const made = [];
globalThis.document = { createElement: () => {
  const el = { className: '', textContent: '', isConnected: true,
               classList: { add(c) { el.className += ' ' + c; } } };
  made.push(el);
  return el;
} };
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
const at = Number(process.argv[2]);
const line = approvalExpiryLine(Number.isNaN(at) ? process.argv[2] : at);
console.log(JSON.stringify(line
  ? { text: line.textContent, className: line.className.trim() }
  : null));
""", encoding="utf-8")
    return d


def _line(expiry_line: Path, value):
    proc = subprocess.run(["node", "case.mjs", str(value)], cwd=expiry_line,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    import json
    return json.loads([ln for ln in proc.stdout.splitlines() if ln.strip()][-1])


def test_a_live_card_counts_down(expiry_line):
    out = _line(expiry_line, time.time() + 605)
    assert out["text"].startswith("Expires in 10m")


def test_the_last_minute_drops_the_minutes(expiry_line):
    out = _line(expiry_line, time.time() + 42)
    assert out["text"] == "Expires in 42s"


def test_a_lapsed_card_says_so_instead_of_looking_live(expiry_line):
    # The row's own complaint: it stopped working and said nothing. A card that
    # looks answerable and 409s on the click is worse than one that says it is
    # too late.
    out = _line(expiry_line, time.time() - 5)
    assert "expired" in out["text"]
    assert "expired" in out["className"]


@pytest.mark.parametrize("value", [0, -1, "", "soon", "NaN"])
def test_a_card_with_no_deadline_gets_no_line(expiry_line, value):
    # Every other kind of ask-user card, and any approval from a build that
    # predates the field.
    assert _line(expiry_line, value) is None
