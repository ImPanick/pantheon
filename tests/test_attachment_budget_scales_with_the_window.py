# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-08` — the attachments' shared allowance scales with the model's window.

`D-2026-08-26-06`: *"Scale the budget off the model's context window, falling
back to today's 24,000 when the window cannot be proven. Keep
first-come-first-served … per-role ceiling under `P12-04` … must use
`budget_context_for_model(…, fallback=0)`."*

**Measured on `a16e7d75`, through the real `ChatHandler.preprocess_message`:**
ten text files of 15,000 characters each, sent to a model with a proven 128K
window, reached it as 24,000 characters in all — the first whole, the second
cut to 8,932, eight left out — while its 111,411-token input budget had room
for all of them. On a model with a proven 8K window the
same allowance was 7,204 tokens against a 6,963-token input budget, so the
agent loop's `trim_for_context` made room by dropping the memory message, with
no marker.

Now the allowance is half of the input token budget the turn's model's proven
window gives (`context_budget.resolve_attachment_total`); an unproven window
keeps the ceiling as `P12-04` resolves it; a number a role or the instance set
stays a ceiling. The truncation markers and each attachment's `reach_note` name
the allowance that applied, and the composer's meter draws the same number.

Driven (`Law 20`): the real `preprocess_message` over the real
`build_user_content`, the real `trim_for_context` at the real
`agent_input_budget`, and the real `GET /api/upload/context-budget` on a real
SQLite chat row. The one stand-in is `budget_context_for_model` — proving a
window asks a live endpoint.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

WINDOWS = {("http://lab:8000/v1", "big-128k"): 131072,
           ("http://lab:8000/v1", "small-8k"): 8192}


@pytest.fixture()
def windows(monkeypatch):
    """`budget_context_for_model` answering the proven windows above, 0 for
    anything else, and keeping what it was asked."""
    import src.model_context as mc
    asked = []

    def proven(url, model, *, fallback=0):
        asked.append((url, model, fallback))
        return WINDOWS.get((url, model), 0)

    monkeypatch.setattr(mc, "budget_context_for_model", proven)
    return asked


@pytest.fixture()
def send(tmp_path, monkeypatch, windows):
    """`send(model, n, size)` → (the text the model is handed, attachment meta)."""
    from src.chat_handler import ChatHandler
    from src.upload_handler import UploadHandler
    import src.chat_handler as ch
    import src.settings as S

    sp = tmp_path / "settings.json"
    sp.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "SETTINGS_FILE", str(sp))
    S._invalidate_caches()
    monkeypatch.setattr(ch, "UPLOAD_DIR", str(tmp_path / "uploads"))

    class _Uploads(UploadHandler):
        def __init__(self, files):
            super().__init__(str(tmp_path), str(tmp_path / "uploads"))
            self.files = files

        def resolve_upload(self, att_id, owner=None):
            return dict(self.files[att_id]) if att_id in self.files else None

        def _inside_upload_dir(self, path):
            return True

    def _send(model, n=10, size=15_000):
        infos = {}
        for i in range(n):
            p = tmp_path / f"part{i}.txt"
            p.write_text(f"FILE{i}:" + chr(65 + i) * (size - 7), encoding="utf-8")
            infos[f"a{i}"] = {"id": f"a{i}", "name": f"part{i}.txt", "path": str(p),
                              "mime": "text/plain", "size": size}
        handler = ChatHandler(session_manager=None, memory_manager=None, chat_processor=None,
                              research_handler=None, preset_manager=None, upload_handler=_Uploads(infos))
        sess = SimpleNamespace(model=model, endpoint_url="http://lab:8000/v1", owner="", id=None)
        _e, content, _t, _y, meta = asyncio.run(handler.preprocess_message(
            "Read these.", list(infos), sess, auto_opened_docs=[], allow_tool_preprocessing=True))
        S._invalidate_caches()
        text = "".join(p.get("text", "") for p in content) if isinstance(content, list) else content
        return text, {m["name"]: m for m in meta}

    return _send


def _cut(text):
    return [line for line in text.split("\n") if line.startswith("[Attachment ")]


def test_a_proven_128k_window_reads_all_ten_files_whole(send, windows):
    text, meta = send("big-128k")
    assert windows == [("http://lab:8000/v1", "big-128k", 0)], "the turn's own pair, fallback=0"
    assert _cut(text) == [], "nothing was cut or left out"
    for i in range(10):
        assert chr(65 + i) * (15_000 - 7) in text, f"part{i}.txt reached the model whole"
    assert not any(m.get("reach_note") for m in meta.values())


