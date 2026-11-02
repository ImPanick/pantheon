# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1253` (fx2-doors) — the first slash command on a page draws no steer bar.

`handleChatSubmit` raises the busy edge before it knows the message is a slash
command. The steer control's listener (`initSteerControl`) awaits
`probeSteerSupport()` the first time on a page; `/help` finishes and drops the
busy edge inside that wait, and the listener then drew *Working… Steer now*
over an idle Agent chat — still there 14 s later, until the next command took
it down. Now the listener asks the run's own flag again after the wait.

2026-11-01: the bar is gone (the queue's row offers *Steer now* instead), and
the same listener now decides whether a steer is OFFERED (`isSteerOffered`).
The defect would read the same — an offer standing over an idle chat — so the
cases pin the offer where they pinned the node. The file keeps its name, which
the tracker's `B1253` row cites.

Driven under node: the REAL `chatStream.js`, in `test_chat_steer_js.py`'s
sandbox, with the probe held open while the busy edge rises and falls.
"""

import shutil

import pytest

from test_chat_steer_js import CHAT_STREAM, _SHIM, _STUBS, _run  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    d = tmp_path_factory.mktemp("slashsteer")
    (d / "shim.js").write_text(_SHIM)
    for name, src in _STUBS.items():
        (d / name).write_text(src)
    shutil.copy(CHAT_STREAM, d / "chatStream.js")
    return d


_HELD_PROBE = """
    globalThis.__sid = 'sess-a';
    let answer;
    const held = new Promise((r) => { answer = r; });
    mockFetch(async () => { await held; return res(409, { reason: 'no_active_run' }); });
    const mod = await import('./chatStream.js');
"""


def test_a_turn_that_ends_inside_the_first_probe_offers_no_steer(sandbox):
    out = _run(sandbox, _HELD_PROBE + """
        setBusy(true);          // `/help` + Enter: the busy edge, before it is known to be a command
        await tick();
        setBusy(false);         // the command answered; the probe has not
        answer();
        await tick(8);
        const idle = mod.isSteerOffered();
        setBusy(true);          // a real agent turn, the probe answered now
        await tick();
        console.log(JSON.stringify({ idle, during: mod.isSteerOffered(),
                                     probes: calls.fetch.length }));
    """)
    assert out["idle"] is False, "a steer was offered over an idle chat"
    assert out["during"] is True, "a real turn must still offer one"
    assert out["probes"] == 1


def test_a_turn_still_going_when_the_first_probe_answers_offers_the_steer(sandbox):
    out = _run(sandbox, _HELD_PROBE + """
        setBusy(true);
        await tick();
        answer();
        await tick(8);
        console.log(JSON.stringify({ offered: mod.isSteerOffered() }));
    """)
    assert out["offered"] is True
