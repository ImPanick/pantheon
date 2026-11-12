# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2099`. The Email Tags task's "Email triage rules" box changed nothing.

`action_check_email_urgency` cached the keyword verdict and then hit an
unconditional `continue`, so the model step after it, the only reader of
`urgent_email_prompt`, could not run. Now a message the keywords leave
untagged (no tags, the keyword rule's default reason) goes to the task's model
once, with the person's rules in the prompt; a message the keywords recognise
never reaches a model; and a model that gives no usable answer leaves the
keyword verdict standing, uncached, so the next run asks again.

Driven (`Law 20`): the real action over the fake mailbox of
`tests/test_email_urgency_checkpoint.py`, with the model call replaced.
"""
import json

from src import llm_core

PLAIN = (
    b"From: Pat <pat@example.test>\r\n"
    b"Subject: Lunch\r\n"
    b"Message-ID: <plain-1@example.test>\r\n"
    b"\r\n"
    b"The blue house on the corner, if you are around."
)

RECEIPT = (
    b"From: Acme Store <receipts@acme.example>\r\n"
    b"Subject: Your receipt from Acme Store\r\n"
    b"Message-ID: <receipt-1@acme.example>\r\n"
    b"\r\n"
    b"Thanks for your order. Payment received: $42.00. Receipt #1234."
)

RULES = "Anything from Pat is urgent."


def _mailbox(monkeypatch, tmp_path, raw):
    import routes.note_routes as note_routes
    from routes import email_helpers
    from tests.test_email_urgency_checkpoint import _FakeImap, _configure_action

    builtin_actions, runtime = _configure_action(monkeypatch, tmp_path, ["acct-a"])
    runtime["settings"]["urgent_email_prompt"] = RULES

    class _Mailbox(_FakeImap):
        def uid(self, command, *args):
            status, data = super().uid(command, *args)
            if command == "FETCH" and str(args[-1]) != "(UID FLAGS)":
                data = [(data[0][0], raw)]
            return status, data

    monkeypatch.setattr(email_helpers, "_imap_connect", lambda account_id=None, **_kw: _Mailbox(
        str(account_id), runtime["failures"], runtime["seen_accounts"], runtime["search_uids"]))

    async def delivered(**_kwargs):
        return {"browser_sent": True, "email_sent": False, "ntfy_sent": False, "webhook_sent": False}

    monkeypatch.setattr(note_routes, "dispatch_reminder", delivered)
    return builtin_actions


def _cached(tmp_path):
    path = tmp_path / "urgency-cache" / "acct-a.json"
    return json.loads(path.read_text(encoding="utf-8")).get("uids", {}) if path.exists() else {}


async def test_a_rule_in_the_box_reaches_the_model_and_tags_mail_the_keywords_left_untagged(monkeypatch, tmp_path):
    builtin_actions = _mailbox(monkeypatch, tmp_path, PLAIN)
    prompts = []

    async def model(_candidates, messages, **_kwargs):
        prompts.append(messages[0]["content"])
        return '{"score": 3, "tags": ["action-needed"], "spam": false, "reason": "Pat is urgent by rule"}'

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", model)

    _message, ok = await builtin_actions.action_check_email_urgency("alice")

    assert ok is True
    assert len(prompts) == 1, "one model call for the one untagged message"
    assert RULES in prompts[0], "the person's rules are in the prompt"
    verdict = _cached(tmp_path)["1"]
    assert verdict["score"] == 3 and verdict["tags"] == ["action-needed"], verdict
    assert verdict["reason"] == "Pat is urgent by rule"


async def test_mail_the_keywords_recognise_never_reaches_a_model(monkeypatch, tmp_path):
    builtin_actions = _mailbox(monkeypatch, tmp_path, RECEIPT)
    calls = []

    async def model(*_args, **_kwargs):
        calls.append(1)
        return '{"score": 3, "tags": [], "reason": "should not be asked"}'

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", model)

    _message, ok = await builtin_actions.action_check_email_urgency("alice")

    assert ok is True
    assert calls == []
    assert "receipt" in _cached(tmp_path)["1"]["tags"]


async def test_a_model_with_no_answer_leaves_the_keyword_verdict_and_asks_again_next_run(monkeypatch, tmp_path):
    builtin_actions = _mailbox(monkeypatch, tmp_path, PLAIN)
    calls = []

    async def model(*_args, **_kwargs):
        calls.append(1)
        return "I cannot help with that."

    monkeypatch.setattr(llm_core, "llm_call_async_with_fallback", model)

    _message, ok = await builtin_actions.action_check_email_urgency("alice")
    assert ok is True
    assert "1" not in _cached(tmp_path), "a failed classification is not cached"

    _message, ok = await builtin_actions.action_check_email_urgency("alice")
    assert ok is True
    assert len(calls) == 2, "the next run asks the model again"
