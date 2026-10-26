# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B801` — email actions flipped the person's settings on disk, ran, and flipped back.

`routes/email_pollers._run_auto_summarize_once` — behind the `summarize_emails`,
`draft_email_replies` and `extract_email_events` actions — set six
email-automation keys and called `_save_settings` (`data/settings.json`)
before the pass, restoring them in a `finally`. A `finally` does not run in a
killed process, and two of these overlapping interleave their save-and-restore
so the second restore writes the first's temporary values as the person's.
The row: *the shared-state shape is the defect, not the restore.*

Now the flags are handed to the pass and laid over the settings it reads, in
memory. Driven (`Law 20`) through the three real actions in
`src/builtin_actions` down to the real pass, with `src.settings` on a temp file
and a throwaway database; the mail server is the one far end replaced — its
opener records what the pass was told to do and what the file held at that
moment, then refuses, the way an unreachable server does.

(`email_auto_translate`, the fourth action the row names, reads its own
setting and no longer goes through `_run_auto_summarize_once` — re-measured,
`action_email_auto_translate` — so it never wrote these keys.)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.test_a_mail_setting_is_saved_through_the_one_door import db, store  # noqa: F401

_FLAGS = ("email_auto_summarize", "email_auto_reply", "_email_auto_reply_draft_only",
          "email_auto_tag", "email_auto_spam", "email_auto_calendar")


@pytest.fixture
def mailbox(store, db, monkeypatch):  # noqa: F811
    """The pass's view at the moment it opens the mailbox: the flags it runs
    with, and the settings file's bytes then — what a kill there would leave."""
    import routes.email_pollers as P

    path = Path(store.SETTINGS_FILE)
    seen = []
    real = P._effective_settings_for_email_account

    def effective(settings, account_id):
        out = real(settings, account_id)
        seen.append({"flags": {k: bool(out.get(k, False)) for k in _FLAGS},
                     "file": path.read_bytes()})
        return out

    def unreachable(*a, **k):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(P, "_effective_settings_for_email_account", effective)
    monkeypatch.setattr(P, "_imap_connect", unreachable)
    return {"path": path, "before": path.read_bytes(), "seen": seen}


@pytest.mark.parametrize("action, asked", [
    ("action_summarize_emails", {"email_auto_summarize"}),
    ("action_draft_email_replies", {"email_auto_reply", "_email_auto_reply_draft_only"}),
    ("action_extract_email_events", {"email_auto_calendar"}),
])
def test_each_email_task_runs_its_flags_and_never_writes_the_file(mailbox, action, asked):
    """The row's `Verify:`, first half — and the pass still runs what it was asked."""
    from src import builtin_actions

    asyncio.run(getattr(builtin_actions, action)("ada"))

    assert mailbox["seen"], "the pass never ran"
    for look in mailbox["seen"]:
        assert {k for k, on in look["flags"].items() if on} == asked
        assert look["file"] == mailbox["before"], "settings.json changed while the task ran"
    assert mailbox["path"].read_bytes() == mailbox["before"]


def test_a_task_cancelled_mid_run_leaves_the_file_byte_identical(mailbox, monkeypatch):
    """The row's `Verify:`, second half. A task timeout (`P8-32`) cancels the
    run; a killed process does not even get that far — so what matters is the
    file *during* the run, and that a cancel changes nothing either."""
    import routes.email_pollers as P

    parked = asyncio.Event()

    async def park(progress_cb, message):
        parked.set()
        await asyncio.Event().wait()         # never set: held mid-run

    monkeypatch.setattr(P, "_emit_progress", park)

    async def go():
        task = asyncio.ensure_future(P._run_auto_summarize_once(
            do_summary=True, do_reply=True, do_tag=True, do_spam=True, do_calendar=True,
            progress_cb=lambda m: None))
        await asyncio.wait_for(parked.wait(), 10)
        during = mailbox["path"].read_bytes()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return during

    during = asyncio.run(go())
    assert during == mailbox["before"], "the flags were on disk mid-run — a kill there keeps them"
    assert mailbox["path"].read_bytes() == mailbox["before"]


def test_two_overlapping_tasks_each_run_their_own_flags(mailbox, monkeypatch):
    """`B603`'s neighbourhood: a summary and a calendar scan at once. Each pass
    runs only what it was asked, and neither leaves the other's flags behind."""
    import routes.email_pollers as P

    both_in = asyncio.Event()
    inside = []

    async def meet(progress_cb, message):
        inside.append(message)
        if len(inside) >= 2:
            both_in.set()
        await asyncio.wait_for(both_in.wait(), 10)

    monkeypatch.setattr(P, "_emit_progress", meet)

    async def go():
        return await asyncio.gather(
            P._run_auto_summarize_once(do_summary=True, do_reply=False, progress_cb=lambda m: None),
            P._run_auto_summarize_once(do_summary=False, do_reply=False, do_calendar=True,
                                       progress_cb=lambda m: None),
        )

    asyncio.run(go())
    ran = sorted(tuple(sorted(k for k, on in look["flags"].items() if on))
                 for look in mailbox["seen"])
    assert ran == [("email_auto_calendar",), ("email_auto_summarize",)]
    assert mailbox["path"].read_bytes() == mailbox["before"]
