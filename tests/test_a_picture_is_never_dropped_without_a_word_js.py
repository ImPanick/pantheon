# SPDX-License-Identifier: AGPL-3.0-or-later
"""fx5-vision — a picture the model does not get is said in the chat, never dropped.

The owner, 2026-10-08: *"It shows the attached image but the LLM literally says
'there's no image'."* Two more doors, measured on `0345288` in Chromium (8761,
a fake OpenAI-compatible server recording what it is sent):

* **`B-NEW-3`, Steer now with a picture.** A steer is words only
  (`/api/chat/steer` takes `{text}`), and `submitSteer` posted the words and
  left the picture in the composer's tray: the agent was steered to "look at
  this picture" with none, the owner's screenshot again (Agent is working, the
  thumbnail in the tray). A message with a picture now goes to the queue — which
  uploads it with the message — and the toast says why.
* **`B-NEW-2`'s other half.** A picture now goes to a model nothing has said is
  blind; a server that cannot see answers with an error (measured through the
  real route: `event: error` `{"status": 400, "text": "local endpoint returned
  HTTP 400: image input is not supported - hint: …"}` in Chat and in Agent mode),
  and the reply said *"The model didn't answer (HTTP 400)."* It now says the
  model refused the picture, with the provider's words behind Details.

Driven under node: the shipped `chatStreamErrors.js`, and the shipped
`chatStream.js` in `tests/test_chat_steer_js.py`'s sandbox.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_chat_steer_js import _run as _steer_run, sandbox  # noqa: F401  (`sandbox` is a fixture)

ROOT = Path(__file__).resolve().parents[1]
ERRORS = (ROOT / "static" / "js" / "chatStreamErrors.js").as_uri()

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The words the route sent, measured (`/tmp/scratch-fx5-vision/repro_refuse.py`):
# what `llm_core` says around a refusal from a llama-server with no projector.
LLAMA_NO_MMPROJ = ("local endpoint returned HTTP 400: image input is not supported - hint: "
                   "if this is unexpected, you may need to provide the mmproj")


def _sentence(payload, model):
    script = f"""
      import {{ createTerminalStreamError, buildReplyError }} from {json.dumps(ERRORS)};
      const el = (tag) => ({{ tag, children: [], style: {{}}, attrs: {{}}, textContent: '',
        className: '', setAttribute(k, v) {{ this.attrs[k] = v; }},
        appendChild(c) {{ this.children.push(c); return c; }}, addEventListener() {{}} }});
      const doc = {{ createElement: el }};
      const box = buildReplyError(doc, createTerminalStreamError({json.dumps(payload)}),
                                  {{ model: {json.dumps(model)} }});
      const text = box.children.find((c) => c.className === 'reply-error-text').textContent;
      const details = box.children.find((c) => c.className === 'reply-error-details');
      console.log(JSON.stringify({{ text, details: details ? details.children[1].textContent : null }}));
    """
    out = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True,
                         text=True, cwd=ROOT, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_model_that_refuses_the_picture_is_said_to_have_refused_it():
    out = _sentence({"status": 400, "text": LLAMA_NO_MMPROJ}, "local/text-only-3b")
    assert out["text"] == "text-only-3b refused the picture (HTTP 400).", out
    assert out["details"] == LLAMA_NO_MMPROJ, "the model's own words are kept behind Details"


@pytest.mark.parametrize("words", [
    "Invalid content type. image_url is only supported by certain models.",
    "Model does not support images. Please use a model that does.",
    "llava-text is not a multimodal model",
])
def test_the_other_servers_words_for_it_say_the_same(words):
    out = _sentence({"status": 400, "text": words}, "m")
    assert out["text"] == "m refused the picture (HTTP 400)."


def test_a_refusal_that_names_no_picture_keeps_the_general_sentence():
    out = _sentence({"status": 400, "text": "max_tokens is too large: 9000"}, "m")
    assert out["text"] == "The model didn't answer (HTTP 400)."


# ── Steer now, with a picture in the composer (`B-NEW-3`) ────────────────────

_STEER_WITH = """
    globalThis.__sid = 'sess-a';
    globalThis.fileHandlerModule = { getPendingCount: () => %d };
    globalThis.chatModule = { queueStreamingComposerRequest: () => { calls.queued++; return true; } };
    mockFetch(async (url, body) => res(200, (body && body.probe) ? {} : { accepted: true, pending: 1 }));
    await import('./chatStream.js');
    setBusy(true); await tick();
    composer.value = 'Steer: look at this picture.';
    pressSteerKey();
    await tick();
    console.log(JSON.stringify({
      steers: calls.fetch.filter((f) => f.body && f.body.text).map((f) => f.body.text),
      queued: calls.queued, toasts: calls.toasts, kept: composer.value }));
"""


def test_a_steer_with_a_picture_waits_in_the_queue_with_it(sandbox):  # noqa: F811
    out = _steer_run(sandbox, _STEER_WITH % 1)
    assert out["steers"] == [], (
        "the words steered the run and the picture stayed in the tray — the agent "
        "was told to look at a picture it was never sent"
    )
    assert out["queued"] == 1, "the message (and its picture) must go to the queue"
    assert any("A picture can't steer a running reply" in t for t in out["toasts"]), out["toasts"]


def test_a_steer_with_no_picture_still_steers(sandbox):  # noqa: F811
    out = _steer_run(sandbox, _STEER_WITH % 0)
    assert out["steers"] == ["Steer: look at this picture."]
    assert out["queued"] == 0