def test_an_unproven_window_keeps_the_24000_it_always_had(send):
    text, meta = send("unknown-model")
    cut = _cut(text)
    assert cut[0].startswith("[Attachment content truncated: part1.txt. Only ")
    assert "the 24,000-character shared inline attachment budget" in cut[0]
    assert len(cut) == 9, "first come, first served: part0 whole, part1 cut, eight left out"
    assert meta["part9.txt"]["reach_note"] == (
        "Not sent: earlier attachments filled this message's room for files (24,000 characters).")


def test_a_small_proven_window_is_given_less_and_the_reply_says_which(send):
    from src.context_budget import resolve_attachment_total
    allowance = resolve_attachment_total(window_tokens=8192).value
    assert allowance < 24_000, allowance
    text, meta = send("small-8k", n=3, size=6_000)
    cut = _cut(text)
    assert cut and f"the {allowance:,}-character shared inline attachment budget" in cut[0]
    assert meta["part2.txt"]["reach"] in ("omitted", "cut"), meta["part2.txt"]
    assert "part0.txt" not in " ".join(cut), "the first file was read whole"


def test_on_a_small_window_the_attachments_no_longer_push_the_memory_out(send):
    """The trade the row was written about, through the agent loop's own
    trimmer at its own budget: what the attachments may take leaves room for
    the rest of the turn, so the memory message is not the thing cut."""
    from src.context_budget import agent_input_budget
    from src.context_compactor import trim_for_context
    from src.settings import get_setting
    text, _ = send("small-8k", n=10, size=6_000)
    memory = {"role": "system", "content": "Saved memory: the person's dog is called Rex."}
    messages = [{"role": "system", "content": "You are a helpful assistant."}, memory,
                {"role": "user", "content": text}]
    budget = agent_input_budget(8192, get_setting)
    kept = trim_for_context(messages, budget, reserve_tokens=1024)
    assert memory in kept, "the memory message was dropped to make room for attachments"
    assert kept[-1]["content"] == text, "and the message itself went whole"


def test_a_ceiling_somebody_set_stays_a_ceiling(monkeypatch):
    import src.settings as S
    from src.context_budget import resolve_attachment_total
    real = S.get_setting
    monkeypatch.setattr(S, "setting_is_explicit",
                        lambda key, **kw: key == "context_attachment_total_chars")
    monkeypatch.setattr(S, "get_setting", lambda key, default=None: 40_000
                        if key == "context_attachment_total_chars" else real(key, default))
    big = resolve_attachment_total(window_tokens=131072)
    assert (big.value, big.source) == (40_000, "setting"), "the window may not go past it"
    small = resolve_attachment_total(window_tokens=8192)
    assert small.source == "window" and small.clamped is True and small.value < 40_000
    unknown = resolve_attachment_total(window_tokens=0)
    assert (unknown.value, unknown.source) == (40_000, "setting")


# ── the composer's meter draws the same number ──────────────────────────────

@pytest.fixture()
def chats(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import core.database as cdb
    import routes.upload_routes as up
    engine = create_engine(f"sqlite:///{tmp_path / 'chats.db'}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine, tables=[cdb.Session.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(up, "SessionLocal", factory)
    db = factory()
    for sid, owner, model in [("c-big", "bob", "big-128k"), ("c-eve", "eve", "big-128k"),
                              ("c-unknown", "bob", "unknown-model")]:
        db.add(cdb.Session(id=sid, name=sid, endpoint_url="http://lab:8000/v1", model=model, owner=owner))
    db.commit()
    db.close()


def _meter(tmp_path, session):
    from tests.test_context_meter_js import _Handler, _endpoint, _request, _upload
    handler = _Handler({"a": _upload(tmp_path, "a.txt", "A" * 5000)}, str(tmp_path))
    out = asyncio.run(_endpoint(handler)(_request("bob"), ids="a", session=session))
    return next(b for b in out["budgets"] if b["is_ceiling"]), \
        next(s for s in out["segments"] if s["key"] == "attachments")


def test_the_meter_for_a_chat_on_a_big_model_draws_the_scaled_allowance(chats, windows, tmp_path):
    from src.context_budget import resolve_attachment_total
    ceiling, spent = _meter(tmp_path, "c-big")
    assert ceiling["source"] == "window"
    assert ceiling["chars"] == spent["budget_chars"] == resolve_attachment_total(window_tokens=131072).value


@pytest.mark.parametrize("session", ["c-unknown", "c-eve", "nope", ""])
def test_the_meter_keeps_the_ceiling_where_no_window_of_yours_is_proven(chats, windows, tmp_path, session):
    """An unproven window, somebody else's chat, a chat that is not there, and
    no chat at all all draw the ceiling as `P12-04` resolves it — another
    person's chat id tells you nothing about their model."""
    ceiling, _ = _meter(tmp_path, session)
    assert (ceiling["chars"], ceiling["source"]) == (24_000, "default")
    if session == "c-eve":
        assert windows == [], "another person's chat was not even asked about"
