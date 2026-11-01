# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1736`. Emoji reactions between the person and the model, both ways.

The model reacts with a marker any model can write (`[react:❤️]`), which never
reaches the screen or the saved reply; the person's reactions reach the model
as one short note. These run the real module, not its source text."""

import json
import re
from pathlib import Path

from src import message_reactions as mr

ROOT = Path(__file__).resolve().parent.parent


def _deltas(chunks):
    f = mr.ReactionStreamFilter()
    out = []
    for c in chunks:
        out += f.feed("data: " + json.dumps({"delta": c}) + "\n\n")
    out += f.feed("data: [DONE]\n\n")
    return out, f


def _text(frames):
    shown = []
    for fr in frames:
        if fr.startswith("data: {"):
            d = json.loads(fr[6:])
            if "delta" in d:
                shown.append(d["delta"])
    return "".join(shown)


def test_the_marker_comes_out_of_the_saved_reply():
    assert mr.take_reaction("[react:❤️] Great brief.") == ("Great brief.", "❤️")
    assert mr.take_reaction("[react: heart]\nOn it.") == ("On it.", "❤️")
    assert mr.take_reaction("[Reaction: thumbs_up] ok") == ("ok", "👍")


def test_ordinary_brackets_are_left_alone():
    for text in ("an array a[i] stays", "see [1] and [docs](https://x)", "[reactor core]"):
        assert mr.take_reaction(text) == (text, None)


def test_a_reaction_outside_the_models_palette_is_dropped_but_still_hidden():
    assert mr.take_reaction("[react:👎] hm") == ("hm", None)
    assert mr.take_reaction("[react:🤡] hi") == ("hi", None)


def test_a_marker_split_over_deltas_never_reaches_the_screen():
    frames, f = _deltas(["[re", "act:", " laugh]", " Ha,", " there [i] ok"])
    assert f.emoji == "😂"
    assert _text(frames) == "Ha, there [i] ok"
    events = [json.loads(fr[6:]) for fr in frames if '"type": "reaction"' in fr]
    assert events == [{"type": "reaction", "role": "assistant", "emoji": "😂"}]
    assert frames[-1] == "data: [DONE]\n\n"


def test_held_text_is_flushed_before_any_other_event():
    frames, _ = _deltas(["see [rea"])
    assert _text(frames) == "see [rea"
    assert frames.index("data: [DONE]\n\n") == len(frames) - 1


def test_thinking_deltas_pass_untouched():
    f = mr.ReactionStreamFilter()
    chunk = "data: " + json.dumps({"delta": "[react:👍]", "thinking": True}) + "\n\n"
    assert f.feed(chunk) == [chunk]


def test_the_model_is_told_once_in_the_system_prompt_and_hears_the_persons_reactions():
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello there, how can I help",
         "metadata": {"reactions": {"user": "👎"}}},
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "B", "metadata": {"reactions": {"user": "❤️"}}},
        {"role": "user", "content": "next"},
    ]
    out = mr.with_reactions(msgs)
    assert out[1] == {"role": "system", "content": mr.INSTRUCTION}
    assert out[-1]["content"] == "next"
    note = out[-2]["content"]
    assert "❤️ (loved it) on your last reply" in note
    assert '👎 (it missed) on your reply that began "Hello there, how can I help"' in note
    assert msgs[1]["content"] == "hi" and len(msgs) == 6, "the transcript was changed"


def test_no_note_when_nobody_reacted_and_the_note_is_bounded():
    plain = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
             {"role": "user", "content": "c"}]
    assert mr.reaction_note(plain) is None
    many = []
    for i in range(10):
        many += [{"role": "user", "content": str(i)},
                 {"role": "assistant", "content": f"reply {i}",
                  "metadata": {"reactions": {"user": "👍"}}}]
    assert mr.reaction_note(many).count("👍") == mr.NOTE_LIMIT


def test_the_instruction_is_small():
    # A 6K local window is a real case (`B1731`): the line must stay short.
    assert len(mr.INSTRUCTION) < 420


def test_the_switch_is_on_unless_turned_off_and_off_in_compare():
    assert mr.wanted({}) is True
    assert mr.wanted({"reactions_enabled": False}) is False
    assert mr.wanted({}, compare_mode=True) is False


def test_the_model_reaction_lands_on_the_persons_latest_message():
    from core.models import ChatMessage

    class S:
        history = [ChatMessage("user", "one", {"_db_id": None}),
                   ChatMessage("assistant", "r", {}),
                   ChatMessage("user", "two", {})]

    mr.react_to_latest_person_message(S, "sid", "❤️")
    assert S.history[2].metadata == {"reactions": {"assistant": "❤️"}}
    assert "reactions" not in S.history[0].metadata


def test_the_browser_palettes_match_the_servers():
    js = (ROOT / "static" / "js" / "reactions.js").read_text(encoding="utf-8")

    def arr(name):
        m = re.search(rf"export const {name} = \[([^\]]*)\]", js)
        return tuple(re.findall(r"'([^']+)'", m.group(1)))

    assert arr("USER_REACTIONS") == mr.USER_REACTIONS
    assert arr("MODEL_REACTIONS") == mr.MODEL_REACTIONS


def test_the_route_and_stream_are_wired():
    routes = (ROOT / "routes" / "history" / "history_routes.py").read_text(encoding="utf-8")
    assert '"/api/session/{session_id}/react"' in routes
    chat = (ROOT / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    assert "ReactionStreamFilter()" in chat and "offer_reactions=" in chat
    js = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")
    assert "json.type === 'reaction'" in js
