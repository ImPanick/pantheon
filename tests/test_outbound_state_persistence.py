# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cooldowns survive a restart (`P15-09`).

The row's own framing: *"Restart Pantheon while GitHub has you in a forty-minute
penalty and it starts asking again immediately — and a crash-loop plus a rate
limit is exactly the pair that turns a soft ban into a hard one."*

THE CLOCK DOMAIN IS THE WHOLE ROW, AND THE NAIVE VERSION PASSES A CASUAL TEST.

`blocked_until` is a `time.monotonic()` reading, whose origin is arbitrary and
per-boot. Persisting that number and reading it back in a new process compares
it against a different origin. Restart WITHOUT a reboot and monotonic has kept
counting, so it appears to work perfectly; restart AFTER a reboot — which is
what a crash-loop and a power cut produce, and the only case that matters — and
the answer is unrelated to reality.

So the tests below simulate a *reboot*, not just a new object: they move the
monotonic origin as well as the process. A test that only builds a second
limiter in the same process proves nothing, and that is the trap this file
exists to avoid falling into.
"""
import json
import time

import pytest

from src import rate_limiter as rl
from src.rate_limiter import OutboundHostLimiter


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "outbound_state.json"
    monkeypatch.setattr("src.constants.OUTBOUND_STATE_FILE", str(path))
    return path


def _fresh():
    """A limiter as it exists one instant after start-up."""
    return OutboundHostLimiter()


def _reboot(monkeypatch, *, seconds_elapsed=0.0):
    """Simulate a restart across a REBOOT.

    Two things move: wall-clock time advances by `seconds_elapsed` (the outage),
    and the monotonic origin resets to zero (the reboot). The second is what
    separates a real test of this from a test that would also pass if the code
    persisted the raw monotonic number.
    """
    wall_at_call = time.time()
    monkeypatch.setattr(rl.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(rl.time, "time", lambda: wall_at_call + seconds_elapsed)


def test_a_cooldown_survives_a_restart(state_file, monkeypatch):
    """The row's `Verify:` line, exactly."""
    before = _fresh()
    imposed = before.penalise("api.github.com", base=2400.0, cap=3600.0,
                              reason="secondary rate limit")
    assert imposed >= 2400.0
    assert state_file.exists(), "the penalty never reached disk"

    _reboot(monkeypatch, seconds_elapsed=60.0)
    after = _fresh()
    remaining = after.blocked_for("api.github.com")
    assert remaining > 0, "restarted straight back into asking"
    # 60 seconds of the penalty were served while the process was down.
    assert imposed - 65 <= remaining <= imposed - 55


def test_the_stored_deadline_is_wall_clock_not_a_monotonic_reading(state_file):
    """The defect at the source rather than through its symptom.

    `time.monotonic()` on a long-running Linux box is a few hundred thousand at
    most and counts from boot; `time.time()` is ~1.7e9 and counts from 1970.
    They are never confusable by accident, which makes this a cheap, exact
    assertion about which clock was written.
    """
    limiter = _fresh()
    limiter.penalise("mail.example.test", base=600.0)
    doc = json.loads(state_file.read_text(encoding="utf-8"))
    stored = doc["hosts"]["mail.example.test"]["until"]
    assert abs(stored - (time.time() + 600)) < 120, \
        f"{stored} is not a wall-clock deadline — a monotonic reading was persisted"
    assert stored > 1_600_000_000, "that number is not an epoch timestamp"


def test_a_penalty_that_expired_while_the_process_was_down_is_not_restored(
        state_file, monkeypatch):
    """Dropped rather than restored as a zero-length block, so the file shrinks
    on its own and a long shutdown leaves nothing behind."""
    before = _fresh()
    before.penalise("slow.example.test", base=60.0, cap=60.0)

    _reboot(monkeypatch, seconds_elapsed=86_400)
    after = _fresh()
    assert after.blocked_for("slow.example.test") == 0
    assert after.load_persisted() == 0


def test_the_escalation_ladder_survives_too(state_file, monkeypatch):
    """Half the value of the row. A crash-loop that resets `consecutive_429`
    re-earns the ban from the base cooldown every time, which is slower to
    recover than not escalating at all."""
    before = _fresh()
    for _ in range(4):
        before.penalise("api.github.com", base=10.0, cap=100_000.0)
    fourth = before.snapshot()["api.github.com"]["consecutive_429"]
    assert fourth == 4

    _reboot(monkeypatch, seconds_elapsed=1.0)
    after = _fresh()
    after.load_persisted()
    assert after.snapshot()["api.github.com"]["consecutive_429"] == 4
    # And the NEXT penalty continues the ladder rather than restarting it.
    fifth = after.penalise("api.github.com", base=10.0, cap=100_000.0)
    assert fifth >= 10.0 * (2 ** 4)


