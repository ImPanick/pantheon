"""A mailbox that will not answer must stop being asked every sixty seconds.

`/unread-state` is index-first *specifically* so periodic UI polling does not
hit the provider -- its own docstring says so. But the guard was
`if indexed_total:`, and the account most likely to have an empty index is the
one whose IMAP is **failing**, because a failing account never indexes. So the
one mailbox that must not be retried was the only one that always was: a live
login attempt every 60 seconds, in every open tab, indefinitely. Repeated
failing logins are what providers lock accounts for.

The trap, and why a naive fix does nothing: `_list_emails_sync` catches every
exception and reports failure as an `error` key on an otherwise empty result.
A backoff hung on `except` around it never fires. From the poll's side, a
mailbox refusing logins for a week looks exactly like one with no unread mail.
"""
import pytest

from src.rate_limiter import OutboundHostLimiter


@pytest.fixture
def limiter(monkeypatch):
    import src.rate_limiter as rl

    lim = OutboundHostLimiter({})
    monkeypatch.setattr(rl, "outbound", lim)
    return lim


KEY = "imap-unread:acct"


def test_a_failing_mailbox_backs_off_and_the_delay_grows(limiter):
    """Assert growth the jitter cannot fake.

    `second > first` is the obvious assertion and it is both flaky and vacuous:
    penalties carry up to 20% jitter, so with escalation deleted entirely the
    two draws still come out in increasing order about half the time. A mutation
    run caught it. Compare against a multiple the jitter band cannot reach.
    """
    delays = [limiter.penalise(KEY, base=120.0, cap=3600.0, reason="AUTH") for _ in range(4)]
    assert delays[0] >= 120.0
    # Geometric from 120 gives 120/240/480/960; a flat 120 with <=20% jitter
    # can never exceed 144, so 3x the base separates the two hypotheses cleanly.
    assert delays[3] >= 3 * 120.0, f"not escalating: {[round(d) for d in delays]}"
    assert delays[3] > delays[0] * 2


def test_the_first_backoff_dwarfs_the_poll_interval(limiter):
    """The poll is every 60s. A backoff shorter than that changes nothing."""
    delay = limiter.penalise(KEY, base=120.0, cap=3600.0)
    assert delay >= 120.0, f"{delay:.0f}s against a 60s tick is not a backoff"


def test_the_backoff_is_capped(limiter):
    for _ in range(40):
        delay = limiter.penalise(KEY, base=120.0, cap=3600.0)
    assert delay <= 3600.0 * 1.25


def test_two_mailboxes_at_one_provider_fail_independently(limiter):
    """One stale password must not silence the user's other accounts.

    Both halves are asserted deliberately. Checking only that the *other*
    account is clear passes trivially when the penalty is written to the wrong
    key entirely -- in which case nothing is blocked, including the mailbox that
    is actually failing. A mutation run found exactly that.
    """
    limiter.penalise("imap-unread:work", base=120.0)
    assert limiter.blocked_for("imap-unread:work") > 0, "the failing account was not blocked"
    assert limiter.blocked_for("imap-unread:personal") == 0, "an unrelated account was blocked"


def test_a_working_poll_clears_the_penalty(limiter):
    limiter.penalise(KEY, base=120.0)
    limiter.penalise(KEY, base=120.0)
    assert limiter.blocked_for(KEY) > 0
    limiter.succeeded(KEY)
    assert limiter.blocked_for(KEY) == 0
    assert limiter.penalise(KEY, base=120.0) < 200, "the ladder did not reset on success"


def test_the_backoff_has_jitter(limiter):
    """Every tab, and every install, must not come back at the same instant."""
    seen = {limiter.penalise(f"imap-unread:{i}", base=120.0) for i in range(12)}
    assert len(seen) > 1, "every first penalty was identical"


def test_penalise_survives_a_key_that_is_not_a_hostname(limiter):
    """The key is the account, deliberately -- see penalise()'s docstring."""
    limiter.penalise("imap-unread:user@example.com/INBOX", base=30.0)
    assert limiter.blocked_for("imap-unread:user@example.com/INBOX") > 0


# ── the part that makes the wiring real ──────────────────────────────────

def _handler_source() -> str:
    import pathlib

    return pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "routes/email_routes.py"
    ).read_text(encoding="utf-8")


def test_the_fallback_is_gated_before_it_runs():
    """A cooldown that is recorded and never consulted is decoration."""
    src = _handler_source()
    gate = src.index("poll_key = f\"imap-unread:")
    call = src.index("_list_emails_sync, folder, 1, 0, \"unread\"", gate)
    between = src[gate:call]
    assert "blocked_for(poll_key)" in between, (
        "the live IMAP call is not gated on the cooldown that precedes it"
    )


def test_failure_is_read_from_the_result_not_only_from_an_exception():
    """The trap this row is really about.

    `_list_emails_sync` swallows everything and returns `{"error": ...}`. A fix
    that only wraps the call in `try/except` compiles, reads correctly, ships,
    and backs off exactly never.
    """
    src = _handler_source()
    start = src.index("poll_key = f\"imap-unread:")
    window = src[start:start + 3000]
    assert 'result.get("error")' in window, (
        "failure is detected only by exception; _list_emails_sync does not raise, "
        "so the backoff would never engage"
    )
    assert "penalise(poll_key" in window


def test_list_emails_sync_really_does_swallow():
    """Pin the premise. If this ever starts raising, the fix above needs revisiting."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "routes/email_routes.py"
    ).read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_list_emails_sync"
    )
    tries = [b for b in fn.body if isinstance(b, ast.Try)]
    assert tries, "_list_emails_sync no longer wraps its body in try"
    broad = [
        h for t in tries for h in t.handlers
        if h.type is None or getattr(h.type, "id", "") == "Exception"
    ]
    assert broad, "no broad handler"
    for h in broad:
        assert not [x for x in ast.walk(h) if isinstance(x, ast.Raise)], (
            "_list_emails_sync now re-raises; the error-key check may be redundant"
        )
