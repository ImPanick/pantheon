# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision `B-NEW-1` — a picture attached in a new chat went nowhere.

The owner, 2026-10-08, from a phone (`/work/notes/owner-shots/bug1-image-not-seen.jpg`):
*"attaching an image to the chat, doesnt actually feed said image to the LLM …
It shows the attached image but the LLM literally says 'there's no image'."* The
screenshot: a chat of two messages, Agent mode, the model's reasoning saying the
picture is missing from the prompt — and the picture's thumbnail still sitting in
the composer while the reply streamed.

**Measured on `0345288`** (Chromium against this checkout on 8761, a fake
OpenAI-compatible `gemma-4-26b-a4b` recording every request): on the FIRST
message of a new chat the page made no upload, `/api/chat_stream` carried no
`attachments`, the model was sent no picture, the person's bubble showed none and
the thumbnail stayed in the composer — file picker, paste, drop, two pictures,
Chat and Agent, 1440 and 390. A second message in the same chat was fine.

**Why.** `B893` keyed the composer's files by chat: a new chat has no id yet, so
they are held under `''`. The send makes the chat first
(`sessions.js` `materializePendingSession`, which sets the current id) and then
reads the files (`chat.js` `handleChatSubmit`: `getPendingCount()`, then
`uploadPending`). The read swapped the working set to the new id's empty set,
the picture stayed under `''`, and `uploadPending` returned `[]` before its
`finally` — so nothing redrew the strip.

**Now** the pending chat's composer becomes the new chat's
(`fileHandler.carryPending`, called where the chat is made), and any swap of the
working set is drawn. Every case drives the real `fileHandler.js` under node and
the shipped `materializePendingSession`, cut out of `sessions.js` with the shared
extractor. None reads the source for an answer.
"""

import json
import shutil
from pathlib import Path

import pytest

from test_an_attachment_belongs_to_its_chat import _SHIM as _B893_SHIM, _STUBS  # noqa: E402
from test_tool_effect_surfaces_js import _make_sandbox, _run  # noqa: E402
from tests.helpers.js_source import js_definition

ROOT = Path(__file__).resolve().parents[1]
FILE_HANDLER = ROOT / "static" / "js" / "fileHandler.js"
SESSIONS = ROOT / "static" / "js" / "sessions.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _materialize_source() -> str:
    src = SESSIONS.read_text(encoding="utf-8")
    at = src.index("export async function materializePendingSession(")
    return js_definition(src, at).replace("export async function", "async function", 1)


# The B893 shim, plus: the strip's drawn children readable as names, and a
# picture the way the composer holds one.
_SHIM = _B893_SHIM + r"""
export function aPicture(name) {
  return { name, type: 'image/jpeg', size: 3692, slice() { return this; } };
}
export function shown() { return strip.children.length; }
"""

# What `materializePendingSession` closes over in `sessions.js`, as plain
# module state the case drives. The function itself is the shipped text.
_PREAMBLE = (
    "import { document, strip, posted, replyWith, tick, aFile, aPicture, shown }"
    " from './shim.js';\n"
    "const fh = await import('./fileHandler.js');\n"
    "fh.init('');\n"
    "globalThis.window.fileHandlerModule = fh;\n"
    "let currentSessionId = null;\n"
    "fh.setSessionResolver(() => currentSessionId);\n"
    "let _pendingMaterializePromise = null;\n"
    "let _pendingChat = null;\n"
    "let _suppressNextSessionLoading = false;\n"
    "const API_BASE = '';\n"
    "const errors = [];\n"
    "const uiModule = { showError: (m) => errors.push(m) };\n"
    "const Storage = { set() {}, remove() {} };\n"
    "globalThis.history = { replaceState() {} };\n"
    "function _markIncognito() {}\n"
    "async function loadSessions() {}\n"
    "let nextChat = { id: 'chat-new' };\n"
    "let onCreate = () => {};\n"
    "const _upload = globalThis.fetch;\n"
    "globalThis.fetch = async (url, opts) => {\n"
    "  if (String(url).endsWith('/api/session')) {\n"
    "    onCreate();\n"
    "    return { ok: true, json: async () => nextChat };\n"
    "  }\n"
    "  return _upload(url, opts);\n"
    "};\n"
    "function newChat() {\n"
    "  _pendingChat = { url: 'http://box/v1/chat/completions', modelId: 'gemma-4-26b-a4b',\n"
    "                   endpointId: 'e1', source: 'manual' };\n"
    "  currentSessionId = null;\n"
    "}\n"
    "const uploads = () => posted.filter((p) => p.url.includes('/api/upload')).length;\n"
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    return _make_sandbox(
        tmp_path_factory.mktemp("firstmessage"), FILE_HANDLER, _SHIM, _STUBS
    )


def _drive(sandbox, script):
    return _run(sandbox, _PREAMBLE + _materialize_source() + "\n", script)


# What `handleChatSubmit` does with the composer once the chat exists, in its
# order: count (`_pendingAttachInfo`), upload for the current id, and the strip.
_SEND = """
    const pending = fh.getPendingCount();
    const ids = await fh.uploadPending({ sessionId: currentSessionId });
    await tick(); await tick();
