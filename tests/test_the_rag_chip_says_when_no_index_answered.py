# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1287` — the RAG chip on, with the document index off, said nothing.

Measured by fx5-vision: with no embedding model the index is off —
`/api/personal/upload` answers 503 *"RAG is off: the embedding model is not
downloaded — Settings › System › Download models from the internet."* — and a
turn with the chip on carried no `rag_sources` and no word that retrieval had
not happened. The RAG window said it (`rag.js`), the chat did not.

Now the turn says it: `ChatProcessor.build_context_preface` keeps why on
`_last_rag_off` (the RAG window's own sentence, read without starting an init
attempt), `build_chat_context` carries it as `ctx.rag_off`, the chat route's
`rag_frames` sends one `rag_sources` frame with no sources and `off`, and the
browser (`static/js/ragNotice.js`, from the stream's `rag_sources` arm) puts it
on the chip and says it once in a toast.

Driven (`Law 20`): the real `ChatProcessor` with the index's state set the way
an install with no embedding model has it, the real `rag_frames`, and under
node the real `ragNotice.js` and the `rag_sources` arm cut from `chat.js`'s
live handler.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
NO_MODEL = ("RAG is off: the embedding model is not downloaded — "
            "Settings › System › Download models from the internet.")


class _Docs:
    def __init__(self, rag_manager=None):
        self.rag_manager = rag_manager


class _Rag:
    def search(self, message, k=5, owner=None):
        return []


@pytest.fixture
def no_embedding_model(monkeypatch):
    """The index as an install with no embedding model has it: no instance,
    no model on disk, no fetch allowed, no embedding server named."""
    import src.embedding_lanes as lanes
    import src.rag_singleton as rag_singleton

    monkeypatch.setattr(rag_singleton, "rag_instance", None)
    monkeypatch.setattr(lanes, "fastembed_model_is_cached", lambda: False)
    monkeypatch.setattr(lanes, "model_download_allowed", lambda: False)
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    started = []
    monkeypatch.setattr(rag_singleton, "get_rag_manager",
                        lambda: started.append("init") or None)
    return started


def _turn(docs, use_rag=True):
    from src.chat_processor import ChatProcessor

    memory = SimpleNamespace(load=lambda owner=None: [], increment_uses=lambda ids: None)
    processor = ChatProcessor(memory_manager=memory, personal_docs_manager=docs)
    _, sources, _ = processor.build_context_preface(
        message="what did the lease say about pets?", session=SimpleNamespace(),
        use_rag=use_rag, use_memory=False)
    return processor, sources


def test_a_turn_with_the_chip_on_and_no_index_keeps_why(no_embedding_model):
    processor, sources = _turn(_Docs(None))
    assert sources == []
    assert processor._last_rag_off == NO_MODEL
    assert no_embedding_model == [], "a turn started an index init attempt"


def test_the_route_sends_the_sentence_in_one_rag_sources_frame(no_embedding_model):
    """What the chat route streams for that turn (`rag_frames`, called where
    the frame used to be built inline)."""
    from routes.chat_routes import rag_frames

    processor, sources = _turn(_Docs(None))
    ctx = SimpleNamespace(rag_sources=sources, rag_off=processor._last_rag_off)
    frames = rag_frames(ctx)
    assert len(frames) == 1
    sent = json.loads(frames[0].removeprefix("data: ").strip())
    assert sent == {"type": "rag_sources", "data": [], "off": NO_MODEL}


def test_the_chip_off_says_nothing(no_embedding_model):
    from routes.chat_routes import rag_frames

    processor, sources = _turn(_Docs(None), use_rag=False)
    assert processor._last_rag_off == ""
    assert rag_frames(SimpleNamespace(rag_sources=sources, rag_off="")) == []


def test_an_index_that_searched_and_found_nothing_says_nothing(no_embedding_model):
    """Below the threshold is not "off": no frame, as before."""
    from routes.chat_routes import rag_frames

    processor, sources = _turn(_Docs(_Rag()))
    assert processor._last_rag_off == ""
    assert rag_frames(SimpleNamespace(rag_sources=sources, rag_off="")) == []


def test_an_index_up_now_is_searched_not_reported_off(no_embedding_model, monkeypatch):
    """`B1532` changed this. It pinned "the chat holds the manager built at
    start; an index that came up since is said, not searched". The real
    `PersonalDocsManager` reads the index as it stands now, so a turn searches
    an index that came up after start and says nothing is off.
    `tests/test_an_index_that_came_up_later_is_searched_by_the_chat.py` drives
    it from the index coming up."""
    import src.rag_singleton as rag_singleton
    from src.personal_docs import PersonalDocsManager

    docs = PersonalDocsManager.__new__(PersonalDocsManager)
    docs.rag_manager = None                      # as `app.py` built it, index down
    monkeypatch.setattr(rag_singleton, "rag_instance", _Rag())
    processor, _ = _turn(docs)
    assert processor._last_rag_off == ""


def test_the_context_carries_it_to_the_route():
    from routes.chat_helpers import ChatContext

    assert ChatContext.__dataclass_fields__["rag_off"].default == ""


# ── the browser ──────────────────────────────────────────────────────────────

_FAKE_DOM = r"""
class Chip {
  constructor() { this.title = 'RAG'; this.attrs = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
}
export const chip = new Chip();
export const document = { getElementById: (id) => (id === 'rag-indicator-btn' ? chip : null) };
export const toasts = [];
export const uiModule = { showToast: (m) => toasts.push(m) };
"""


def _node(tmp_path: Path, script: str) -> dict:
    (tmp_path / "ragNotice.js").write_text((ROOT / "static/js/ragNotice.js").read_text())
    # `B492`: `ragNotice.js` takes its throttle words from `runStatus.js`
    # (which imports nothing), so it is copied beside it.
    (tmp_path / "runStatus.js").write_text((ROOT / "static/js/runStatus.js").read_text())
    (tmp_path / "dom.mjs").write_text(_FAKE_DOM)
    (tmp_path / "case.mjs").write_text(textwrap.dedent(script))
    done = subprocess.run(["node", str(tmp_path / "case.mjs")], cwd=tmp_path,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def _rag_arm() -> str:
    """The `rag_sources` arm of `handleChatSubmit`'s live dispatcher, as shipped."""
    src = (ROOT / "static/js/chat.js").read_text(encoding="utf-8")
    start = src.index("export async function handleChatSubmit(")
    opening = "} else if (json.type === 'rag_sources') {"
    at = src.index(opening, start)
    end = src.index("} else if (json.type ===", at + len(opening))
    return src[at + len(opening):end]


@pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")
def test_the_stream_puts_it_on_the_chip_and_says_it_once(tmp_path):
    arm = _rag_arm()
    out = _node(tmp_path, f"""
        import {{ chip, document, toasts, uiModule }} from './dom.mjs';
        import {{ noteRagFrame }} from './ragNotice.js';
        const holder = {{}};
        const _isBg = false;
        function arm(json) {{
          for (;;) {{
            {arm}
            break;
          }}
        }}
        const off = {json.dumps(NO_MODEL)};
        arm({{ type: 'rag_sources', data: [], off }});
        const first = {{ title: chip.title, label: chip.attrs['aria-label'], sources: holder._ragSources }};
        arm({{ type: 'rag_sources', data: [], off }});          // the next turn
        const afterTwo = toasts.length;
        arm({{ type: 'rag_sources', data: [{{ filename: 'lease.pdf' }}] }});   // it came back
        const cleared = {{ title: chip.title, label: chip.attrs['aria-label'] || null }};
        arm({{ type: 'rag_sources', data: [], off }});          // and went again: news
        console.log(JSON.stringify({{ first, afterTwo, cleared, toasts }}));
    """)
    assert out["first"]["title"] == f"RAG — {NO_MODEL}"
    assert out["first"]["label"] == f"RAG is on, but did not search: {NO_MODEL}"
    assert out["first"]["sources"] == []
    assert out["afterTwo"] == 1, "said on every turn, not once"
    assert out["cleared"] == {"title": "RAG", "label": None}
    assert out["toasts"] == [NO_MODEL, NO_MODEL]