def test_an_account_scoped_key_round_trips(state_file, monkeypatch):
    """`penalise` keys need not be hostnames — two mailboxes on one provider
    fail independently, and the IMAP penalties are the ones a restart can least
    afford to forget."""
    before = _fresh()
    before.penalise("imap:me@example.test", base=900.0, reason="AUTHENTICATIONFAILED")
    before.penalise("imap:other@example.test", base=900.0)

    _reboot(monkeypatch, seconds_elapsed=5.0)
    after = _fresh()
    assert after.blocked_for("imap:me@example.test") > 0
    assert after.blocked_for("imap:other@example.test") > 0
    # The two mailboxes keep separate ladders across the restart — one stale
    # password must not silence the other account.
    assert after.snapshot()["imap:me@example.test"]["consecutive_429"] == 1
    doc = json.loads(state_file.read_text(encoding="utf-8"))
    assert doc["hosts"]["imap:me@example.test"]["why"] == "AUTHENTICATIONFAILED"


def test_a_success_clears_the_file_so_a_restart_does_not_resurrect_the_penalty(
        state_file, monkeypatch):
    """The same defect pointing the other way: a cooldown the provider has
    already forgiven must not come back at the next restart."""
    before = _fresh()
    before.penalise("api.github.com", base=1800.0)
    before.succeeded("api.github.com")
    assert json.loads(state_file.read_text(encoding="utf-8"))["hosts"] == {}

    _reboot(monkeypatch, seconds_elapsed=1.0)
    after = _fresh()
    assert after.blocked_for("api.github.com") == 0


def test_an_http_429_is_persisted_as_well_as_a_penalty(state_file, monkeypatch):
    """`observe` is the path every HTTP caller takes; `penalise` is the one for
    protocols with no status code. Both have to write, and testing only the
    second would leave the commonest case unproven."""
    before = _fresh()
    before.observe("api.github.com", 429, {"Retry-After": "1800"})

    _reboot(monkeypatch, seconds_elapsed=30.0)
    after = _fresh()
    assert 1700 < after.blocked_for("api.github.com") <= 1800


def test_reset_clears_the_file_too(state_file):
    """An operator's 'clear this' that came back after a restart would be a
    surprising way for the button not to work."""
    limiter = _fresh()
    limiter.penalise("api.github.com", base=600.0)
    limiter.reset()
    assert json.loads(state_file.read_text(encoding="utf-8"))["hosts"] == {}
    assert limiter.blocked_for("api.github.com") == 0


def test_a_reset_holds_even_when_the_file_cannot_be_rewritten(state_file, monkeypatch):
    """The narrow case that makes `reset()`'s `_loaded = True` load-bearing.

    Normally the reset's own write leaves an empty file, so a later reload
    restores nothing and the flag changes no outcome — mutating it away survives
    every other test here. It matters exactly when the write FAILS: the file
    still names the blocked host, and without the flag the next read path would
    reload it and silently undo the operator's clear inside the same process.

    Kept and tested on this case rather than deleted, for the same reason
    `P16-12` kept its `# TYPE` de-duplication guard: the failure it prevents is
    invisible and the line is one assignment.
    """
    # A penalty from the PREVIOUS run, and a limiter that has not loaded yet —
    # which is the realistic shape: an operator clears cooldowns right after a
    # restart, before anything else has touched the limiter. Penalising first
    # would set `_loaded` on the way in and hide what this is testing.
    state_file.write_text(json.dumps({
        "version": 1,
        "hosts": {"api.github.com": {"until": time.time() + 3600, "n": 3}},
    }), encoding="utf-8")
    limiter = _fresh()
    assert limiter._loaded is False, "the limiter loaded too early to test this"

    def _boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr("core.atomic_io.atomic_write_json", _boom)

    limiter.reset()
    # The file still says blocked, because the clearing write could not land.
    assert json.loads(state_file.read_text(encoding="utf-8"))["hosts"], \
        "the fixture for this test is wrong — the write did land"
    # The reset still holds in this process.
    assert limiter.blocked_for("api.github.com") == 0
    assert limiter.snapshot().get("api.github.com", {}).get("blocked_for", 0) == 0


def test_reset_does_not_immediately_reload_what_it_just_cleared(state_file):
    limiter = _fresh()
    limiter.penalise("api.github.com", base=600.0)
    limiter.reset()
    # Any read path calls `_ensure_loaded`; it must not undo the reset.
    assert limiter.blocked_for("api.github.com") == 0
    # `blocked_for` creates the (empty) state row as a side effect, which
    # predates this row — so the assertion is on the block, not on the dict
    # being absent, which would be testing `_st` rather than the reload.
    assert limiter.snapshot().get("api.github.com", {}).get("blocked_for", 0) == 0
    assert limiter.snapshot().get("api.github.com", {}).get("consecutive_429", 0) == 0


# --------------------------------------------------------------------------
# Bounds and bad input — a limiter that raises is worse than one that forgets
# --------------------------------------------------------------------------