"""


def test_the_picture_on_a_new_chats_first_message_is_uploaded_with_it(sandbox):
    """The owner's report: a new chat, a picture, the first message."""
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg')]);
        const before = shown();
        replyWith({ files: [{ id: 'u-cat', name: 'cat.jpg' }], rejected: [] });
        const made = await materializePendingSession();
    """ + _SEND + """
        console.log(JSON.stringify({ before, made, sid: currentSessionId, pending, ids,
                                     uploads: uploads(), after: shown() }));
    """)
    assert out["made"] is True and out["sid"] == "chat-new"
    assert out["before"] == 1, "the picture never reached the composer"
    assert out["pending"] == 1, (
        "making the chat lost the picture: the send counted nothing to attach — "
        "this is the message the model answered with 'there is no image'"
    )
    assert out["uploads"] == 1 and out["ids"] == ["u-cat"], (
        "the picture was never uploaded, so the message carried no attachment"
    )
    assert out["after"] == 0, "the composer kept a thumbnail the send had taken"


def test_two_pictures_go_with_it_in_the_order_attached(sandbox):
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg'), aPicture('square.png')]);
        replyWith({ files: [{ id: 'u1', name: 'cat.jpg' }, { id: 'u2', name: 'square.png' }],
                    rejected: [] });
        await materializePendingSession();
    """ + _SEND + """
        console.log(JSON.stringify({ pending, ids }));
    """)
    assert out == {"pending": 2, "ids": ["u1", "u2"]}


