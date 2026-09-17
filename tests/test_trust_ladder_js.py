# SPDX-License-Identifier: AGPL-3.0-or-later
"""P7-03 / P7-04 / P7-05 — the trust ladder, and "always allow this".

Two user-facing surfaces, driven under node against the real files in the
sandbox pattern `tests/test_chat_steer_js.py` established and
`tests/test_tool_effect_surfaces_js.py` extended: stub modules plus a DOM shim
beside a copy of the unmodified source, which is then imported and exercised.
The shim, the sandbox builder and the runner are imported from that file rather
than copied — one harness, one place it can be fixed.

What is pinned, and why each is a defect if it breaks:

  * **the ladder offers exactly three options**, and their values are exactly
    the three members of `TrustRung` (`src/tool_capabilities.py`). The design at
    `.pantheon/design/pantheon-v10.html:1719-1727` draws five; two of them —
    "plan only" and "auto-pilot" — are not gate settings, and a radio button
    offering either would be a control lying about what it does. Both may still
    be *mentioned* in the prose, and are, so the test separates what is offered
    from what is said;

  * **the default is first, and marked as what the install already has.** That
    order is `P7-05`'s acceptance criterion — *"Auto-Pilot as the existing
    default with the ladder added below it, never above"* — not a layout
    preference. A rung drawn above the default tells a reader that something
    looser was being withheld, which is the belief the correction exists to
    prevent;

  * **every option's sentence names a consequence, in the reader's words.**
    `Law 15` is why this project exists, and `P7-06`'s refuter set the standard
    one row ago: *"the honest answer is yes — from the sentence, not from the
    design."* The names are jargon by necessity; the sentences carry them, and
    carry no mechanism vocabulary and no enum identifier;

  * **the strict rungs state their cost.** "Ask every time" means a
    confirmation before everything that writes, runs, sends or deletes. Someone
    who turns it on without being told will turn it off angrily and trust the
    next control less;

  * **the "always allow" affordance is absent unless two real things hold** — the
    server has said it takes rules, and the rung is the one that reads them.
    `Law 13` is the law this programme breaks most often, and `P3-13` is the row
    where a gate against half-wiring was itself half-wired;

  * **the distinction survives greyscale.** `P7-06`'s refutation measured the
    previous attempt at 2.11:1 on `paper` for the one line that mattered most
    while the harmless line beside it sat at 11.05:1, and on `terminal` and
    `retrowave` `--fg` and `--red` are the same hex. Every CSS assertion below
    reads *values*, never property names: a version of `P7-06`'s tests that
    compared names let a mutation collapse the whole visual ladder while staying
    green.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

# One harness. `_DOM` is the shim, `_make_sandbox`/`_run` build and drive it,
# and the colour helpers are the ones that measured `P7-06`'s defect.
from test_tool_effect_surfaces_js import (  # noqa: E402
    _CARD_SHIM,
    _CARD_STUBS,
    _contrast,
    _make_sandbox,
    _px,
    _resolve,
    _run,
    _themes,
)
from tests.helpers.source_text import blank, blank_text  # B290

ROOT = Path(__file__).resolve().parents[1]
TRUST_LADDER = ROOT / "static" / "js" / "trustLadder.js"
CHAT_RENDERER = ROOT / "static" / "js" / "chatRenderer.js"
STYLE = ROOT / "static" / "style.css"
INDEX = ROOT / "static" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The three members of `TrustRung`, in the order the ladder draws them: the
# default first, the two stricter rungs below it.
RUNGS = ("gate_on_untrusted", "allow_listed", "ask_every_time")
DEFAULT_RUNG = "gate_on_untrusted"
# The two rungs of the design's five that are deliberately not gate settings.
NOT_RUNGS = ("plan only", "plan-only", "auto-pilot", "auto pilot", "autopilot")


# ── Ladder sandbox ──────────────────────────────────────────────────────────

_LADDER_SHIM = r"""
import { installDom, Node } from './dom.js';
export const document = installDom();
export { Node };

const card = document.body.appendChild(new Node('div'));
card.setAttribute('id', 'trust-ladder-card');
card.hidden = true;
const host = card.appendChild(new Node('div'));
host.setAttribute('id', 'trust-ladder');
export { card, host };

/** Every request the module makes, and the canned reply each one gets. */
export const posts = [];
let _reply = { ok: true, status: 200, body: {} };
let _rules = { ok: true, status: 200, body: { rules: [], match_kinds: ['any', 'exact', 'prefix'] } };
let _revoke = { ok: true, status: 200, body: { status: 'revoked' } };
export function replyWith(next) { _reply = next; }
/** `GET /api/tool-allow-rules` — the probe, and the list under the ladder. */
export function rulesReplyWith(next) { _rules = next; }
/** `DELETE /api/tool-allow-rules/{id}`. */
export function revokeReplyWith(next) { _revoke = next; }
globalThis.fetch = async (url, init) => {
  const method = String(((init || {}).method) || 'GET').toUpperCase();
  posts.push({ url: String(url), method, init: init || {} });
  let reply = _reply;
  if (String(url).indexOf('/api/tool-allow-rules') >= 0) {
    reply = method === 'DELETE' ? _revoke : _rules;
  }
  return {
    ok: reply.ok !== false,
    status: reply.status || 200,
    json: async () => reply.body,
  };
};

/** The ladder as a person reads it off the screen. */
export function readLadder() {
  const box = document.querySelector('.trust-ladder');
  if (!box) return null;
  const rows = box.querySelectorAll('.trust-rung');
  const one = (row) => {
    const cost = row.querySelector('.trust-rung-cost');
    const badge = row.querySelector('.trust-rung-badge');
    const sentence = row.querySelector('.trust-rung-sentence');
    const input = row.querySelector('.trust-rung-input');
    return {
      value: row.dataset.rungValue || null,
      band: row.dataset.rungCost || null,
      current: row.dataset.rungCurrent === 'true',
      name: row.querySelector('.trust-rung-name').textContent,
      badge: badge ? badge.textContent : null,
      sentence: sentence ? sentence.textContent : null,
      cost: cost ? cost.textContent : null,
      // Raw `_html` behind the two sentences, deliberately not read through the
      // `textContent` getter — that getter strips tags out of `_html`, so a
      // switch from `textContent` to `innerHTML` reads back identically through
      // text. '' if and only if the renderer used `textContent`.
      sentenceHtml: sentence ? sentence._html : null,
      costHtml: cost ? cost._html : null,
      checked: !!(input && input.checked),
      inputValue: input ? input.value : null,
      inputType: input ? input.type : null,
    };
  };
  return {
    title: box.querySelector('.trust-ladder-title').textContent,
    intro: box.querySelector('.trust-ladder-intro').textContent,
    note: box.querySelector('.trust-ladder-note').textContent,
    status: box.querySelector('.trust-ladder-status').textContent,
    rows: rows.map(one),
    text: box.readable,
    cardHidden: !!card.hidden,
  };
}

export function pick(value) {
  const row = document.querySelector('.trust-rung[data-rung-value="' + value + '"]');
  const input = row.querySelector('.trust-rung-input');
  input.checked = true;
  input.dispatchEvent(new Event('change'));
  return input;
}

/** The standing-rule list under the ladder, as a person reads it off the screen. */
export function readRules() {
  const box = document.querySelector('.allow-rule-list');
  if (!box) return null;
  const text = (node) => (node ? node.textContent : null);
  const empty = box.querySelector('.allow-rule-list-empty');
  return {
    hidden: !!box.hidden,
    title: text(box.querySelector('.allow-rule-list-title')),
    hint: text(box.querySelector('.allow-rule-list-hint')),
    status: text(box.querySelector('.allow-rule-list-status')),
    empty: text(empty),
    rows: box.querySelectorAll('.allow-rule-row').map((row) => {
      const button = row.querySelector('.allow-rule-revoke');
      const sentence = row.querySelector('.allow-rule-row-sentence');
      return {
        id: row.dataset.ruleId || null,
        match: row.dataset.ruleMatch || null,
        label: text(row.querySelector('.allow-rule-row-label')),
        detail: text(row.querySelector('.allow-rule-row-detail')),
        sentence: text(sentence),
        // Raw `_html`: '' if and only if the renderer used `textContent`.
        sentenceHtml: sentence ? sentence._html : null,
        when: text(row.querySelector('.allow-rule-row-when')),
        revoke: text(button),
        revokeLabel: button ? button.getAttribute('aria-label') : null,
        disabled: !!(button && button.disabled),
      };
    }),
    text: box.readable,
  };
}

export function revoke(id) {
  const row = document.querySelector('.allow-rule-row[data-rule-id="' + id + '"]');
  const button = row.querySelector('.allow-rule-revoke');
  button.dispatchEvent(new Event('click'));
  return button;
}

