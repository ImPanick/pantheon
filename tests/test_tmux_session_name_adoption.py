"""P0-31 — the agent's persistent shell was named after the fork.

Every chat session gets a tmux session, and it was called `ody-agent-<id>`.
Renaming that prefix looks like the same kind of cosmetics as a CSS keyframe,
and it is not: the name is how the code finds a shell that is already running.
A bare rename means the next command looks for `pan-agent-<id>`, does not find
it, and creates a second shell — so the first one's working directory, its
exported variables and anything it had backgrounded are gone from the user's
point of view, while the process itself keeps running until the machine
restarts. Nothing reports either half.

So the new name is what gets created, and a session still alive under an older
prefix is adopted. Same shape as the API-token prefix in the same row, for the
same reason: the old name is still out there on a machine somebody is using.
"""
import asyncio

import pytest

import src.agent_tools.subprocess_tools as st


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.setattr(st, "_RESOLVED_TMUX_NAMES", {})


def _resolve(session_id):
    return asyncio.run(st._resolve_tmux_session_name(session_id))


def _existing(*names):
    """Stub `tmux has-session` and record what was probed, in order."""
    probed = []

    async def _has(name):
        probed.append(name)
        return name in names

    return _has, probed


def test_a_fresh_session_gets_the_current_prefix(monkeypatch):
    has, probed = _existing()
    monkeypatch.setattr(st, "_tmux_has_session", has)
    assert _resolve("s1") == "pan-agent-s1"
    assert st.TMUX_SESSION_PREFIX == "pan-agent-"


def test_a_live_session_under_the_old_prefix_is_adopted(monkeypatch):
    has, probed = _existing("ody-agent-s1")
    monkeypatch.setattr(st, "_tmux_has_session", has)
    assert _resolve("s1") == "ody-agent-s1", (
        "a shell the user is in the middle of using was abandoned, and left "
        "running, by a rename that only changed what we create"
    )
    assert probed == ["pan-agent-s1", "ody-agent-s1"], probed


def test_the_current_name_wins_when_both_exist(monkeypatch):
    has, probed = _existing("pan-agent-s1", "ody-agent-s1")
    monkeypatch.setattr(st, "_tmux_has_session", has)
    assert _resolve("s1") == "pan-agent-s1"
    assert probed == ["pan-agent-s1"], "should not have looked further"


def test_the_probe_runs_once_per_session(monkeypatch):
    has, probed = _existing()
    monkeypatch.setattr(st, "_tmux_has_session", has)
    for _ in range(5):
        assert _resolve("s1") == "pan-agent-s1"
    assert len(probed) == len(st.LEGACY_TMUX_SESSION_PREFIXES) + 1, (
        "the adoption probe was riding every bash call: " + repr(probed)
    )


def test_the_reported_name_is_the_one_the_command_ran_in(monkeypatch):
    """`bash` returns `tmux_session` to the caller. Recomputing it instead of
    reading the resolution would name a session that does not exist."""
    has, _ = _existing("ody-agent-s1")
    monkeypatch.setattr(st, "_tmux_has_session", has)
    assert st._tmux_session_name("s1") == "pan-agent-s1", "before resolution"
    _resolve("s1")
    assert st._tmux_session_name("s1") == "ody-agent-s1", "after adoption"


def test_the_slug_is_unchanged_by_the_rename():
    """Only the prefix moved. A different sanitiser would miss every live
    session for a different reason."""
    assert st._tmux_session_slug("abc/def") == "abc-def"
    assert st._tmux_session_slug(None) == "default"
    assert st._tmux_session_slug("") == "default"
    assert st._tmux_session_slug("-" * 5) == "default"
    assert len(st._tmux_session_slug("x" * 200)) == 80
    for name in (st._tmux_session_name("abc/def"), "ody-agent-" + st._tmux_session_slug("abc/def")):
        assert name.endswith("abc-def")


def test_the_cache_does_not_grow_without_bound(monkeypatch):
    has, _ = _existing()
    monkeypatch.setattr(st, "_tmux_has_session", has)
    for i in range(st._MAX_RESOLVED_TMUX_NAMES + 25):
        _resolve(f"s{i}")
    assert len(st._RESOLVED_TMUX_NAMES) <= st._MAX_RESOLVED_TMUX_NAMES