def test_a_wall_clock_that_jumped_cannot_impose_an_unbounded_block(
        state_file, monkeypatch):
    """Not policy about how long a host may block us — `observe` honours a long
    `Retry-After` in-process. A bound on how much damage a corrupt file or a
    clock that moved can do."""
    state_file.write_text(json.dumps({
        "version": 1,
        "hosts": {"api.github.com": {"until": time.time() + 400 * 86400, "n": 1}},
    }), encoding="utf-8")
    limiter = _fresh()
    limiter.load_persisted()
    assert 0 < limiter.blocked_for("api.github.com") <= rl.MAX_RESTORED_COOLDOWN


@pytest.mark.parametrize("content", [
    "",
    "not json at all",
    "[]",
    '{"version": 999, "hosts": {"a": {"until": 99999999999}}}',
    '{"version": 1, "hosts": "not a dict"}',
    '{"version": 1, "hosts": {"a": "not a dict"}}',
    '{"version": 1, "hosts": {"a": {"until": "soon"}}}',
    '{"version": 1, "hosts": {"a": {}}}',
])
def test_a_corrupt_or_foreign_state_file_starts_clean_instead_of_raising(
        state_file, content):
    """A limiter that raises on a bad file takes down every outbound call in the
    product. Forgetting a cooldown is the lesser failure, and it is the one that
    self-corrects on the next 429."""
    state_file.write_text(content, encoding="utf-8")
    limiter = _fresh()
    assert limiter.load_persisted() == 0
    assert limiter.blocked_for("a") == 0
    limiter.observe("a", 200, {})          # still fully functional


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("src.constants.OUTBOUND_STATE_FILE",
                        str(tmp_path / "nope" / "outbound_state.json"))
    limiter = _fresh()
    assert limiter.load_persisted() == 0
    assert limiter.blocked_for("api.github.com") == 0


def test_an_unwritable_data_dir_does_not_break_outbound_calls(state_file, monkeypatch):
    """The cooldown still applies in this process; it just does not survive a
    restart. Degrading is right — refusing to pace because a file will not open
    would turn a disk problem into a rate-limit ban."""
    def _boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr("core.atomic_io.atomic_write_json", _boom)
    limiter = _fresh()
    imposed = limiter.penalise("api.github.com", base=600.0)
    assert imposed >= 600.0
    assert limiter.blocked_for("api.github.com") > 0


# --------------------------------------------------------------------------
# What is deliberately NOT persisted
# --------------------------------------------------------------------------

def test_pacing_and_per_process_counters_are_not_carried_across_a_restart(state_file):
    """Pacing is sub-second and re-earned in one request. The counters feed
    `pantheon_outbound_*`, and carrying them across a restart would make a gauge
    that says 'this process' quietly mean something else."""
    limiter = _fresh()
    limiter.penalise("api.github.com", base=600.0)
    entry = json.loads(state_file.read_text(encoding="utf-8"))["hosts"]["api.github.com"]
    assert set(entry) <= {"until", "n", "why"}, f"more than the boring state: {entry}"


def test_an_install_that_has_never_been_rate_limited_has_no_state_file(state_file):
    """The steady state is an empty projection that is never written at all —
    which is why the write path needs no debounce, and why a fresh data
    directory does not gain a permanent artefact describing the default state.

    Also the reason this cannot be a `tmp_path` root file in the suite fixture:
    an unconditional write puts it inside every test's working directory.
    """
    limiter = _fresh()
    for _ in range(50):
        limiter.observe("api.github.com", 200, {})
    limiter.succeeded("api.github.com")
    limiter.reset()
    assert not state_file.exists(), "a file was created to record that nothing is wrong"


def test_a_stale_file_is_overwritten_rather_than_left_saying_a_host_is_blocked(
        state_file, monkeypatch):
    """`_last_written` starts as `None`, which is not the same as `{}`: on the
    first change the file must be written even when the projection is empty,
    because the previous run may have left one behind."""
    state_file.write_text(json.dumps({
        "version": 1,
        "hosts": {"api.github.com": {"until": time.time() + 3600, "n": 3}},
    }), encoding="utf-8")
    limiter = _fresh()
    limiter.succeeded("api.github.com")
    assert json.loads(state_file.read_text(encoding="utf-8"))["hosts"] == {}


def test_every_mutating_entry_point_restores_before_it_decides(state_file, monkeypatch):
    """A load someone has to remember to call is a load that gets forgotten in
    one entry point, and the symptom — a cooldown that silently does not apply —
    is precisely what this row is fixing. So it is lazy and unconditional."""
    state_file.write_text(json.dumps({
        "version": 1,
        "hosts": {"api.github.com": {"until": time.time() + 3600, "n": 2}},
    }), encoding="utf-8")

    for probe in (
        lambda lim: lim.blocked_for("api.github.com"),
        lambda lim: lim.snapshot().get("api.github.com", {}).get("blocked_for", 0),
        lambda lim: lim.observe("api.github.com", 200, {}) or lim.blocked_for("api.github.com"),
    ):
        lim = _fresh()
        assert probe(lim) > 0, "this entry point decided without restoring first"

    # `acquire` is the one that matters most: it is what actually stops a call.
    lim = _fresh()
    with pytest.raises(rl.OutboundRateLimited):
        lim.acquire("api.github.com")