/** Enough turns for a save, a probe and a revoke to have settled. */
export async function settle() {
  for (let i = 0; i < 8; i += 1) await new Promise((r) => setTimeout(r, 0));
}
"""

_LADDER_APPCONFIG = """
let _settings = {};
export function setSettings(next) { _settings = next; }
export let invalidated = 0;
export function getSettings() { return Promise.resolve(_settings); }
export function invalidateSettings() { invalidated += 1; }
export function getTools() { return Promise.resolve({ tools: [] }); }
"""


# `trustLadder.js` reports a failed rule write through the app's own toast and
# error channels, because the card it was chosen on is gone by then. The ladder
# never uses them; the stub exists so the import resolves.
_LADDER_UI = """
export const toasts = [];
export const errors = [];
export default {
  esc: (s) => String(s == null ? '' : s),
  showToast: (m) => { toasts.push(String(m)); },
  showError: (m) => { errors.push(String(m)); },
};
"""


@pytest.fixture(scope="module")
def ladder_sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("trustladder"),
        TRUST_LADDER,
        _LADDER_SHIM,
        {"appConfig.js": _LADDER_APPCONFIG, "ui.js": _LADDER_UI},
    )


_LADDER_PREAMBLE = (
    "import { document, host, card, readLadder, pick, posts, replyWith,"
    " readRules, revoke, rulesReplyWith, revokeReplyWith, settle }"
    " from './shim.js';\n"
    "import { setSettings } from './appConfig.js';\n"
)


def _ladder(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _LADDER_PREAMBLE, script)


# The settings payload a server that has `P7-03` returns, and one from a server
# that does not. The difference is the whole capability check.
_HAS_KEY = "setSettings({ trust_rung: 'gate_on_untrusted', tts_enabled: true });"
_NO_KEY = "setSettings({ tts_enabled: true });"
_IMPORT = "await import('./trustLadder.js');\nawait (await import('./trustLadder.js')).trustSettingsReady();\n"


# ── Job 1: what the ladder offers ───────────────────────────────────────────


def test_the_ladder_offers_exactly_the_three_rungs_that_are_gate_settings(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    values = [row["value"] for row in out["rows"]]
    assert values == list(RUNGS), values
    assert [row["inputValue"] for row in out["rows"]] == list(RUNGS)
    assert {row["inputType"] for row in out["rows"]} == {"radio"}


def test_the_default_leads_the_ladder_and_says_it_is_what_you_already_have(ladder_sandbox):
    """`P7-05`: the ladder is added below current behaviour, never above it."""

    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    first = out["rows"][0]
    assert first["value"] == DEFAULT_RUNG
    assert first["current"] is True
    assert first["checked"] is True
    # Nothing above it, and nothing else claiming to be current.
    assert [row["current"] for row in out["rows"]] == [True, False, False]
    assert [row["badge"] for row in out["rows"][1:]] == [None, None]

    badge = (first["badge"] or "").lower()
    assert badge, "the default rung must be marked as the current behaviour"
    assert "now" in badge or "already" in badge or "current" in badge, badge
    # And the sentence, not only the badge, says so — a badge is a decoration a
    # screen reader may reach after the sentence, and the claim has to be in the
    # prose that is read first.
    assert "already" in first["sentence"].lower()


def test_plan_only_and_auto_pilot_are_mentioned_but_never_offered(ladder_sandbox):
    """Two of the design's five rungs are not gate settings. Saying so is fine;
    offering a radio button for either is the control lying about what it does."""

    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    assert len(out["rows"]) == 3
    for row in out["rows"]:
        haystack = f"{row['name']} {row['value']}".lower()
        for phrase in NOT_RUNGS:
            assert phrase not in haystack, f"{phrase!r} is offered as a rung: {row}"

    # Mentioned, though — a person has to be told where plan mode went and that
    # auto-pilot is the thing they already have.
    prose = f"{out['intro']} {out['note']} {out['rows'][0]['sentence']}".lower()
    assert "auto-pilot" in prose
    assert "plan mode" in prose
    assert "plan button" in prose


# The vocabulary of the implementation. None of it may appear in a sentence a
# person is expected to decide from. The option *names* are exempt: they are the
# design's names and the enum's names, and giving the product a second set would
# be worse than the jargon. The sentences are what carry them.
_MECHANISM = (
    "rung", "gate", "taint", "untrusted", "enum", "effect", "capabilit",
    "allowlist", "allow-list", "regex", "pattern", "policy", "boolean",
    "trustrung", "api", "endpoint", "payload",
)
# The enum's own identifiers, which must appear nowhere a person can read.
_IDENTIFIERS = RUNGS
# A sentence that names a consequence says what happens to the reader.
_CONSEQUENCE = (
    "stops and waits", "stops to ask", "does not interrupt", "goes ahead",
    "asks you", "stops asking",
)


def test_every_option_sentence_names_a_consequence_and_carries_no_identifier(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    for row in out["rows"]:
        sentence = row["sentence"] or ""
        assert len(sentence) >= 120, f"{row['value']}: a label, not a sentence: {sentence!r}"
        low = sentence.lower()
        assert any(mark in low for mark in _CONSEQUENCE), (
            f"{row['value']}: the sentence never says what happens to the "
            f"person reading it: {sentence!r}"
        )
        assert " you" in low or "your " in low, (
            f"{row['value']}: the sentence is about the system, not the reader"
        )
        for word in _MECHANISM:
            assert word not in low, (
                f"{row['value']}: {word!r} is the taxonomy's word, not a person's: {sentence!r}"
            )

    # And nowhere on the control — badge, intro, note, status, cost included.
    everything = " ".join(
        [out["title"], out["intro"], out["note"], out["status"], out["text"]]
        + [f"{r['badge'] or ''} {r['sentence'] or ''} {r['cost'] or ''}" for r in out["rows"]]
    ).lower()
    for identifier in _IDENTIFIERS:
        assert identifier not in everything, f"{identifier!r} is on screen"

    # The prose reaches the DOM as text and never as markup. `P7-06` shipped a
    # `textContent` -> `innerHTML` swap past a full green run because every
    # assertion went through text.
    for row in out["rows"]:
        assert row["sentenceHtml"] == ""
        assert row["costHtml"] in (None, "")


def test_the_strict_rungs_state_what_they_cost_and_the_default_has_no_price(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    by_value = {row["value"]: row for row in out["rows"]}

    # Changing nothing costs nothing, and inventing a price for the default
    # would push a reader off the setting they should stay on.
    assert by_value[DEFAULT_RUNG]["cost"] is None

    for value in ("allow_listed", "ask_every_time"):
        cost = by_value[value]["cost"] or ""
        assert len(cost) >= 80, f"{value}: the cost line is a gesture, not a price: {cost!r}"
        assert "cost" in cost.lower(), f"{value}: the cost line never says it is a cost"

    strictest = by_value["ask_every_time"]["cost"].lower()
    # The two things a person actually feels, both named with a number or an
    # explicit situation rather than a hedge.
    assert "twenty times" in strictest, "the repetition is not quantified"
    assert "away from the screen" in strictest, (
        "an unattended run stalling on this rung is the surprise that makes "
        "someone switch it off angrily; it has to be said before they choose"
    )

    milder = by_value["allow_listed"]["cost"].lower()
    assert "anything new still stops" in milder, (
        "the allow-list's price is that a new action still interrupts; without "
        "it the rung reads as a one-time approval"
    )


# The four verbs both strict rungs used to promise, and nothing else.
_WRITE_VERBS = ("saves a file", "runs code", "sends anything", "deletes anything",
                "saving a file", "running code", "sending anything", "deleting anything")
# The private reads the same effect set also gates, in a person's words.
_READS = ("mail", "calendar", "notes", "remembers")


def test_the_strict_rungs_promise_the_reads_their_gate_actually_stops(ladder_sandbox):
    """`documentation-is-false`, measured.

    Both strict rungs used to gate on `POST_EXTERNAL_BLOCKED_EFFECTS`, and that
    set carries `read_private` alongside the four write-ish effects, so reading
    your mail, your calendar, your notes and the agent's own memory of earlier
    chats all stopped and asked while the copy promised a confirmation "before
    it saves a file, runs code, sends anything or deletes anything" and no more.

    **This test read the wrong constant and would have gone on passing while
    the copy it guards became false** (`B19`). It asked whether `read_private`
    is in `POST_EXTERNAL_BLOCKED_EFFECTS` — which it still is, and must remain,
    because `FORBIDDEN.md` Part 2 forbids relaxing that gate. What the strict
    rungs consult while a run is untainted is now `RUNG_BLOCKED_EFFECTS`, and
    that is the set the sentences describe. The binding is only worth having if
    it points at the constant the copy is about.

    Bound to the effect set rather than to a wording, in both directions: if
    somebody puts `read_private` back into the untainted rung set, this fails
    and says the copy is under-promising.
    """

    from src.tool_capabilities import RUNG_BLOCKED_EFFECTS, ToolEffect

    gates_private_reads = ToolEffect.READ_PRIVATE in RUNG_BLOCKED_EFFECTS

    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)
    by_value = {row["value"]: row for row in out["rows"]}

    for value in ("allow_listed", "ask_every_time"):
        sentence = (by_value[value]["sentence"] or "").lower()
        # The four verbs stay: they are still true and still most of the cost.
        assert any(verb in sentence for verb in _WRITE_VERBS), value
        named = [word for word in _READS if word in sentence]
        if gates_private_reads:
            assert len(named) >= 3, (
                f"{value}: the rung stops and asks before reading your own "
                f"things, and the sentence still promises only the write verbs: "
                f"{by_value[value]['sentence']!r}"
            )
        else:
            # **Not silence.** The first draft of this branch asserted the
            # sentence must stop naming the reads at all, on the assumption
            # that naming them means gating them. That is the wrong binary: a
            # person on the strictest rung needs to know both halves — that
            # reading their own things does not stop and ask, AND that it
            # starts the moment anything comes in from outside, because that
            # transition is the one that surprises people (`Law 15`). Silence
            # would under-inform in exactly the direction the 2026-08-29
            # correction was trying to fix.
            assert len(named) >= 3, (
                f"{value}: the rung no longer stops private reads, and the "
                f"sentence has gone quiet about them instead of saying so: "
                f"{by_value[value]['sentence']!r}"
            )
            assert "outside" in sentence, (
                f"{value}: the sentence says the reads do not stop and ask, "
                f"and does not say that changes once something comes in from "
                f"outside the conversation — which is when they do"
            )

    # And the strictest rung's price says it out loud, because a confirmation
    # before reading a note is the interruption that reads as a bug.
    cost = (by_value["ask_every_time"]["cost"] or "").lower()
    assert "calendar" in cost or "note" in cost, (
        "the cost line warns about twenty files and says nothing about what "
        "happens to reads — whichever way the gate currently answers, the "
        "price of the strictest rung has to name them"
    )
    if not gates_private_reads:
        assert "outside" in cost, (
            "the cost line implies reading your calendar always asks; since "
            "`B19` it only asks once something has come in from outside"
        )


def test_the_allow_listed_price_says_a_saved_rule_stops_applying(ladder_sandbox):
    """`decision_for` ignores every saved rule once untrusted content has
    entered the run — which is what makes the intro's *"only ever make Pantheon
    ask more often"* true. It is also the moment someone who has approved a
    dozen things watches Pantheon ask about all of them again, so the price of
    the rung has to name it before they choose."""

    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)
    cost = next(
        row["cost"] for row in out["rows"] if row["value"] == "allow_listed"
    ).lower()

    assert "from outside the conversation" in cost
    assert "including the things you said yes to" in cost


# ── Job 1: the capability check ─────────────────────────────────────────────


def test_the_ladder_is_absent_when_the_server_does_not_carry_the_setting(ladder_sandbox):
    """`POST /api/auth/settings` iterates `DEFAULT_SETTINGS` and drops any key
    that is not in it, answering 200 either way. On a build without `trust_rung`
    three radio buttons would therefore save nothing and report success — the
    half-wiring `Law 13` names."""

    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify({
          ladder: readLadder(),
          hostText: host.readable,
          cardHidden: !!card.hidden,
          posts: posts.length,
        }));
    """ % (_NO_KEY, _IMPORT), ladder_sandbox)

    assert out["ladder"] is None
    assert out["hostText"] == ""
    assert out["cardHidden"] is True, (
        "an empty bordered card reads as a feature that failed to load"
    )
    assert out["posts"] == 0


def test_the_ladder_appears_and_unhides_its_card_when_the_setting_is_real(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify({ ladder: readLadder(), cardHidden: !!card.hidden }));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    assert out["ladder"] is not None
    assert out["cardHidden"] is False


def test_a_stored_rung_is_the_one_shown_as_chosen(ladder_sandbox):
    out = _ladder("""
        setSettings({ trust_rung: 'ask_every_time' });
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_IMPORT,), ladder_sandbox)

    chosen = [row["value"] for row in out["rows"] if row["checked"]]
    assert chosen == ["ask_every_time"]


def test_an_unreadable_stored_rung_falls_back_to_the_default_not_the_strictest(ladder_sandbox):
    """`coerce_trust_rung` fails safe, and the UI has to agree with it. Showing
    the strictest rung as chosen when the stored value is corrupt would tell a
    person their install confirms everything when it does not."""

    out = _ladder("""
        setSettings({ trust_rung: 'nonsense_value' });
        %s
        console.log(JSON.stringify(readLadder()));
    """ % (_IMPORT,), ladder_sandbox)

    chosen = [row["value"] for row in out["rows"] if row["checked"]]
    assert chosen == [DEFAULT_RUNG]


def test_choosing_a_rung_writes_only_that_key(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        replyWith({ ok: true, status: 200, body: { trust_rung: 'ask_every_time' } });
        pick('ask_every_time');
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({
          posts: posts.map((p) => ({ url: p.url, method: p.init.method, body: p.init.body })),
          status: readLadder().status,
        }));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    assert len(out["posts"]) == 1
    post = out["posts"][0]
    assert post["url"] == "/api/auth/settings"
    assert post["method"] == "POST"
    # Only the one key: the settings route merges a partial body into the saved
    # file, so sending the whole form back would let this control overwrite
    # every other setting with whatever the page happened to be holding.
    assert json.loads(post["body"]) == {"trust_rung": "ask_every_time"}
    assert "saved" in out["status"].lower()


def test_a_server_that_silently_drops_the_key_is_reported_as_not_saved(ladder_sandbox):
    """The exact failure this control exists not to have. A 200 whose body does
    not carry the value back means the key was discarded, and saying "Saved" to
    that is how a half-wired control passes for a working one."""

    out = _ladder("""
        %s
        %s
        replyWith({ ok: true, status: 200, body: { tts_enabled: true } });
        pick('ask_every_time');
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ status: readLadder().status }));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    status = out["status"].lower()
    assert "saved" not in status.replace("did not accept", "")
    assert "did not accept" in status or "nothing has changed" in status, status


