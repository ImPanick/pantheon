# SPDX-License-Identifier: AGPL-3.0-or-later
r"""A slash command the user did not type must not become part of their chat.

This is what `P3-10b` found behind the year-old note *"Disabled for v1
stability"*. `handleSlashCommand` echoes the command it was given as a **user
message** and persists it, and every `slashReply` / `typewriterReply` persists
too. `_persistMsg` then does one more thing that turns a cosmetic problem into a
data one::

    if (!sid && sessionModule.hasPendingChat?.()) {
      await sessionModule.materializePendingSession?.();

So on a fresh install, opening Settings for the first time would have **created
a chat in the sidebar** containing `/tour-settings` — a command nobody wrote, in
a conversation nobody started. That is not an overlay problem, which is what the
stub's note guessed at, and it is why the fix is a pair of options rather than
better halo positioning.

`echo` and `persist` both default to what every hand-typed command has always
done, so the tests below check the default path too: an option that quietly
changed the behaviour of the chat box would be a worse bug than the one it
fixed. The production functions are lifted out and run — `_persistMsg` and
`handleSlashCommand` verbatim — rather than read and asserted on.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "static" / "js" / "slashCommands.js"
_HAS_NODE = shutil.which("node") is not None

pytestmark = pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")


def _function(name: str) -> str:
    text = _SRC.read_text(encoding="utf-8")
    match = re.search(
        rf"\n((?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{)",
        text,
    )
    assert match, f"{name} not found in slashCommands.js"
    start, i, depth = match.start(1), match.end(1), 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"{name} body did not close"
    return re.sub(r"^export\s+", "", text[start:i])


def _declaration(name: str) -> str:
    """A single `let <name> = <literal>;` line, so the test shares the real one."""
    text = _SRC.read_text(encoding="utf-8")
    match = re.search(rf"^let {re.escape(name)} = [^;]+;$", text, re.M)
    assert match, f"{name} declaration not found"
    return match.group(0)


_HARNESS = """
    const out = { added: [], posted: [], replies: [], materialised: 0 };

    // --- the two production functions, verbatim ---
    __DEPTH__
    __PERSIST__
    __HANDLE__

    // --- everything they reach for ---
    const API_BASE = 'http://x';
    let _sid = __SID__;
    const sessionModule = {
      getCurrentSessionId: () => _sid,
      hasPendingChat: () => __PENDING__,
      materializePendingSession: async () => { out.materialised += 1; _sid = 'made-up'; },
    };
    const fetch = async (url, opts) => {
      out.posted.push({ url, body: JSON.parse(opts.body) });
      return { ok: true, json: async () => ({}) };
    };
    const _addMessage = (role, content) => { out.added.push({ role, content }); };
    const slashReply = (text) => {
      out.replies.push(text);
      _persistMsg('assistant', text, { source: 'slash' });
    };
    const _makeCtx = () => ({ esc: (s) => s });
    const _fuzzyMatch = () => [];
    const _invokeSkillByName = async () => true;
    const _loadSkillSlashCatalog = async () => [];
    const _resolveCommand = (c) => (c in COMMANDS ? c : null);
    const _resolveSubcommand = () => null;
    const LEGACY_ALIASES = {};
    const COMMANDS = {
      'tour-settings': {
        category: 'Tours',
        help: 'Settings tour',
        // A tour: it talks back, exactly as the real handlers do.
        handler: async () => { slashReply('Here is Settings.'); __THROW__ return true; },
      },
    };

    __BODY__
    console.log(JSON.stringify(out));
"""


def _run(body: str, sid="null", pending="false", throw="") -> dict:
    script = (
        _HARNESS
        .replace("__DEPTH__", _declaration("_transcriptOnlyDepth"))
        .replace("__PERSIST__", _function("_persistMsg"))
        .replace("__HANDLE__", _function("handleSlashCommand"))
        .replace("__SID__", sid)
        .replace("__PENDING__", pending)
        .replace("__THROW__", throw)
        .replace("__BODY__", textwrap.dedent(body))
    )
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=script, capture_output=True, text=True, cwd=str(_REPO), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"node produced no stdout\n{proc.stderr}"
    return json.loads(lines[-1])


def test_a_command_the_user_typed_still_echoes_and_is_saved():
    # The default path, unchanged. If this ever goes quiet, the options did not
    # add a behaviour — they replaced one.
    out = _run("await handleSlashCommand('/tour-settings');", sid="'s1'")
    assert out["added"] == [{"role": "user", "content": "/tour-settings"}]
    roles = [p["body"]["role"] for p in out["posted"]]
    assert roles == ["user", "assistant"], "both halves of the exchange are saved"
    assert all("/api/session/s1/message" in p["url"] for p in out["posted"])


def test_an_autoplayed_command_neither_echoes_nor_is_saved():
    out = _run(
        "await handleSlashCommand('/tour-settings', { echo: false, persist: false });",
        sid="'s1'",
    )
    assert out["added"] == [], "no command the user did not type appears as their message"
    assert out["posted"] == [], "and nothing about it reaches the session"
    assert out["replies"] == ["Here is Settings."], "the tour still runs and still speaks"


def test_an_autoplayed_command_never_conjures_a_session_to_hold_itself():
    # The headline harm, and the reason a cosmetic-sounding note was worth a
    # year of the feature being off: with no current session and a pending
    # chat, persisting materialises one. Opening Settings on a fresh install
    # would have put a chat in the sidebar the user never started.
    quiet = _run(
        "await handleSlashCommand('/tour-settings', { echo: false, persist: false });",
        sid="null", pending="true",
    )
    assert quiet["materialised"] == 0
    assert quiet["posted"] == []

    # Same conditions, typed by hand: materialising is correct there — the user
    # started this exchange and it belongs somewhere.
    typed = _run("await handleSlashCommand('/tour-settings');", sid="null", pending="true")
    assert typed["materialised"] == 1


@pytest.mark.parametrize("options, expected", [("", 2), ("{ persist: false }", 0)])
def test_persist_governs_the_replies_and_not_only_the_echo(options, expected):
    # `slashReply` and `typewriterReply` persist too, and a tour is mostly
    # replies. Suppressing the echoed command alone would still have written
    # the tour's narration into the transcript.
    call = f"await handleSlashCommand('/tour-settings'{', ' + options if options else ''});"
    assert len(_run(call, sid="'s1'")["posted"]) == expected


def test_the_quiet_window_closes_even_when_the_command_throws():
    # A tour that fails mid-way must not leave the app silently refusing to
    # save anything the user does afterwards.
    out = _run(
        """
        try { await handleSlashCommand('/tour-settings', { persist: false }); } catch (_) {}
        await _persistMsg('user', 'a real message the user typed', null);
        """,
        sid="'s1'", throw="throw new Error('halo blew up');",
    )
    saved = [p["body"]["content"] for p in out["posted"]]
    assert saved == ["a real message the user typed"]


def test_the_quiet_window_closes_on_an_unknown_command_too():
    # The unknown-command path returns from *after* the try block, which is the
    # one exit a `finally` is easy to miss.
    out = _run(
        """
        await handleSlashCommand('/not-a-command', { persist: false });
        await _persistMsg('user', 'after', null);
        """,
        sid="'s1'",
    )
    assert [p["body"]["content"] for p in out["posted"]] == ["after"]