def test_the_carried_picture_does_not_come_back_in_the_next_new_chat(sandbox):
    """It moved; it was not copied. Measured on the base: the picture the first
    message lost was still held under the no-chat key, so the NEXT new chat
    opened with it in the composer."""
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg')]);
        replyWith({ files: [{ id: 'u-cat', name: 'cat.jpg' }], rejected: [] });
        await materializePendingSession();
    """ + _SEND + """
        newChat();
        const inNext = fh.getPendingCount();
        await tick(); await tick();
        console.log(JSON.stringify({ inNext, shownInNext: shown() }));
    """)
    assert out == {"inNext": 0, "shownInNext": 0}


def test_a_chat_that_was_not_made_keeps_its_composer(sandbox):
    """`materializePendingSession` gives up when the person opened another chat
    while this one was being made; nothing moves then, and the picture is still
    the new chat's when the person comes back to one."""
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg')]);
        onCreate = () => { _pendingChat = null; };
        const made = await materializePendingSession();
        const keptUnder = fh.getAttachmentSessionKey();
        const kept = fh.getPendingCount();
        console.log(JSON.stringify({ made, keptUnder, kept }));
    """)
    assert out == {"made": False, "keptUnder": "", "kept": 1}


# ── the strip shows the working set, whoever swapped it ─────────────────────

def test_a_swap_a_getter_noticed_is_drawn(sandbox):
    """The other half of the photograph: the thumbnail on screen after the send.

    A swap only a getter noticed left the strip drawing the set just stashed.
    Measured on the base in Chromium: a picture left in one chat's composer, then
    New chat — the strip still showed it over an empty working set, and the
    first message went without it."""
    out = _drive(sandbox, """
        currentSessionId = 'chat-a';
        await fh.addFiles([aPicture('cat.jpg')]);
        const inA = shown();
        currentSessionId = null;
        const pendingInNew = fh.getPendingCount();
        await tick(); await tick();
        console.log(JSON.stringify({ inA, pendingInNew, shownInNew: shown() }));
    """)
    assert out["inA"] == 1
    assert out["pendingInNew"] == 0, "B893's binding moved: a chat's file followed you out"
    assert out["shownInNew"] == 0, (
        "the strip kept drawing the last chat's picture over an empty composer"
    )


# ── and a carry never merges two chats' files (`B893`) ──────────────────────

def test_a_carry_into_a_chat_with_its_own_files_is_refused(sandbox):
    out = _drive(sandbox, """
        currentSessionId = 'chat-b';
        await fh.addFiles([aFile('b.txt')]);
        currentSessionId = null;
        await fh.addFiles([aPicture('cat.jpg')]);
        const moved = fh.carryPending('', 'chat-b');
        const stillNew = fh.getPendingInfo().map((f) => f.name);
        currentSessionId = 'chat-b';
        const inB = fh.getPendingInfo().map((f) => f.name);
        console.log(JSON.stringify({ moved, stillNew, inB }));
    """)
    assert out == {"moved": False, "stillNew": ["cat.jpg"], "inB": ["b.txt"]}


def test_a_carry_of_a_stashed_set_lands_in_the_chat_on_screen(sandbox):
    """The order the two can happen in: the current id already moved and a
    getter already swapped to its empty set — and drew it — before the carry
    ran. The carry draws what it brought, and leaves nothing behind."""
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg')]);
        currentSessionId = 'chat-new';
        const before = fh.getPendingCount();
        await tick(); await tick();
        const shownBefore = shown();
        const moved = fh.carryPending('', 'chat-new');
        const after = fh.getPendingInfo().map((f) => f.name);
        await tick(); await tick();
        const shownAfter = shown();
        newChat();
        const inNext = fh.getPendingCount();
        console.log(JSON.stringify({ before, shownBefore, moved, after, shownAfter, inNext }));
    """)
    assert out == {"before": 0, "shownBefore": 0, "moved": True, "after": ["cat.jpg"],
                   "shownAfter": 1, "inNext": 0}


def test_a_picture_kept_while_looking_at_another_chat_goes_and_does_not_come_back(sandbox):
    """Attach in a new chat, glance at another chat, come back, send: the set
    left the no-chat key once and came back, and the carry must not leave that
    copy behind for the next new chat."""
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg')]);
        currentSessionId = 'chat-a';
        const inA = fh.getPendingCount();
        currentSessionId = null;
        const back = fh.getPendingCount();
        replyWith({ files: [{ id: 'u-cat', name: 'cat.jpg' }], rejected: [] });
        await materializePendingSession();
    """ + _SEND + """
        newChat();
        const inNext = fh.getPendingCount();
        console.log(JSON.stringify({ inA, back, ids, inNext }));
    """)
    assert out == {"inA": 0, "back": 1, "ids": ["u-cat"], "inNext": 0}


def test_no_chat_is_the_same_key_however_it_is_written(sandbox):
    """`getCurrentSessionId()` answers `null` for a chat not made yet; the
    composer's key for it is `''`. A caller passing either moves the set."""
    out = _drive(sandbox, """
        newChat();
        await fh.addFiles([aPicture('cat.jpg')]);
        currentSessionId = 'chat-new';
        const moved = fh.carryPending(null, 'chat-new');
        console.log(JSON.stringify({ moved, pending: fh.getPendingCount() }));
    """)
    assert out == {"moved": True, "pending": 1}