def test_a_refused_write_puts_the_dot_back(ladder_sandbox):
    """Otherwise the ladder shows two answers at once — the option the person
    clicked, and a line beside it saying nothing changed — and the dot is the
    more visible of the two."""

    out = _ladder("""
        %s
        %s
        replyWith({ ok: false, status: 403, body: {} });
        pick('ask_every_time');
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        const after = readLadder();
        console.log(JSON.stringify({
          chosen: after.rows.filter((r) => r.checked).map((r) => r.value),
          status: after.status,
        }));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    assert out["chosen"] == [DEFAULT_RUNG], (
        "the refused rung is still showing as chosen"
    )
    assert "nothing was saved" in out["status"].lower()


def test_a_dropped_key_also_puts_the_dot_back(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        replyWith({ ok: true, status: 200, body: { tts_enabled: true } });
        pick('allow_listed');
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({
          chosen: readLadder().rows.filter((r) => r.checked).map((r) => r.value),
        }));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    assert out["chosen"] == [DEFAULT_RUNG]


def test_a_refused_write_says_who_can_change_it(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        replyWith({ ok: false, status: 403, body: {} });
        pick('allow_listed');
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ status: readLadder().status }));
    """ % (_HAS_KEY, _IMPORT), ladder_sandbox)

    status = out["status"].lower()
    assert "administrator" in status
    assert "nothing was saved" in status


# ── Job 2: "always allow this", on the approval card ────────────────────────
#
# `P7-04`'s store is real: `GET /api/tool-allow-rules` lists rules and returns
# the store's own `match_kinds`, `POST` creates one. The chooser is probed onto
# the card the way `probeSteerSupport()` probes the steer route, so every "no"
# below — no route, a caller the route refuses, the wrong rung — draws nothing
# and sends nothing.

_ALLOW_APPCONFIG = """
let _settings = {};
export function setSettings(next) { _settings = next; }
export function getSettings() { return Promise.resolve(_settings); }
export function invalidateSettings() {}
export function getTools() { return Promise.resolve({ tools: [] }); }
"""

# The card's `ui.js`, with the two report channels recorded. A rule that failed
# to save has to say so somewhere, and the card it was chosen on is gone by
# then.
_ALLOW_UI = """
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
export const toasts = [];
export const errors = [];
export default {
  esc,
  showToast: (m) => { toasts.push(String(m)); },
  showError: (m) => { errors.push(String(m)); },
  copyToClipboard: () => {}, el: (id) => document.getElementById(id),
  debounce: (f) => f, autoResize: () => {}, scrollHistory: () => {},
  formatBytes: (n) => String(n),
};
"""

_ALLOW_SHIM = _CARD_SHIM + r"""
import { toasts, errors } from './ui.js';
export { toasts, errors };

/** Every request the page makes, and the canned reply each one gets. */
export const requests = [];
let _probe = { ok: true, status: 200, body: { rules: [], match_kinds: ['any', 'exact', 'prefix'] } };
let _post = { ok: true, status: 200, body: { id: 'rule-1', match_kind: 'exact' } };
export function probeReplyWith(next) { _probe = next; }
export function postReplyWith(next) { _post = next; }
globalThis.fetch = async (url, init) => {
  const method = String(((init || {}).method) || 'GET').toUpperCase();
  const body = (init || {}).body || null;
  requests.push({ url: String(url), method, body });
  // The settings write echoes what it was sent, so moving the rung inside one
  // page session succeeds the way it does against the real route.
  if (String(url).indexOf('/api/auth/settings') >= 0) {
    let sent = {};
    try { sent = JSON.parse(body || '{}'); } catch (_) { sent = {}; }
    return { ok: true, status: 200, json: async () => sent };
  }
  const reply = method === 'POST' ? _post : _probe;
  return {
    ok: reply.ok !== false,
    status: reply.status || 200,
    json: async () => reply.body,
  };
};

/** A place to draw the ladder inside the card sandbox, so one case can move the
    rung the way Settings does and watch the card change under it. */
export function ladderHost() {
  return document.body.appendChild(new Node('div'));
}

export function pickRung(host, value) {
  const row = host.querySelector('.trust-rung[data-rung-value="' + value + '"]');
  const input = row.querySelector('.trust-rung-input');
  input.checked = true;
  input.dispatchEvent(new Event('change'));
  return input;
}

/** The standing-rule list drawn under a ladder inside the card sandbox. */
export function describeRuleList(host) {
  const box = host.querySelector('.allow-rule-list');
  if (!box) return null;
  return {
    hidden: !!box.hidden,
    rows: box.querySelectorAll('.allow-rule-row').map((row) => {
      const detail = row.querySelector('.allow-rule-row-detail');
      return {
        id: row.dataset.ruleId || null,
        match: row.dataset.ruleMatch || null,
        label: row.querySelector('.allow-rule-row-label').textContent,
        detail: detail ? detail.textContent : null,
      };
    }),
  };
}

/** What the scope chooser offers, as a person reads it off the card. */
export function describeAllowRule(card) {
  const box = card.querySelector('.allow-rule');
  if (!box) return null;
  const scopes = card.querySelectorAll('.allow-rule-scope');
  return {
    title: box.querySelector('.allow-rule-title').textContent,
    hint: box.querySelector('.allow-rule-hint').textContent,
    scopes: scopes.map((b) => ({
      match: b.dataset.scope,
      pressed: b.getAttribute('aria-pressed'),
      label: b.querySelector('.allow-rule-scope-label').textContent,
      detail: b.querySelector('.allow-rule-scope-detail').textContent,
      sentence: b.querySelector('.allow-rule-scope-sentence').textContent,
      sentenceHtml: b.querySelector('.allow-rule-scope-sentence')._html,
    })),
    // Any text entry at all would be pattern authoring wearing a scope's hat.
    inputs: card.querySelectorAll('input').length,
    textareas: card.querySelectorAll('textarea').length,
    read: box.read ? box.read() : null,
  };
}

export function press(card, match) {
  const button = card.querySelector('.allow-rule-scope[data-scope="' + match + '"]');
  button.dispatchEvent(new Event('click'));
  return button;
}

export function choose(card, value) {
  const options = card.querySelectorAll('.ask-user-option');
  const hit = options.find((o) => o.readable.toLowerCase().includes(value));
  hit.dispatchEvent(new Event('click'));
  return hit;
}

/** Two microtask turns, which is all `createAllowRule` needs to settle. */
export async function settle() {
  for (let i = 0; i < 6; i += 1) await new Promise((r) => setTimeout(r, 0));
}
"""


@pytest.fixture(scope="module")
def allow_sandbox(tmp_path_factory):
    stubs = dict(_CARD_STUBS)
    stubs["appConfig.js"] = _ALLOW_APPCONFIG
    stubs["ui.js"] = _ALLOW_UI
    # The stub `_CARD_STUBS` carries for this module is what a default install
    # renders; these cases want the real one.
    stubs.pop("trustLadder.js", None)
    directory = _make_sandbox(
        tmp_path_factory.mktemp("allowrule"), CHAT_RENDERER, _ALLOW_SHIM, stubs
    )
    shutil.copy(TRUST_LADDER, directory / TRUST_LADDER.name)
    return directory


_ALLOW_PREAMBLE = (
    "import { document, root, approvalPayload, describeAllowRule, press, choose,"
    " requests, probeReplyWith, postReplyWith, toasts, errors, settle,"
    " ladderHost, pickRung, describeRuleList } from './shim.js';\n"
    "import { setSettings } from './appConfig.js';\n"
)

_BASH_ACTION = (
    "{ tool: 'bash', content: 'git status --short', digest: 'abcd1234',"
    " effects: ['execute_code'] }"
)

_LOAD_CARD = (
    "const { renderAskUserCard } = await import('./chatRenderer.js');\n"
    "await (await import('./trustLadder.js')).trustSettingsReady();\n"
)
_ON_RUNG = "setSettings({ trust_rung: 'allow_listed' });"


def _allow(script: str, sandbox: Path) -> dict:
    return _run(sandbox, _ALLOW_PREAMBLE, script)


def test_the_chooser_is_absent_when_the_build_has_no_rule_route(allow_sandbox):
    """404/405/501 is how `chatStream.js` reads "this build has no such route",
    and it is how this reads it too. A build without `P7-04`'s store must not
    grow a control that posts into nothing."""

    for status in (404, 405, 501):
        out = _allow("""
            %s
            probeReplyWith({ ok: false, status: %d, body: {} });
            %s
            const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
            console.log(JSON.stringify({
              rule: describeAllowRule(card),
              posts: requests.filter((r) => r.method === 'POST').length,
              text: card.readable,
            }));
        """ % (_ON_RUNG, status, _LOAD_CARD, _BASH_ACTION), allow_sandbox)
        assert out["rule"] is None, status
        assert out["posts"] == 0, status
        assert "stop asking" not in out["text"].lower()


def test_the_chooser_is_absent_when_the_route_would_refuse_this_caller(allow_sandbox):
    """`_allow_rule_owner` 403s a bearer API token and 401s an unauthenticated
    caller. An affordance certain to be refused is not an affordance."""

    for status in (401, 403):
        out = _allow("""
            %s
            probeReplyWith({ ok: false, status: %d, body: {} });
            %s
            const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
            console.log(JSON.stringify({ rule: describeAllowRule(card) }));
        """ % (_ON_RUNG, status, _LOAD_CARD, _BASH_ACTION), allow_sandbox)
        assert out["rule"] is None, status


def test_the_chooser_is_absent_off_the_rung_that_reads_rules(allow_sandbox):
    """`ToolRunSecurityContext.decision_for` consults the store only at
    `ALLOW_LISTED`, and `_resolve_allow_rule_lookup` only builds a lookup there.
    A rule saved on any other rung is written, listed, and never read — a button
    wired to nothing wearing a receipt. The probe is not even sent."""

    for rung in ("gate_on_untrusted", "ask_every_time"):
        out = _allow("""
            setSettings({ trust_rung: '%s' });
            %s
            const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
            console.log(JSON.stringify({
              rule: describeAllowRule(card),
              requests: requests.map((r) => r.url),
            }));
        """ % (rung, _LOAD_CARD, _BASH_ACTION), allow_sandbox)
        assert out["rule"] is None, rung
        assert out["requests"] == [], rung


def test_moving_off_the_rung_takes_the_chooser_away_in_the_same_session(allow_sandbox):
    """The rung guard on its own, with the probe already answered.

    Reachable and not contrived: the probe runs once per page load, so a person
    who opens Pantheon on `allow_listed` and then moves the ladder to "Ask every
    time" leaves the store's kinds cached and the rung changed. Without the
    guard in `buildAllowRuleChooser` the next approval card still offers to save
    a rule that nothing on that rung will ever read — and every other assertion
    in this file passes while it does, because on a cold load the two conditions
    fail together.
    """

    out = _allow("""
        %s
        %s
        const { renderTrustLadder } = await import('./trustLadder.js');
        const before = describeAllowRule(
          renderAskUserCard(approvalPayload({ action: %s }), { root: root() }));

        const host = ladderHost();
        renderTrustLadder(host, 'allow_listed');
        pickRung(host, 'ask_every_time');
        await settle();

        const after = describeAllowRule(
          renderAskUserCard(approvalPayload({ action: %s }), { root: root() }));
        console.log(JSON.stringify({
          before: before ? before.scopes.map((s) => s.match) : null,
          after,
          probes: requests.filter((r) => r.url === '/api/tool-allow-rules').length,
        }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION, _BASH_ACTION), allow_sandbox)

    assert out["before"] == ["exact", "prefix", "any"]
    assert out["after"] is None, (
        "the rung moved and the chooser stayed; a rule saved from it would be "
        "written, listed, and never read"
    )
    # And the store was asked exactly once, on load — the second card did not
    # re-probe and get a fresh yes.
    assert out["probes"] == 1


def test_moving_onto_the_rung_brings_the_chooser_in_the_same_session(allow_sandbox):
    """The direction a first-time user actually takes, and the one that was
    broken.

    `_probeAllowRules()` used to run only from `_loadTrustState()`, which skips
    it unless the rung was already `allow_listed` when the page loaded.
    `_saveRung` set `_rung` and never probed, so someone who switched the ladder
    on and then approved something got no chooser at all — `_ruleKinds` was
    still empty and `buildAllowRuleChooser` returned `null` — until they
    reloaded. Refutation reproduced it against the real module and got
    `{"before": null, "after": null}` with the store never asked.

    The mirror of this case above was tested and its docstring called it
    "reachable and not contrived". This one is the more common of the two: you
    switch a setting on, and then you use it.
    """

    out = _allow("""
        setSettings({ trust_rung: 'gate_on_untrusted' });
        %s
        const { renderTrustLadder } = await import('./trustLadder.js');
        const before = describeAllowRule(
          renderAskUserCard(approvalPayload({ action: %s }), { root: root() }));

        const host = ladderHost();
        renderTrustLadder(host, 'gate_on_untrusted');
        pickRung(host, 'allow_listed');
        await settle();

        const after = describeAllowRule(
          renderAskUserCard(approvalPayload({ action: %s }), { root: root() }));
        console.log(JSON.stringify({
          before,
          after: after ? after.scopes.map((s) => s.match) : null,
          probes: requests.filter((r) => r.url === '/api/tool-allow-rules').length,
        }));
    """ % (_LOAD_CARD, _BASH_ACTION, _BASH_ACTION), allow_sandbox)

    # Nothing before: the rung was the default, and the store was never asked.
    assert out["before"] is None
    assert out["after"] == ["exact", "prefix", "any"], (
        "the ladder moved onto the rung that reads rules and the card still "
        "offers nothing; the store was never asked"
    )
    # Asked once, on the way onto the rung — not on load, and not again per card.
    assert out["probes"] == 1


def test_moving_onto_a_rung_that_reads_no_rules_asks_the_store_nothing(allow_sandbox):
    """The probe follows the rung, in both directions and on every move. The fix
    for the case above is one line, and the wrong version of it — probe after
    any successful save — would put a request and an unusable affordance on a
    rung whose runs never consult a rule."""

    out = _allow("""
        setSettings({ trust_rung: 'gate_on_untrusted' });
        %s
        const { renderTrustLadder } = await import('./trustLadder.js');
        const host = ladderHost();
        renderTrustLadder(host, 'gate_on_untrusted');
        pickRung(host, 'ask_every_time');
        await settle();
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        console.log(JSON.stringify({
          rule: describeAllowRule(card),
          probes: requests.filter((r) => r.url === '/api/tool-allow-rules').length,
        }));
    """ % (_LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["rule"] is None
    assert out["probes"] == 0


def test_a_rule_made_on_a_card_is_in_the_settings_list_without_a_reload(allow_sandbox):
    """Settings is a panel in the same page. A list loaded before the rule
    existed would be missing the one rule the person is most likely to come
    looking for — the one they just made and immediately regretted."""

    out = _allow("""
        %s
        postReplyWith({ ok: true, status: 200, body: {
          id: 'rule-new', tool_name: 'bash', match_kind: 'any', pattern: '' } });
        %s
        const { renderTrustLadder } = await import('./trustLadder.js');
        const card = renderAskUserCard(approvalPayload({ action: %s }),
          { root: root(), onSubmit: () => false });
        press(card, 'any');
        choose(card, 'allow for this task');
        await settle();

        const host = ladderHost();
        renderTrustLadder(host, 'allow_listed');
        console.log(JSON.stringify({ list: describeRuleList(host) }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["list"]["hidden"] is False
    assert out["list"]["rows"] == [
        {"id": "rule-new", "match": "any", "label": "Anything bash does", "detail": "bash"},
    ]


def test_an_unknown_rung_is_treated_as_not_offering_rules(allow_sandbox):
    """A server without `trust_rung`, or a settings read that failed, leaves the
    rung unknown. Unknown draws nothing — guessing `allow_listed` would put the
    affordance on a card whose run will never consult a rule."""

    out = _allow("""
        setSettings({ tts_enabled: true });
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        console.log(JSON.stringify({ rule: describeAllowRule(card), requests: requests.length }));
    """ % (_LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["rule"] is None
    assert out["requests"] == 0


def test_the_chooser_offers_only_the_three_match_kinds_and_no_text_entry(allow_sandbox):
    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        console.log(JSON.stringify(describeAllowRule(card)));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    # Narrowest first: the widest scope is the one granted by accident, so a
    # list read top to bottom widens as it goes.
    assert [s["match"] for s in out["scopes"]] == ["exact", "prefix", "any"]
    # No regex, no pattern authoring: a person picks a scope, and there is
    # nowhere on this card to type one.
    assert out["inputs"] == 0
    assert out["textareas"] == 0
    # Each scope shows the literal string the store would hold, so the rule is
    # read rather than imagined.
    detail = {s["match"]: s["detail"] for s in out["scopes"]}
    assert detail["exact"] == "git status --short"
    assert detail["prefix"] == "git"
    assert detail["any"] == "bash"
    for scope in out["scopes"]:
        assert scope["sentenceHtml"] == ""
        assert len(scope["sentence"]) >= 60
        assert "still stops and asks you" in scope["sentence"] or scope["match"] == "any"

    # The prefix rule is a literal `startswith` with no word boundary
    # (`rule_matches`, src/tool_allow_rules.py). The sentence has to describe
    # that rule and not a friendlier one it is not.
    prefix = next(s for s in out["scopes"] if s["match"] == "prefix")
    assert "exact letters" in prefix["sentence"]
    # And the widest one says it is the widest, in the sentence rather than only
    # in the geometry beside it.
    widest = next(s for s in out["scopes"] if s["match"] == "any")
    assert "widest" in widest["sentence"].lower()
    assert "have not seen" in widest["sentence"].lower()


def test_only_the_kinds_the_store_names_are_offered(allow_sandbox):
    """`routes/chat_routes.py` sends `match_kinds` so a chooser is built from the
    store's own vocabulary. A client copy would render a kind the store rejects,
    or hide one it gained."""

    out = _allow("""
        %s
        probeReplyWith({ ok: true, status: 200, body: { rules: [], match_kinds: ['any', 'exact'] } });
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        console.log(JSON.stringify(describeAllowRule(card)));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert [s["match"] for s in out["scopes"]] == ["exact", "any"]


def test_a_route_that_names_no_kinds_offers_nothing(allow_sandbox):
    out = _allow("""
        %s
        probeReplyWith({ ok: true, status: 200, body: { rules: [] } });
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        console.log(JSON.stringify({ rule: describeAllowRule(card) }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["rule"] is None


def test_prefix_is_not_offered_when_it_would_be_the_same_rule_as_exact(allow_sandbox):
    """A one-word command has no prefix to generalise to; offering both would
    make "only this exact command" look narrower than the identical rule beside
    it."""

    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({
          action: { tool: 'bash', content: 'ls', digest: 'd' },
        }), { root: root() });
        console.log(JSON.stringify(describeAllowRule(card)));
    """ % (_ON_RUNG, _LOAD_CARD), allow_sandbox)

    assert [s["match"] for s in out["scopes"]] == ["exact", "any"]


def test_no_rule_is_sent_until_a_scope_is_pressed(allow_sandbox):
    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }),
          { root: root(), onSubmit: () => false });
        const before = describeAllowRule(card);
        choose(card, 'allow for this task');
        await settle();
        console.log(JSON.stringify({
          before: before.read,
          pressed: before.scopes.map((s) => s.pressed),
          posts: requests.filter((r) => r.method === 'POST'),
        }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    # Nothing is chosen by default: a standing rule is never the default answer
    # to a question about whether to stop asking.
    assert out["before"] is None
    assert out["pressed"] == ["false", "false", "false"]
    assert out["posts"] == []


def test_allowing_with_a_scope_chosen_writes_the_rule_in_the_stores_own_fields(allow_sandbox):
    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }),
          { root: root(), onSubmit: () => false });
        press(card, 'prefix');
        choose(card, 'allow for this task');
        await settle();
        console.log(JSON.stringify({
          posts: requests.filter((r) => r.method === 'POST'),
          toasts, errors,
        }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert len(out["posts"]) == 1
    post = out["posts"][0]
    assert post["url"] == "/api/tool-allow-rules"
    # `ToolAllowRuleCreate` in routes/chat_routes.py. `owner` is deliberately
    # not sent: the route refuses a body that names one.
    assert json.loads(post["body"]) == {
        "tool_name": "bash",
        "match_kind": "prefix",
        "pattern": "git",
    }
    assert out["errors"] == []
    assert out["toasts"] and "saved" in out["toasts"][0].lower()
    assert "stop asking" in out["toasts"][0].lower()
    # CORRECTED 2026-08-29. This asserted `"settings" not in` the toast, under a
    # comment reading: *"`GET`/`DELETE /api/tool-allow-rules` both exist and no
    # screen in the product draws them, so a toast pointing at a place to revoke
    # would be pointing at nowhere."* Both halves were true and together they
    # were the defect — refutation's *"the worst thing in the change"*: the
    # widest grant in the product was one click away and could then be neither
    # seen nor taken back. A screen draws them now, so the toast has somewhere
    # to point and must point there. The person who has just been surprised by
    # their own click is exactly the person who needs the way back, and they
    # need it in the same breath rather than after a hunt through Settings.
    toast = out["toasts"][0].lower()
    assert "settings" in toast, "the toast no longer says where to take it back"
    assert "how often pantheon checks with you" in toast, (
        "and it has to name the card, not just the panel"
    )


def test_the_widest_scope_sends_no_pattern(allow_sandbox):
    """`create_rule` stores '' for `any` — a string beside it would read like a
    condition and not be one."""

    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }),
          { root: root(), onSubmit: () => false });
        press(card, 'any');
        choose(card, 'allow for this task');
        await settle();
        console.log(JSON.stringify({ posts: requests.filter((r) => r.method === 'POST') }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert json.loads(out["posts"][0]["body"]) == {
        "tool_name": "bash", "match_kind": "any", "pattern": "",
    }


def test_pressing_a_second_scope_replaces_the_first_and_pressing_again_clears_it(allow_sandbox):
    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        press(card, 'exact');
        const first = describeAllowRule(card);
        press(card, 'any');
        const second = describeAllowRule(card);
        press(card, 'any');
        const cleared = describeAllowRule(card);
        console.log(JSON.stringify({
          first: first.read, firstPressed: first.scopes.map((s) => s.pressed),
          second: second.read, secondPressed: second.scopes.map((s) => s.pressed),
          cleared: cleared.read, clearedPressed: cleared.scopes.map((s) => s.pressed),
        }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["first"]["match"] == "exact"
    assert out["first"]["pattern"] == "git status --short"
    assert out["firstPressed"] == ["true", "false", "false"]
    assert out["second"]["match"] == "any"
    assert out["secondPressed"] == ["false", "false", "true"]
    assert out["cleared"] is None
    assert out["clearedPressed"] == ["false", "false", "false"]


def test_denying_never_creates_a_rule(allow_sandbox):
    """Refusing an action must not be a way to create permission for it. The
    chooser sits above all three buttons, so this is a guard and not tidiness."""

    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({
          action: %s,
          options: [
            { label: 'Allow for this task', value: 'approve_task' },
            { label: 'Deny', value: 'deny' },
          ],
        }), { root: root(), onSubmit: () => false });
        press(card, 'any');
        choose(card, 'deny');
        await settle();
        console.log(JSON.stringify({ posts: requests.filter((r) => r.method === 'POST') }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["posts"] == []


# Denials that are not the literal string `deny`. The guard used to be
# `detail.decision !== 'deny'` — a blacklist of one string under a comment
# claiming the opposite — so every one of these created the standing rule.
# `public_payload` (src/tool_approvals.py) only ever sends
# `DENY_APPROVAL_DECISION` today, so none of them ships; each is one server-side
# copy change away, and the failure mode is silent and grants permission.
_NOT_QUITE_DENY = (
    ("a second refusal", "{ label: 'Deny and stop', value: 'deny_all' }", "deny and stop"),
    ("a button with no value", "{ label: 'Deny' }", "deny"),
    ("a renamed refusal", "{ label: 'Refuse', value: 'refuse' }", "refuse"),
    ("an empty value", "{ label: 'Deny', value: '' }", "deny"),
)


@pytest.mark.parametrize("why,option,click", _NOT_QUITE_DENY)
def test_no_refusal_creates_a_rule_whatever_the_button_is_called(
    allow_sandbox, why, option, click,
):
    """Refusing an action must not be a way to create permission for it — and
    that has to hold for every refusal, not for the one spelling the server
    happens to send today."""

    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({
          action: %s,
          options: [
            { label: 'Allow for this task', value: 'approve_task' },
            %s,
          ],
        }), { root: root(), onSubmit: () => false });
        press(card, 'any');
        choose(card, '%s');
        await settle();
        console.log(JSON.stringify({ posts: requests.filter((r) => r.method === 'POST') }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION, option, click), allow_sandbox)

    assert out["posts"] == [], why


@pytest.mark.parametrize("decision,label", [
    ("approve_task", "allow for this task"),
    ("approve", "allow for this chat session"),
])
def test_both_of_the_servers_affirmative_decisions_create_the_rule(
    allow_sandbox, decision, label,
):
    """The other half of the whitelist. `scope_for_decision`
    (src/tool_approval_scopes.py) returns a scope for exactly two values —
    `approve_task` and `approve` — and both are a yes to the action the rule
    would go on covering. A whitelist that admitted only one of them would make
    "stop asking" quietly conditional on which allow button you happened to
    press, which is worse than not offering it."""

    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({
          action: %s,
          options: [
            { label: 'Allow for this task', value: 'approve_task' },
            { label: 'Allow for this chat session', value: 'approve' },
            { label: 'Deny', value: 'deny' },
          ],
        }), { root: root(), onSubmit: () => false });
        press(card, 'any');
        choose(card, '%s');
        await settle();
        console.log(JSON.stringify({ posts: requests.filter((r) => r.method === 'POST') }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION, label), allow_sandbox)

    assert len(out["posts"]) == 1, decision
    assert json.loads(out["posts"][0]["body"])["match_kind"] == "any"


def test_a_refused_rule_is_reported_in_the_servers_own_words(allow_sandbox):
    """The store's refusals are already plain sentences. Replacing one with a
    generic failure would take away the only thing that tells a person what to
    do next."""

    out = _allow("""
        %s
        postReplyWith({ ok: false, status: 400, body: {
          detail: 'You already have 200 allow rules. Revoke one before adding another.' } });
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }),
          { root: root(), onSubmit: () => false });
        press(card, 'exact');
        choose(card, 'allow for this task');
        await settle();
        console.log(JSON.stringify({ toasts, errors }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["toasts"] == []
    assert out["errors"] == [
        "You already have 200 allow rules. Revoke one before adding another."
    ]


def test_a_reply_with_no_rule_in_it_is_not_reported_as_saved(allow_sandbox):
    """The same shape of check the ladder makes on its own save: a 200 is not a
    receipt. Without a stored rule in the body, nothing was created."""

    out = _allow("""
        %s
        postReplyWith({ ok: true, status: 200, body: {} });
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }),
          { root: root(), onSubmit: () => false });
        press(card, 'exact');
        choose(card, 'allow for this task');
        await settle();
        console.log(JSON.stringify({ toasts, errors }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["toasts"] == []
    assert out["errors"] and "keep asking" in out["errors"][0].lower()


def test_a_plain_question_card_never_grows_a_rule_chooser(allow_sandbox):
    out = _allow("""
        %s
        %s
        const card = renderAskUserCard({
          question: 'Which one?',
          options: [{ label: 'A' }, { label: 'B' }],
        }, { root: root() });
        console.log(JSON.stringify({ rule: describeAllowRule(card) }));
    """ % (_ON_RUNG, _LOAD_CARD), allow_sandbox)

    assert out["rule"] is None


def test_the_effect_box_still_leads_the_card(allow_sandbox):
    """`P7-06`'s consequence box decides the answer; the rule chooser changes
    what the answer will mean, and the buttons come last. A regression in that
    order is silent."""

    out = _allow("""
        %s
        %s
        const card = renderAskUserCard(approvalPayload({
          action: %s,
          effect_label: 'Can run code on this machine',
          effect_band: 'serious',
        }), { root: root() });
        console.log(JSON.stringify({ order: card.children.map((c) => c.className) }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    order = out["order"]
    assert order.index("approval-effects") < order.index("allow-rule")
    assert order.index("allow-rule") < order.index("ask-user-options")


# ── Job 3: seeing what you granted, and taking it back ──────────────────────
#
# Refutation called the absence of this *"the worst thing in the change"*, and
# the reproduction was one sentence long: the widest grant on offer — "anything
# bash does" — is one click on an approval card, after which no screen shows the
# rule exists and none revokes it. Recovering meant knowing
# `DELETE /api/tool-allow-rules/{id}` was there and issuing HTTP by hand against
# your own install.
#
# It also hollowed out three claims the code makes for itself: `core/database.py`
# (*"Revocation is a DELETE… this is the table where that omission is
# expensive"*), `list_tool_allow_rules` (*"Listable is half of revocable: a grant
# nobody can see is one nobody thinks to take back"*), and the store's 5-second
# snapshot TTL, defended on the grounds that *"revoke means revoked before the
# user has finished reading the confirmation"* — with no revoke to be prompt
# about.
#
# The cases below drive the real module against the real response shape:
# `{ rules: [{id, owner, tool_name, match_kind, pattern, last_used_at,
# created_at}], match_kinds: [...] }`, newest first.

_ON_RUNG_LADDER = "setSettings({ trust_rung: 'allow_listed', tts_enabled: true });"

_TWO_RULES = """
rulesReplyWith({ ok: true, status: 200, body: {
  match_kinds: ['any', 'exact', 'prefix'],
  rules: [
    { id: 'r-any', owner: 'ana', tool_name: 'bash', match_kind: 'any',
      pattern: '', last_used_at: null, created_at: '2026-08-28T09:00:00' },
    { id: 'r-pre', owner: 'ana', tool_name: 'bash', match_kind: 'prefix',
      pattern: 'git', last_used_at: '2026-08-29T08:30:00',
      created_at: '2026-08-27T09:00:00' },
  ] } });
"""


def test_the_ladder_lists_every_standing_rule_and_offers_to_revoke_each_one(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        %s
        console.log(JSON.stringify(readRules()));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["hidden"] is False
    assert [row["id"] for row in out["rows"]] == ["r-any", "r-pre"], (
        "a grant that is not on this screen is one nobody thinks to take back"
    )
    # The same words the approval card offered when the grant was made. A person
    # who read "Anything bash does" as they granted it has to meet those four
    # words again, or they cannot be sure it is the same thing they are undoing.
    assert out["rows"][0]["label"] == "Anything bash does"
    assert out["rows"][0]["detail"] == "bash"
    assert out["rows"][1]["label"] == "Anything beginning with “git”"
    assert out["rows"][1]["detail"] == "git"
    for row in out["rows"]:
        assert row["revoke"] == "Revoke"
        assert row["disabled"] is False
        assert len(row["sentence"]) >= 60
        # Prose reaches the DOM as text, never as markup.
        assert row["sentenceHtml"] == ""

    # Whether it has ever been used: the one fact that separates "I need this"
    # from "I clicked that once by accident", which is the whole question.
    assert "not used" in out["rows"][0]["when"].lower()
    assert "last used" in out["rows"][1]["when"].lower()

    # Twenty buttons all reading "Revoke" name nothing to a screen reader.
    assert out["rows"][0]["revokeLabel"] == "Revoke: Anything bash does"


def test_the_list_says_the_rules_stop_applying_once_something_came_in(ladder_sandbox):
    """`decision_for` ignores every saved rule once untrusted content has entered
    the run. Someone who granted "anything bash does" and then watches Pantheon
    ask anyway will think the button did nothing, so the list says it first."""

    out = _ladder("""
        %s
        %s
        %s
        console.log(JSON.stringify(readRules()));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    hint = out["hint"].lower()
    assert "from outside the conversation" in hint
    assert "asks about everything again" in hint
    # And when a revoke bites. `SNAPSHOT_TTL_SECONDS` is five seconds precisely
    # so this sentence can be true — *"revoke means revoked before the user has
    # finished reading the confirmation"* — and someone revoking in a hurry
    # needs to know the run in front of them is already covered.
    assert "within a few seconds" in hint
    assert "already running" in hint


def test_an_empty_store_says_so_instead_of_showing_a_blank_box(ladder_sandbox):
    """A person who has just revoked their last rule and a person who has never
    made one are looking at the same empty space and need to be told which."""

    out = _ladder("""
        %s
        %s
        console.log(JSON.stringify(readRules()));
    """ % (_ON_RUNG_LADDER, _IMPORT), ladder_sandbox)

    assert out["rows"] == []
    assert out["empty"] and len(out["empty"]) >= 60
    assert "nothing yet" in out["empty"].lower()


def test_the_list_costs_no_request_of_its_own(ladder_sandbox):
    """`GET /api/tool-allow-rules` answers both questions this module asks — what
    kinds may be offered, and what already exists — so the list is drawn from the
    probe that was happening anyway."""

    out = _ladder("""
        %s
        %s
        %s
        console.log(JSON.stringify({
          rows: readRules().rows.length,
          gets: posts.filter((p) => p.url === '/api/tool-allow-rules').length,
        }));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["rows"] == 2
    assert out["gets"] == 1


def test_revoking_calls_the_delete_that_already_exists_and_takes_the_row_away(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        %s
        revoke('r-pre');
        await settle();
        const after = readRules();
        console.log(JSON.stringify({
          deletes: posts.filter((p) => p.method === 'DELETE').map((p) => p.url),
          rows: after.rows.map((r) => r.id),
          status: after.status,
        }));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    # The route that was already owner-scoped and already tested. No new
    # endpoint, and the id goes in the path exactly as the route declares it.
    assert out["deletes"] == ["/api/tool-allow-rules/r-pre"]
    assert out["rows"] == ["r-any"]
    status = out["status"].lower()
    assert "taken back" in status
    assert "will ask before" in status


def test_revoking_the_last_rule_leaves_the_sentence_and_not_a_blank(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        %s
        revoke('r-any');
        await settle();
        revoke('r-pre');
        await settle();
        console.log(JSON.stringify(readRules()));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["rows"] == []
    assert "nothing yet" in (out["empty"] or "").lower()


def test_a_revoke_the_server_refuses_keeps_the_row_and_says_the_grant_stands(ladder_sandbox):
    """`Law 13`. The failure path is the whole point of a revoke button: a
    silent one leaves someone believing they took a permission back when they
    did not, and the permission is the widest thing the product hands out."""

    out = _ladder("""
        %s
        %s
        revokeReplyWith({ ok: false, status: 500, body: {} });
        %s
        revoke('r-any');
        await settle();
        const after = readRules();
        console.log(JSON.stringify({
          rows: after.rows.map((r) => ({ id: r.id, disabled: r.disabled })),
          status: after.status,
        }));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert [row["id"] for row in out["rows"]] == ["r-any", "r-pre"], (
        "the row went away and the grant did not"
    )
    # And the button comes back, so the person can try again.
    assert out["rows"][0]["disabled"] is False
    status = out["status"].lower()
    assert "could not" in status
    assert "still do it without asking" in status, (
        "the failure line has to say the unwelcome thing, not just that "
        "something went wrong"
    )


def test_a_revoke_the_network_drops_is_reported_the_same_way(ladder_sandbox):
    out = _ladder("""
        %s
        %s
        %s
        globalThis.fetch = async () => { throw new Error('offline'); };
        revoke('r-any');
        await settle();
        const after = readRules();
        console.log(JSON.stringify({
          rows: after.rows.map((r) => r.id), status: after.status,
        }));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["rows"] == ["r-any", "r-pre"]
    assert "still do it without asking" in out["status"].lower()


def test_a_rule_the_server_says_has_already_gone_leaves_the_list_honest(ladder_sandbox):
    """404 is what this route answers for a rule that is not there — revoked in
    another tab, or a click that landed twice. The person's intent has been
    served, so the row goes; leaving it would be this screen telling the exact
    lie it was built to stop telling."""

    out = _ladder("""
        %s
        %s
        revokeReplyWith({ ok: false, status: 404, body: { detail: 'Allow rule not found' } });
        %s
        revoke('r-any');
        await settle();
        const after = readRules();
        console.log(JSON.stringify({ rows: after.rows.map((r) => r.id), status: after.status }));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["rows"] == ["r-pre"]
    status = out["status"].lower()
    assert "already gone" in status
    assert "will ask before" in status


def test_a_rule_this_build_cannot_phrase_is_still_listed_and_still_revocable(ladder_sandbox):
    """The store is authoritative for which kinds exist; this file is only
    authoritative for which it can describe. A grant it has no sentence for is
    still a grant, and dropping it from the list would be the defect this list
    exists to fix, arriving through the back door."""

    out = _ladder("""
        %s
        rulesReplyWith({ ok: true, status: 200, body: {
          match_kinds: ['any', 'exact', 'prefix'],
          rules: [{ id: 'r-new', tool_name: 'bash', match_kind: 'sorcery',
                    pattern: 'abra', last_used_at: null }] } });
        %s
        const before = readRules();
        revoke('r-new');
        await settle();
        console.log(JSON.stringify({
          rows: before.rows.map((r) => ({ id: r.id, label: r.label, sentence: r.sentence })),
          deletes: posts.filter((p) => p.method === 'DELETE').map((p) => p.url),
          after: readRules().rows.map((r) => r.id),
        }));
    """ % (_ON_RUNG_LADDER, _IMPORT), ladder_sandbox)

    assert [row["id"] for row in out["rows"]] == ["r-new"]
    # Said to be unreadable rather than dressed up as one of the three kinds.
    assert "cannot put this one into words" in out["rows"][0]["sentence"]
    assert out["deletes"] == ["/api/tool-allow-rules/r-new"]
    assert out["after"] == []


def test_a_kind_the_store_names_and_this_build_cannot_phrase_is_never_offered(allow_sandbox):
    """The other side of the same coin.

    `routes/chat_routes.py` sends `match_kinds` so the chooser is built from the
    store's vocabulary rather than a client copy, and warns that a kind in one
    and not the other "renders as a blank option or an unsubmittable form".
    Building it straight off the wire is what would produce that blank option,
    so the chooser offers a kind only when `allowRuleWording` has a sentence for
    it. Narrowing what the store named is safe *because* it can only ever hide a
    choice, never widen a grant; the same rule pointed the other way would let
    the store's list mint buttons this build cannot label.
    """

    out = _allow("""
        %s
        probeReplyWith({ ok: true, status: 200, body: { rules: [],
          match_kinds: ['any', 'exact', 'prefix', 'sorcery'] } });
        %s
        const card = renderAskUserCard(approvalPayload({ action: %s }), { root: root() });
        const rule = describeAllowRule(card);
        console.log(JSON.stringify({
          matches: rule.scopes.map((s) => s.match),
          labels: rule.scopes.map((s) => s.label),
        }));
    """ % (_ON_RUNG, _LOAD_CARD, _BASH_ACTION), allow_sandbox)

    assert out["matches"] == ["exact", "prefix", "any"]
    assert all(label.strip() for label in out["labels"])


def test_the_list_is_away_on_the_rungs_that_never_read_a_rule(ladder_sandbox):
    """A saved rule still exists on the other rungs and is simply not consulted.
    Listing grants beside a setting that ignores them would read as a promise the
    run will not keep."""

    out = _ladder("""
        %s
        %s
        %s
        const before = readRules();
        replyWith({ ok: true, status: 200, body: { trust_rung: 'ask_every_time' } });
        pick('ask_every_time');
        await settle();
        const off = readRules();
        replyWith({ ok: true, status: 200, body: { trust_rung: 'allow_listed' } });
        pick('allow_listed');
        await settle();
        const back = readRules();
        console.log(JSON.stringify({
          before: { hidden: before.hidden, rows: before.rows.length },
          off: { hidden: off.hidden, rows: off.rows.length },
          back: { hidden: back.hidden, rows: back.rows.map((r) => r.id) },
          gets: posts.filter((p) => p.url === '/api/tool-allow-rules').length,
        }));
    """ % (_ON_RUNG_LADDER, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["before"] == {"hidden": False, "rows": 2}
    assert out["off"] == {"hidden": True, "rows": 0}
    # And back again without a second trip to the store.
    assert out["back"] == {"hidden": False, "rows": ["r-any", "r-pre"]}
    assert out["gets"] == 1


def test_switching_onto_the_rung_from_cold_fetches_the_list_it_never_asked_for(ladder_sandbox):
    """The list half of the same defect the chooser had. A page that loaded on
    the default rung has never asked the store, so moving onto the rung has to
    ask — otherwise the screen that exists to show every grant opens on "nothing
    yet" for an install that has grants."""

    out = _ladder("""
        %s
        %s
        %s
        const cold = readRules();
        replyWith({ ok: true, status: 200, body: { trust_rung: 'allow_listed' } });
        pick('allow_listed');
        await settle();
        const warm = readRules();
        console.log(JSON.stringify({
          cold: { hidden: cold.hidden, rows: cold.rows.length },
          warm: { hidden: warm.hidden, rows: warm.rows.map((r) => r.id) },
          gets: posts.filter((p) => p.url === '/api/tool-allow-rules').length,
        }));
    """ % (_HAS_KEY, _TWO_RULES, _IMPORT), ladder_sandbox)

    assert out["cold"] == {"hidden": True, "rows": 0}
    assert out["warm"] == {"hidden": False, "rows": ["r-any", "r-pre"]}
    assert out["gets"] == 1


def test_a_store_that_cannot_be_asked_draws_no_list_rather_than_an_empty_one(ladder_sandbox):
    """A build with no such route, a caller the route refuses, a store that
    cannot answer — none of them may be drawn as "Nothing yet". That is a claim
    about the store, and nobody managed to ask it. The chooser on the approval
    card treats all three the same way and so does this."""

    for status in (404, 403, 500):
        out = _ladder("""
            %s
            rulesReplyWith({ ok: false, status: %d, body: {} });
            %s
            console.log(JSON.stringify(readRules()));
        """ % (_ON_RUNG_LADDER, status, _IMPORT), ladder_sandbox)

        assert out["hidden"] is True, status
        assert out["rows"] == [], status
        assert out["empty"] is None, (
            f"{status}: the store was never able to answer, so the screen must "
            f"not claim it is empty"
        )


# ── Job 4: the stylesheet, read as values ───────────────────────────────────
#
# Scoped to this block rather than reusing the readers in
# `test_tool_effect_surfaces_js.py`: those split the sheet into "desktop" and
# the two media spans that file names, and would report this block's phone rules
# as desktop ones — which is exactly how a desktop-only distinction hides.

_BLOCK_START = ".trust-ladder {"
_BLOCK_END = "/* ── Workspace picker"
_M768 = "@media (max-width: 768px) {\n  .trust-ladder-intro"
_M640 = "@media (max-width: 640px) {\n  .trust-ladder-title"


def _block() -> str:
    css = STYLE.read_text(encoding="utf-8")
    start = css.index(_BLOCK_START)
    return css[start:css.index(_BLOCK_END, start)]


def _regions() -> dict:
    block = _block()
    m768 = block.index(_M768)
    m640 = block.index(_M640)
    end640 = block.index("\n}\n", m640) + 3
    return {
        "desktop": block[:m768],
        "m768": block[m768:m640],
        "m640": block[m640:end640],
    }


def _decls(selector: str, where: str = "desktop") -> dict:
    """Every declaration this exact selector makes in one region, in cascade
    order. Split on `;` rather than per line, so a one-line override at a
    breakpoint reports all of its declarations and not only the first."""
    out = {}
    for match in re.finditer(
        r"(?:^|[},/])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}",
        _regions()[where],
        re.M,
    ):
        body = blank_text(match.group(1), "css")
        for chunk in body.split(";"):
            declaration = re.match(r"\s*([a-z-]+)\s*:\s*(\S.*?)\s*$", chunk, re.S)
            if not declaration:
                continue
            out.pop(declaration.group(1), None)
            out[declaration.group(1)] = re.sub(r"\s+", " ", declaration.group(2))
    return out


def _cascade(where: str, *selectors: str) -> dict:
    """Only what `where` itself declares. Every selector must exist somewhere in
    the block — a typo or a deleted rule still fails — but a region is allowed to
    say nothing about one, which is the normal case at a breakpoint."""
    resolved = {}
    for selector in selectors:
        found = any(_decls(selector, region) for region in ("desktop", "m768", "m640"))
        assert found, f"no rule anywhere for {selector!r}"
        resolved.update(_decls(selector, where))
    return resolved


def _effective(where: str, *selectors: str) -> dict:
    """What actually resolves at `where`: the desktop rules, then whatever the
    breakpoint overrides. Reading a breakpoint alone reports "no left rule" for
    a ladder that reaches it perfectly intact, which is the opposite of the
    answer the test wants."""
    resolved = _cascade("desktop", *selectors)
    if where != "desktop":
        resolved.update(_cascade(where, *selectors))
    return resolved


_ROW = {
    "none": '.trust-rung[data-rung-cost="none"]',
    "some": '.trust-rung[data-rung-cost="some"]',
    "high": '.trust-rung[data-rung-cost="high"]',
}


def _row(band: str, where: str = "desktop") -> dict:
    chain = [".trust-rung"]
    if band != "none":
        chain.append(_ROW[band])
    return _effective(where, *chain)


def _mark(band: str) -> dict:
    chain = [".trust-rung-mark"]
    if band != "none":
        chain.append(f"{_ROW[band]} .trust-rung-mark")
    resolved = _effective("desktop", *chain)
    return {
        "size": (resolved.get("width"), resolved.get("height")),
        "radius": resolved.get("border-radius"),
        "transform": resolved.get("transform"),
        "fill": resolved.get("background"),
        # Both spellings, read separately: the triangle sets `border: none`
        # and then `border-bottom`, so a reader that falls back from one to the
        # other stops at 'none' and never sees the 11px that makes the shape.
        "border": resolved.get("border"),
        "edge": resolved.get("border-bottom"),
    }


def _cost(band: str, where: str = "desktop") -> dict:
    chain = [".trust-rung-cost"]
    if band == "high":
        chain.append('.trust-rung[data-rung-cost="high"] .trust-rung-cost')
    return _effective(where, *chain)


_RULE_PROPS = ("border-left", "border-left-width")


def _rule_px(band: str, where: str = "desktop") -> float:
    resolved = _row(band, where)
    spelled = [prop for prop in resolved if prop in _RULE_PROPS]
    assert spelled, f"the {band} rung declares no left rule"
    return _px(resolved[spelled[-1]].split()[0])


def test_the_rung_ladder_differs_in_values_a_reader_can_see():
    widths = {band: _rule_px(band) for band in ("none", "some", "high")}
    assert widths["none"] < widths["some"] < widths["high"], widths
    assert widths == {"none": 2.0, "some": 4.0, "high": 6.0}

    marks = {band: _mark(band) for band in ("none", "some", "high")}
    # Every adjacent pair differs on at least two channels, and no channel here
    # is a hue: size, corner, rotation and fill all survive greyscale.
    for a, b in (("none", "some"), ("some", "high"), ("none", "high")):
        differing = [k for k in marks[a] if marks[a][k] != marks[b][k]]
        assert len(differing) >= 2, f"{a} and {b} share their mark: {marks[a]} {marks[b]}"

    assert marks["none"]["radius"] == "50%" and marks["none"]["fill"] == "none"
    assert marks["some"]["radius"] == "0" and marks["some"]["transform"] == "rotate(45deg)"
    assert marks["some"]["fill"] == "currentColor"
    assert marks["high"]["size"] == ("0", "0")
    assert "11px" in (marks["high"]["edge"] or "")


def test_the_cost_line_is_never_quieter_than_the_sentence_above_it():
    sentence = _cascade("desktop", ".trust-rung-sentence")
    for band in ("some", "high"):
        cost = _cost(band)
        assert _px(cost["font-size"]) >= _px(sentence["font-size"]), band
        assert int(cost["font-weight"]) > int(sentence["font-weight"]), band
        assert float(cost["opacity"]) >= float(sentence["opacity"]), band
    # And the strictest rung's price is louder than the milder one's.
    assert _px(_cost("high")["font-size"]) > _px(_cost("some")["font-size"])
    assert int(_cost("high")["font-weight"]) > int(_cost("some")["font-weight"])


def test_the_widest_allow_scope_is_marked_without_relying_on_colour():
    base = _cascade("desktop", ".allow-rule-scope-mark")
    prefix = _cascade("desktop", '.allow-rule-scope[data-scope="prefix"] .allow-rule-scope-mark')
    widest = _cascade("desktop", '.allow-rule-scope[data-scope="any"] .allow-rule-scope-mark')
    # The scopes nest — exact inside prefix inside any — so the mark grows with
    # what the rule would cover.
    assert _px(base["width"]) < _px(prefix["width"]) < _px(widest["width"])
    assert base["background"] == "none" and widest["background"] == "currentColor"

    sentence = _cascade("desktop", ".allow-rule-scope-sentence")
    loud = _cascade("desktop", '.allow-rule-scope[data-scope="any"] .allow-rule-scope-sentence')
    assert int(loud["font-weight"]) > int(sentence["font-weight"])
    assert float(loud["opacity"]) > float(sentence["opacity"])


def test_the_chosen_scope_is_not_carried_by_colour_alone():
    chosen = _cascade("desktop", '.allow-rule-scope[aria-pressed="true"]')
    base = _cascade("desktop", ".allow-rule-scope")
    assert _px(chosen["border-left-width"]) > _px(base["border-left"].split()[0])
    label = _cascade("desktop", '.allow-rule-scope[aria-pressed="true"] .allow-rule-scope-label')
    assert int(label["font-weight"]) > int(_cascade("desktop", ".allow-rule-scope-label")["font-weight"])


def test_both_narrow_breakpoints_keep_the_whole_ladder():
    regions = _regions()
    assert regions["m768"].strip() and regions["m640"].strip()

    # Nothing is hidden. `P6-04` deleted the queue panel's state line under
    # 768px and removed the sentence that said the queue was paused from the
    # form factor with the least room to guess; the cost line is the same kind
    # of sentence.
    for where in ("m768", "m640"):
        assert "display: none" not in regions[where], where
        assert "display:none" not in regions[where], where

    # 768 restates no meaning-bearing value, so the desktop ladder reaches it
    # untouched. Asserting the absence is the point: a future edit that resizes
    # the cost line here without resizing the sentence has to say so.
    for selector in (".trust-rung-cost", ".trust-rung-sentence", ".trust-rung-mark"):
        assert not _decls(selector, "m768"), f"{selector} is restated at 768px"
    for band in ("none", "some", "high"):
        assert not _decls(_ROW[band], "m768"), f"the {band} rule width is restated at 768px"
        assert _rule_px(band, "m768") == _rule_px(band), band

    # 640 shrinks the type. The relationship — cost never smaller than the
    # sentence, strictest cost a step above the milder one — has to survive it.
    sentence = _effective("m640", ".trust-rung-sentence")
    for band in ("some", "high"):
        cost = _cost(band, "m640")
        assert _px(cost["font-size"]) >= _px(sentence["font-size"]), band
    assert _px(_cost("high", "m640")["font-size"]) > _px(_cost("some", "m640")["font-size"])
    # And the rule ladder is never restated there either.
    for band in ("none", "some", "high"):
        assert _rule_px(band, "m640") == _rule_px(band), band


# ── The measurement, across the sixteen shipped palettes ────────────────────


def _ratio(colour: str, background: str, theme: dict) -> float:
    return _contrast(_resolve(colour, theme), _resolve(background, theme))


def test_no_string_in_either_control_is_less_legible_than_the_prose_beside_it():
    """`P7-06`'s defect, transplanted. The previous attempt at an approval card
    recoloured the one line that mattered most and put it at 2.11:1 on `paper`
    while the harmless line beside it sat at 11.05:1. Colour is not allowed to
    carry either of these controls, and the way that is enforced is that every
    string resolves to the same token on the same ground in every band — so the
    numbers below are equal by construction, and any recolour breaks them."""

    themes = _themes()
    assert len(themes) >= 16, sorted(themes)

    row_bg = _cascade("desktop", ".trust-rung")["background"]
    sentence_colour = _cascade("desktop", ".trust-rung-sentence")["color"]
    measured = {}
    for name, theme in themes.items():
        base = _ratio(sentence_colour, row_bg, theme)
        worst = base
        for band in ("some", "high"):
            assert "background" not in _decls(_ROW[band]), (
                f"the {band} rung tints its own ground; measured across the "
                f"sixteen palettes a 7% --fg tint cost the strict row up to 19% "
                f"of its contrast (claude, 12.02 -> 9.78)"
            )
            worst = min(worst, _ratio(_cost(band)["color"], row_bg, theme))
        measured[name] = (base, worst)

    dimmer = {n: v for n, v in measured.items() if v[1] < v[0] * 0.999}
    assert not dimmer, (
        "the price of a strict rung is harder to read than the harmless prose "
        "beside it on " + ", ".join(f"{n} ({v[1]:.2f} vs {v[0]:.2f})"
                                    for n, v in sorted(dimmer.items()))
    )

    # The allow-rule box sits on the same 3% tint `.approval-effects` already
    # ships. Its consequence sentences must not lose to its own hint text.
    box_bg = _cascade("desktop", ".allow-rule")["background"]
    scope_bg = _cascade("desktop", ".allow-rule-scope")["background"]
    hint = _cascade("desktop", ".allow-rule-hint")["color"]
    scope_text = _cascade("desktop", ".allow-rule-scope-sentence")["color"]
    losing = {}
    for name, theme in themes.items():
        hint_ratio = _ratio(hint, box_bg, theme)
        scope_ratio = _ratio(scope_text, scope_bg, theme)
        if scope_ratio < hint_ratio * 0.9:
            losing[name] = (scope_ratio, hint_ratio)
    assert not losing, losing

    # Two palettes put *every* string in the app under 4.5:1 against their own
    # panel — `B15` measured `cute` at 3.44 and `retrowave` at 4.15. That
    # ceiling belongs to the palette and not to this control, and it is named
    # here on purpose rather than papered over.
    under = sorted(n for n, v in measured.items() if v[0] < 4.5)
    assert under == ["cute", "retrowave"], (
        f"the set of palettes that cannot carry body text has changed: {under}"
    )


_REVOKE_STRINGS = (
    ".allow-rule-list-title", ".allow-rule-list-hint", ".allow-rule-list-status",
    ".allow-rule-list-empty", ".allow-rule-row-label", ".allow-rule-row-detail",
    ".allow-rule-row-sentence", ".allow-rule-row-when", ".allow-rule-revoke",
)


def test_every_string_on_the_revoke_screen_reads_exactly_as_well_as_the_ladder():
    """`P7-06`'s defect, kept out of the new screen the same way it was kept out
    of the old ones: not by clearing a threshold but by making the numbers equal.

    Every string here is `var(--fg)` on `var(--panel)`, which is what the rung
    rows above it are, so the ratios come out identical on all sixteen palettes
    and any recolour — of a string or of a ground — breaks this. The 3% panel
    tint `.allow-rule` uses on the approval card was tried here and dropped: it
    costs up to 8% of contrast (claude, 12.02 -> 11.02), and one of the strings
    it would have dimmed is the line that says a revoke failed.
    """

    themes = _themes()
    assert len(themes) >= 16, sorted(themes)

    rung_bg = _cascade("desktop", ".trust-rung")["background"]
    baseline = _cascade("desktop", ".trust-rung-sentence")["color"]
    grounds = {
        ".allow-rule-list-title": ".allow-rule-list",
        ".allow-rule-list-hint": ".allow-rule-list",
        ".allow-rule-list-status": ".allow-rule-list",
        ".allow-rule-list-empty": ".allow-rule-list",
        ".allow-rule-row-label": ".allow-rule-row",
        ".allow-rule-row-detail": ".allow-rule-row",
        ".allow-rule-row-sentence": ".allow-rule-row",
        ".allow-rule-row-when": ".allow-rule-row",
        ".allow-rule-revoke": ".allow-rule-revoke",
    }
    assert set(grounds) == set(_REVOKE_STRINGS)

    measured = {}
    off = {}
    for name, theme in themes.items():
        base = _ratio(baseline, rung_bg, theme)
        measured[name] = base
        for selector, box in grounds.items():
            ratio = _ratio(
                _cascade("desktop", selector)["color"],
                _cascade("desktop", box)["background"],
                theme,
            )
            if abs(ratio - base) > 0.001:
                off[(name, selector)] = (ratio, base)
    assert not off, (
        "a string on the revoke screen no longer reads as well as the prose in "
        "the ladder above it: " + ", ".join(
            f"{n} {s} ({v[0]:.2f} vs {v[1]:.2f})" for (n, s), v in sorted(off.items())
        )
    )

    # The palette ceiling, named rather than papered over — the same two the
    # ladder's own measurement names.
    under = sorted(name for name, base in measured.items() if base < 4.5)
    assert under == ["cute", "retrowave"], under


def test_the_revoke_screen_never_whispers_the_part_that_matters():
    """Read as values, never as property names. The status line is the only
    thing on this screen that reports a failed revoke — "so Pantheon can still
    do it without asking" — and a control that whispers that has not reported
    it at all."""

    hint = _cascade("desktop", ".allow-rule-list-hint")
    status = _cascade("desktop", ".allow-rule-list-status")
    assert _px(status["font-size"]) >= _px(hint["font-size"])
    assert int(status["font-weight"]) > int(hint["font-weight"])
    assert float(status["opacity"]) >= float(hint["opacity"])
    # And it reserves its line, so a status arriving does not shove the list.
    assert _px(status["min-height"]) > 0

    # An empty list is a sentence, not a blank space: the same size as the hint
    # that explains the screen, not a footnote to it.
    empty = _cascade("desktop", ".allow-rule-list-empty")
    assert _px(empty["font-size"]) >= _px(hint["font-size"])
    assert float(empty["opacity"]) >= float(hint["opacity"])

    # The button is a control, not a link: its own border and a weight above the
    # sentence beside it, so it is findable without reading the row.
    button = _cascade("desktop", ".allow-rule-revoke")
    sentence = _cascade("desktop", ".allow-rule-row-sentence")
    assert button["border"].split()[0] == "1px"
    assert int(button["font-weight"]) > int(sentence["font-weight"])
    assert button["cursor"] == "pointer"
    # In flight it is dimmed *and* disabled, so the two channels agree — a
    # button that only looks busy invites the second press that revokes twice.
    busy = _cascade("desktop", ".allow-rule-revoke:disabled")
    assert float(busy["opacity"]) < float(button.get("opacity", "1"))
    assert busy["cursor"] == "default"


def test_the_revoke_row_stacks_rather_than_squeezing_on_the_narrow_screen():
    """`P6-04` deleted a queue panel's state line under 768px and took the
    sentence saying the queue was paused away from the form factor with the
    least room to guess. Here the sentence and the button both have to survive:
    at 320px a Revoke held on the same line takes its width from the sentence
    that says what it revokes, and the sentence is the half that cannot be
    inferred from the other."""

    regions = _regions()
    for where in ("m768", "m640"):
        assert "display: none" not in regions[where], where

    # Untouched at 768 — the desktop row reaches the tablet intact.
    assert not _decls(".allow-rule-row", "m768")
    assert not _decls(".allow-rule-revoke", "m768")

    row = _effective("m640", ".allow-rule-row")
    assert row["flex-direction"] == "column"
    assert _effective("m640", ".allow-rule-revoke")["align-self"] == "stretch"

    # Nothing on this screen is hidden or shrunk below the sentence beside it.
    hint = _effective("m640", ".allow-rule-list-hint")
    status = _effective("m640", ".allow-rule-list-status")
    empty = _effective("m640", ".allow-rule-list-empty")
    assert _px(status["font-size"]) >= _px(hint["font-size"])
    assert _px(empty["font-size"]) >= _px(hint["font-size"])
    assert int(status["font-weight"]) > int(hint["font-weight"])


def test_the_list_stays_out_of_the_way_when_it_is_hidden():
    """`display: flex` beats the browser's own `[hidden]` rule, so without an
    explicit answer the list is emptied, marked hidden and drawn anyway — an
    empty bordered box under the ladder, which is the exact thing
    `#trust-ladder-card` starts hidden to avoid."""

    assert _decls(".allow-rule-list")["display"] == "flex"
    assert _decls(".allow-rule-list[hidden]")["display"] == "none"


def test_the_accent_appears_only_on_geometry_and_never_on_a_string():
    """`B16` records the accent-on-panel graphic at 2.24:1 on `paper`. That is
    acceptable here for exactly one reason: it is redundant to a rule width and
    a mark shape that a greyscale reader already resolves. It stops being
    acceptable the moment it carries a word."""

    block = _block()
    text_selectors = (
        ".trust-ladder-title", ".trust-ladder-intro", ".trust-ladder-note",
        ".trust-ladder-status", ".trust-rung-name", ".trust-rung-badge",
        ".trust-rung-sentence", ".trust-rung-cost", ".allow-rule-title",
        ".allow-rule-hint", ".allow-rule-scope-label", ".allow-rule-scope-detail",
        ".allow-rule-scope-sentence",
        # The revoke list. `Revoke` is the most important word on that screen
        # and `terminal` and `retrowave` give a hue nothing at all — `--fg` and
        # `--red` are the same hex on both.
        ".allow-rule-list-title", ".allow-rule-list-hint",
        ".allow-rule-list-status", ".allow-rule-list-empty",
        ".allow-rule-row-label", ".allow-rule-row-detail",
        ".allow-rule-row-sentence", ".allow-rule-row-when",
        ".allow-rule-revoke",
    )
    for selector in text_selectors:
        colour = _cascade("desktop", selector).get("color")
        if colour is None:
            continue
        assert "accent" not in colour and "--red" not in colour, (
            f"{selector} carries meaning in a hue: {colour}"
        )

    # The accent survives on geometry only: the 6px rule, the triangle, the
    # chosen-scope outline and the native radio's own dot.
    accented = re.findall(r"^\s*([a-z-]+)\s*:.*var\(--accent", block, re.M)
    assert set(accented) <= {
        "border-left-color", "border-bottom", "outline", "accent-color",
    }, sorted(set(accented))


def test_no_new_rule_reaches_for_a_bare_accent():
    """`--accent` is undefined until `P1-01` runs, so a bare `var(--accent)`
    makes the whole declaration invalid and the rule silently does nothing.
    This has bitten twice."""

    block = _block()
    reaching = [line.strip() for line in block.splitlines() if "var(--accent" in line]
    assert reaching, "the new rules should use the accent somewhere"
    for line in reaching:
        assert "var(--accent, var(--red))" in line or "accent-color" in line, line
    assert "--accent:" not in STYLE.read_text(encoding="utf-8").split(":root")[1].split("}")[0]


def test_the_ladder_has_a_home_in_the_markup_and_it_starts_hidden():
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="trust-ladder"' in index
    card = re.search(r'<div class="admin-card" id="trust-ladder-card"[^>]*>', index)
    assert card, "the ladder's card is missing"
    assert " hidden" in card.group(0), (
        "an empty bordered card in a settings panel reads as a feature that "
        "failed to load; it must not be shown until the ladder is drawn into it"
    )


def _code(source: str) -> str:
    """One JS file with its whole-line `//` comments blanked out.

    The assertions below are about what the code does, and this programme
    corrects a false comment *in place*: the claim that turned out wrong stays
    in the file, with a note saying what it used to say. So every one of these
    strings is expected to survive somewhere in the source, and only its
    absence from the executable half means anything.
    """
    return "\n".join(
        "" if re.match(r"\s*//", line) else line for line in source.splitlines()
    )


def test_the_module_does_not_stage_a_disagreement_the_store_no_longer_has():
    """`documentation-is-false`. `allowRuleScopes`'s comment cited
    `src/tool_allow_rules.py:48` as saying its tuple is *"ordered widest-first,
    which is the order a chooser should present them in"* and stated a
    disagreement with it. That line was corrected on 2026-08-29 and now hands
    presentation order to the chooser — so the citation pointed at a sentence
    that no longer exists, and a reader who followed it would have found the two
    files agreeing and assumed one of them was stale.

    Corrected, not deleted: this programme keeps its corrections, so the quote
    stays and the note beside it says what it used to claim and why that was
    wrong. Both halves are asserted — reverting to the old text fails, and so
    does quietly dropping the sentence that was corrected.
    """

    store = (ROOT / "src" / "tool_allow_rules.py").read_text(encoding="utf-8")
    assert "Presentation order is" in store and "chooser's call" in store, (
        "the store's own line has changed again; re-read it before trusting "
        "the note in trustLadder.js"
    )

    module = TRUST_LADDER.read_text(encoding="utf-8")
    quote = "ordered widest-first"
    hits = [i for i in range(len(module)) if module.startswith(quote, i)]
    assert hits, "the corrected comment must keep the claim it is correcting"
    for index in hits:
        assert "CORRECTED" in module[max(0, index - 900):index], (
            "the store's widest-first sentence is quoted as if it were current"
        )


def test_the_module_keeps_no_second_copy_of_the_stores_match_kinds():
    """`src/tool_allow_rules.py` says `GET` returns `MATCH_KINDS` *"so nothing
    keeps a second copy of the three strings"*. `ALLOW_RULE_MATCH_KINDS` was
    exactly that second copy, described as "the store's kinds". It could only
    narrow, never widen, so it was not a security hole — but the claim was false
    as written and a kind added to the store would have been dropped with
    nothing said.

    What is left is a wording table, which is a different thing and is allowed
    to be incomplete: a kind it cannot phrase is not offered as a choice (a
    blank button posts a rule nobody can read back) and *is* still listed and
    revocable. Both behaviours are driven above; this pins the claim.
    """

    module = TRUST_LADDER.read_text(encoding="utf-8")
    code = _code(module)
    assert "ALLOW_RULE_MATCH_KINDS" not in code
    assert not re.search(
        r"\[\s*'(any|exact|prefix)'\s*,\s*'(any|exact|prefix)'\s*,"
        r"\s*'(any|exact|prefix)'\s*\]",
        code,
    ), "the three strings are back as a list"
    # And the note explaining the removal survives, so the next reader does not
    # helpfully add it again.
    assert "ALLOW_RULE_MATCH_KINDS" in module and "second copy" in module


def test_the_renderer_commits_on_a_named_yes_and_not_on_the_absence_of_one():
    """`wrong-but-contained`, latent. The guard read
    `detail.decision !== 'deny'` — a blacklist of one string, beside a comment
    claiming the opposite. A denial button with no `value`, or any second
    denial, created the standing rule. The behaviour is driven above; this pins
    the shape, because the shape is the whole defect."""

    renderer = CHAT_RENDERER.read_text(encoding="utf-8")
    code = _code(renderer)
    assert "detail.decision !== 'deny'" not in code
    assert 'detail.decision !== "deny"' not in code
    assert "!== 'deny'" not in code and '!== "deny"' not in code
    # The corrected comment keeps the line it replaced, and says why.
    assert "detail.decision !== 'deny'" in renderer
    # The two values `scope_for_decision` (src/tool_approval_scopes.py) answers
    # to, and no third.
    scopes = (ROOT / "src" / "tool_approval_scopes.py").read_text(encoding="utf-8")
    assert 'TASK_APPROVAL_DECISION = "approve_task"' in scopes
    assert 'CHAT_SESSION_APPROVAL_DECISION = "approve"' in scopes
    match = re.search(
        r"APPROVAL_DECISIONS_THAT_GRANT\s*=\s*\[([^\]]*)\]", renderer
    )
    assert match, "the affirmative decisions are no longer a named set"
    assert sorted(re.findall(r"'([^']+)'", match.group(1))) == ["approve", "approve_task"]


def test_the_renderer_owns_no_second_copy_of_the_trust_vocabulary():
    """One module holds the words for both surfaces. A second copy drifts, and
    then the same choice reads as two different promises in two places — which
    is the defect `P7-06` found three times in one payload."""

    renderer = CHAT_RENDERER.read_text(encoding="utf-8")
    assert "from './trustLadder.js'" in renderer
    for phrase in ("Stop asking about this", "Anything starting with",
                   "Only this exact command"):
        assert phrase not in renderer, phrase
    for rung in RUNGS:
        assert rung not in renderer, rung
