# SPDX-License-Identifier: AGPL-3.0-or-later
"""A scripted stand-in model for the showcase: OpenAI-compatible, local, honest.

The screenshots need chats with a real agent trace in them — thinking, tool
calls, tool results, a reply — and a capture has no model and must not reach
one (`Law 16`). So this serves `/v1/models` and `/v1/chat/completions` on
loopback and **plays a script**: for each conversation below it streams the
thinking and the tool calls written here, Pantheon runs those tools for real
against the seeded demo data, and the results go back into the next request
exactly as they would to any model. The model's words are scripted; everything
Pantheon does with them is the product.

It calls itself `scripted-demo` everywhere a model name is shown, and the README
caption says the screens use demo data, so no picture passes a script off as a
model's judgement.

Standard library only — `capture.py` runs it in a thread of its own process.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

MODEL_ID = "scripted-demo"

# What it says to anything off its script. The seed refuses a chat that ever
# shows it, so a capture cannot quietly ship a picture of a broken script.
OFF_SCRIPT = "This is the scripted demo model; it only knows the showcase's script."

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TODAY = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")


def _id_near(results: List[str], name: str) -> str:
    """The id on the line of a tool result that names `name`."""
    for text in reversed(results):
        for line in text.splitlines():
            if name in line:
                m = _UUID.search(line)
                if m:
                    return m.group(0)
        # A result that is one JSON object or list: find the record by its title.
        try:
            data = json.loads(text)
        except ValueError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if any(name in str(v) for v in cur.values() if isinstance(v, str)):
                    for k in ("id", "document_id", "task_id", "uid"):
                        if isinstance(cur.get(k), str) and cur[k]:
                            return cur[k]
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
    return ""


def demo_monday(today: _dt.date) -> _dt.date:
    """The Monday of the demo week: this week's on a Monday or Tuesday, else the
    next one — so Wednesday's review is never in the past whatever day the
    capture runs. `seed.seed_calendar` places the events by the same day."""
    this = today - _dt.timedelta(days=today.weekday())
    return this if today.weekday() <= 1 else this + _dt.timedelta(days=7)


def _prep_slot(today: _dt.date) -> str:
    """Wednesday 09:00 of the demo week — the hour before the seeded launch review."""
    return _dt.datetime.combine(demo_monday(today) + _dt.timedelta(days=2), _dt.time(9, 0)).isoformat()


BRAMBLEWICK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Bramblewick Bakery — Spring menu</title>
<style>
body{margin:0;font:18px/1.5 Georgia,serif;background:#f6efe4;color:#3b2a1e}
header{background:#7a2e2a;color:#fff7ec;padding:48px 64px}
h1{margin:0;font-size:44px}main{padding:32px 64px;display:grid;grid-template-columns:1fr 1fr;gap:32px}
section{background:#fffaf2;border:1px solid #e4d5bf;border-radius:10px;padding:20px 28px}
h2{margin-top:0;color:#7a2e2a}li{margin:6px 0}.price{float:right;font-weight:bold}
footer{padding:0 64px 40px;color:#7d6450}
</style></head><body>
<header><h1>Bramblewick Bakery</h1><p>Spring menu · baked every morning from 6</p></header>
<main>
<section><h2>Breads</h2><ul>
<li>Country sourdough <span class="price">5.20</span></li>
<li>Seeded rye <span class="price">4.80</span></li>
<li>Olive fougasse <span class="price">4.50</span></li></ul></section>
<section><h2>Sweet</h2><ul>
<li>Rhubarb custard tart <span class="price">3.90</span></li>
<li>Cardamom bun <span class="price">3.20</span></li>
<li>Lemon drizzle slice <span class="price">2.90</span></li></ul></section>
</main>
<footer>Celebration cakes: order two days ahead. Open Tue–Sun, 7–3.</footer>
</body></html>
"""


# ── the conversations ────────────────────────────────────────────────────────
#
# Oldest first; the last is the hero and sits at the top of the sidebar. Each
# step is either a tool call (`call`, `args`) or the reply (`say`). `args` may
# be a function of the turn so far: `ctx["results"]` holds this turn's tool
# results, `ctx["today"]` the date Pantheon put in the context block.

CONVERSATIONS: List[Dict[str, Any]] = [
    {
        "key": "survey",
        "title": "What the survey says",
        "turns": [{
            "user": "Read survey-results.csv in my documents — what does it say about reminders? Keep it short.",
            "expect_tools": ["manage_documents"],
            "steps": [
                {"think": "The survey is a CSV in the Research folder. I'll find it, read it, "
                          "and compare the reminder row with the others.",
                 "call": "manage_documents", "args": {"action": "list", "search": "survey"}},
                {"think": "Found it. Reading the rows.",
                 "call": "manage_documents",
                 "args": lambda ctx: {"action": "read",
                                      "document_id": _id_near(ctx["results"], "survey-results")}},
                {"think": "Reminders: 41 agree, 37 disagree — the most divided row by far.",
                 "say": "**Reminders are the most divided question in the survey.**\n\n"
                        "| Question | Agree | Disagree |\n|---|---:|---:|\n"
                        "| Reminders arrive at a useful time | 41 | **37** |\n"
                        "| The timeline is easy to read | 66 | 13 |\n"
                        "| I would share a space | 58 | 17 |\n\n"
                        "That matches the interviews: five of eight people stopped because "
                        "reminders came at the wrong time. **Quiet hours** in 2.0 is the right "
                        "first answer; worth re-asking this question a month after launch."},
            ],
        }],
    },
    {
        "key": "filing",
        "title": "File the loose documents",
        "turns": [{
            "user": "Three documents are sitting in Unfiled. Put each one where it belongs.",
            "expect_tools": ["manage_documents"],
            "steps": [
                {"think": "Let me see what is unfiled and which folders exist.",
                 "call": "manage_documents", "args": {"action": "list", "unfiled": True}},
                {"think": "Meeting notes are about the Lumen launch; the agenda is Quillfeather's; "
                          "the ideas are for 2.1. Checking the folder names before moving.",
                 "call": "manage_documents", "args": {"action": "list_folders"}},
                {"think": "Three moves, each into a folder that already exists.",
                 "call": "manage_documents",
                 "args": lambda ctx: {"action": "reorganise", "steps": [
                     {"action": "move", "to": "Projects/Lumen 2.0",
                      "document_ids": [_id_near(ctx["results"], "meeting-notes-2026-09-28")]},
                     {"action": "move", "to": "Clients/Quillfeather Cycles",
                      "document_ids": [_id_near(ctx["results"], "Quillfeather kickoff agenda")]},
                     {"action": "move", "to": "Projects/Lumen 2.0/Research",
                      "document_ids": [_id_near(ctx["results"], "ideas-for-2.1")]},
                 ]}},
                {"say": "Filed all three:\n\n"
                        "- `meeting-notes-2026-09-28.md` → **Projects / Lumen 2.0**\n"
                        "- `Quillfeather kickoff agenda.md` → **Clients / Quillfeather Cycles**\n"
                        "- `ideas-for-2.1.txt` → **Projects / Lumen 2.0 / Research**\n\n"
                        "Unfiled is empty now. Nothing was renamed or deleted."},
            ],
        }],
    },
    {
        # Only when a workstation is running (`capture.py --workstation`): the
        # agent's file and shell tools run in the person's Ubuntu account there,
        # and `computer` works its screen.
        "key": "workstation",
        "needs": "workstation",
        "title": "A first page for Bramblewick",
        "turns": [{
            "user": "In my workstation, start the Bramblewick menu site with a first page, "
                    "then open it in Firefox so I can see it.",
            "allow_bash": True,
            "expect_tools": ["write_file", "bash", "computer"],
            "steps": [
                {"think": "A folder in the workstation home, one HTML page with the menu, "
                          "then open it on the desktop.",
                 "call": "write_file",
                 "args": {"path": "sites/bramblewick/index.html", "content": BRAMBLEWICK_PAGE}},
                {"call": "bash",
                 "args": {"command": "cd ~/sites/bramblewick && ls -l && wc -l index.html"}},
                {"think": "The page is written. Opening it from the terminal on the desktop.",
                 "call": "computer", "args": {"action": "click", "x": 480, "y": 320}},
                {"call": "computer",
                 "args": {"action": "type", "text": "firefox ~/sites/bramblewick/index.html &"}},
                {"call": "computer", "args": {"action": "key", "keys": "Return"}},
                {"call": "computer", "args": {"action": "wait", "ms": 15000}},
                {"call": "computer", "args": {"action": "screenshot"}},
                {"say": "The site has a first page at `~/sites/bramblewick/index.html` in your "
                        "workstation, and it is open in Firefox there — **Workstation screen** "
                        "shows it. It is plain HTML with the menu, opening hours and a pre-order "
                        "note; nothing is published anywhere."},
            ],
        }],
    },
    {
        "key": "week",
        "title": "Plan the launch week",
        "turns": [{
            "user": "Plan my launch week: check what's scheduled, read the launch checklist, "
                    "and book a 30-minute prep slot before Wednesday's review.",
            "expect_tools": ["manage_tasks", "manage_documents", "manage_calendar"],
            "steps": [
                {"think": "Three things to gather: the automations that run this week, what is "
                          "still open on the checklist, and a free slot before the review. "
                          "Starting with the automations.",
                 "call": "manage_tasks", "args": {"action": "list"}},
                {"think": "The weekly metrics chain runs Monday at 08:00 with a failure branch. "
                          "Now the checklist.",
                 "call": "manage_documents", "args": {"action": "list", "search": "launch-checklist"}},
                {"call": "manage_documents",
                 "args": lambda ctx: {"action": "read",
                                      "document_id": _id_near(ctx["results"], "launch-checklist")}},
                {"think": "Three items are open before Wednesday. Checking the calendar for a gap.",
                 "call": "manage_calendar",
                 "args": lambda ctx: {"action": "list_events",
                                      "start": demo_monday(ctx["today"]).isoformat() + "T00:00:00",
                                      "end": (demo_monday(ctx["today"]) + _dt.timedelta(days=5)).isoformat() + "T00:00:00"}},
                {"think": "Wednesday has the review at 10:00 and nothing before it, so 09:00 "
                          "is the slot — booking it.",
                 "call": "manage_calendar",
                 "args": lambda ctx: {"action": "create_event", "summary": "Launch review prep",
                                      "dtstart": _prep_slot(ctx["today"]),
                                      "dtend": (_dt.datetime.fromisoformat(_prep_slot(ctx["today"])) + _dt.timedelta(minutes=30)).isoformat(),
                                      "event_type": "work", "importance": "high"}},
                {"think": "Everything gathered. Writing it up short, bullets first.",
                 "say": "**Booked:** *Launch review prep*, Wednesday 09:00–09:30, the hour "
                        "before the review.\n\n"
                        "| Still open before Wednesday | Owner |\n|---|---|\n"
                        "| Release notes reviewed | Jun |\n"
                        "| Pricing page — annual plan toggle | You |\n"
                        "| Accessibility pass on the timeline | Priya |\n\n"
                        "**Runs on its own:** the morning briefing daily at 07:30; weekly metrics "
                        "→ report → share on Monday at 08:00, which tells you which step broke "
                        "if one fails; and the nightly notes backup."},
            ],
        }],
    },
]

# `integrate-e`. The README's *Describe it* animation: the drafter's answer to
# the first example sentence. It reads the palette it was sent for the chat
# server's `send_message` — the qualified name carries the server's id, which a
# capture only knows once the scene has registered `demo_chat.py` — as a model
# reads its prompt, and drafts the gate's workflow: mail from the bank → a
# one-line summary → a post to #bank. `needs: "drafter"`: never played as a chat.
DESCRIBE_SENTENCE = "When mail arrives from my bank, summarise it and post it to my chat server."


def _bank_draft(ctx: Dict[str, Any]) -> Dict[str, Any]:
    found = re.findall(r"mcp__[0-9A-Za-z_-]+?__send_message", ctx.get("sent") or "")
    return {
        "name": "Bank mail to chat",
        "trigger": {"type": "event", "event": "email_received"},
        "steps": [
            {"id": "from-the-bank", "kind": "if", "label": "Is it from the bank?",
             "config": {"join": "all", "conditions": [
                 {"left": "{{ steps.start.data.from_address }}", "op": "contains", "right": "bank"}]}},
            {"id": "summarise", "kind": "llm", "label": "Summarise it",
             "config": {"prompt": "Summarise this mail from my bank in one line for my chat. "
                                  "Subject: {{ steps.start.data.subject }}"}},
            {"id": "post", "kind": "mcp", "label": "Post to #bank",
             "config": {"tool": found[0] if found else "send_message",
                        "args": {"channel": "#bank", "text": "{{ steps.summarise.text }}"}}},
        ],
        "arrows": [{"from": "from-the-bank", "port": "then", "to": "summarise"},
                   {"from": "summarise", "port": "success", "to": "post"}],
        "missing": [],
    }


CONVERSATIONS.append({"key": "describe", "needs": "drafter", "plain": True, "title": "Draft",
                      "turns": [{"user": DESCRIBE_SENTENCE, "steps": [{"say": _bank_draft}]}]})


# Requests Pantheon makes on the side — a title for a new chat, memory and
# skill extraction after a turn. They are the non-streaming calls without tools
# (measured: the agent's own rounds always stream), and they are answered
# plainly so nothing is invented: the script's title, no facts, no skill.
#
# `integrate-e` (wb-canvas-e's `B-NEW-2`): the Workbench's drafter (`P22-19`)
# and *Why did this fail?* (`P22-20`) ask a model the same way — one plain,
# non-streaming request with no tools, through `workflow_assist.ask_for_json` —
# and every such request was answered "OK", so neither could be scripted and
# the drafter said "its answer was not a JSON object". A conversation marked
# `"plain": True` answers a plain request whose person's words are its turn's
# with that step's `say` (a dict is sent as JSON text; a function of the turn
# reads what it was sent first); everything else plain is a side request, as
# before. The model's words are still the script's; what Pantheon makes of
# them is the product.
_SIDE = [
    (re.compile(r"^\s*Generate a short title", re.I), None),       # the script's title
    (re.compile(r"memory extraction assistant", re.I), "[]"),
    (re.compile(r"reusable 'skill'", re.I), "NONE"),
]


def _text(content: Any) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


def _find_turn(messages: List[Dict[str, Any]], conversations: Optional[List[Dict[str, Any]]] = None):
    """The scripted turn this request belongs to, whether it is the turn's first
    request, and what it carries.

    The turn is found by the person's words, in the latest user message that
    holds them — not simply the last user message: a tool result can come back
    as a user message (a `computer` result carrying the screenshot, and every
    result on a model that is sent no tools), and a turn the person approved
    part-way through came back, until `B1069`, with the approved tool's result
    as a user message after an assistant *"Allow this task to continue?"*.
    A request with nothing after the person's words starts the turn.
    """
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") != "user":
            continue
        said = _text(messages[i].get("content"))
        for conv in (CONVERSATIONS if conversations is None else conversations):
            for turn in conv["turns"]:
                if turn["user"] not in said:
                    continue
                after = messages[i + 1:]
                results = [_text(m.get("content")) for m in after
                           if m.get("role") in ("tool", "user")]
                m = _TODAY.search(said)
                today = _dt.date.fromisoformat(m.group(1)) if m else _dt.date.today()
                sent = "\n".join(_text(m.get("content")) for m in messages)
                return conv, turn, not after, {"results": results, "today": today, "said": said,
                                               "sent": sent}
    return None, None, True, {}


class _Progress:
    """Where each scripted turn is, kept by the model the way a model keeps
    its own plan.

    Counting what a request carries was not enough, and that was measured, not
    assumed: after a card the person approved **part-way through** a turn, the
    next request carried the person's words, the card and the approved result —
    and not the tool results from the rounds before the card (`B1069`, since
    fixed: the continuation now carries the whole turn). So the script
    remembers which step it is on and every result it has been shown in this
    turn, and a step that needs an id from an earlier round still finds it.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.turns: Dict[str, Dict[str, Any]] = {}

    def advance(self, turn: Dict[str, Any], first: bool, results: List[str]):
        with self.lock:
            state = self.turns.get(turn["user"])
            if first or state is None:
                state = self.turns[turn["user"]] = {"next": 0, "results": []}
            for r in results:
                if r not in state["results"]:
                    state["results"].append(r)
            step = min(state["next"], len(turn["steps"]) - 1)
            state["next"] = step + 1
            return step, list(state["results"])


class _Handler(BaseHTTPRequestHandler):
    server_version = "scripted-demo/1"
    pace = 0.0        # seconds between streamed words; set by DemoModel
    log = None        # a list to append each request to; set by DemoModel
    progress = None   # a `_Progress`, one per DemoModel
    conversations = None  # the script; `CONVERSATIONS` unless DemoModel is given one
    max_model_len = None  # served the way vLLM serves a model (`_vllm_refusal`), when set
    model_id = MODEL_ID   # the name it lists and answers under

    def log_message(self, *args):  # quiet
        pass

    def _json(self, code: int, obj: Any) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            entry = {"id": self.model_id, "object": "model", "owned_by": "pantheon-showcase"}
            if self.max_model_len:
                entry["max_model_len"] = self.max_model_len   # vLLM's `/v1/models` says it
            return self._json(200, {"object": "list", "data": [entry]})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._json(400, {"error": {"message": "bad json"}})
        messages = body.get("messages") or []
        system = " ".join(_text(m.get("content")) for m in messages if m.get("role") == "system")
        conv, turn, first, ctx = _find_turn(messages, self.conversations)
        if self.log is not None:
            # The whole request as it arrived, beside the summary: a model that
            # records what it is sent is how `B1069` was measured and is held.
            self.log.append({"stream": bool(body.get("stream")), "tools": len(body.get("tools") or []),
                             "roles": [m.get("role") for m in messages],
                             "conv": (conv or {}).get("key"), "first": first,
                             "messages": messages,
                             "max_tokens": body.get("max_completion_tokens") or body.get("max_tokens"),
                             "temperature": body.get("temperature")})
        refused = self._vllm_refusal(body)
        if refused:
            if self.log is not None:
                self.log[-1]["refused"] = refused
            return self._json(400, {"error": {"message": refused, "type": "BadRequestError",
                                              "param": None, "code": 400}})

        side = None
        if not body.get("stream") and not body.get("tools") and (conv or {}).get("plain"):
            step_no, ctx["results"] = self.progress.advance(turn, first, ctx["results"])
            said = turn["steps"][step_no].get("say")
            # A `say` may read what it was sent (`ctx["sent"]`, every message —
            # the drafter's palette is a turn before the person's words), as a
            # model reads its prompt.
            said = said(ctx) if callable(said) else said
            text = said if isinstance(said, str) else json.dumps(said)
            if self.log is not None:
                self.log[-1]["plain"] = True
            return self._json(200, {"id": "demo-" + uuid.uuid4().hex[:8], "object": "chat.completion",
                                    "model": self.model_id,
                                    "choices": [{"index": 0, "finish_reason": "stop",
                                                 "message": {"role": "assistant", "content": text}}],
                                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        if not body.get("stream") and not body.get("tools"):
            side = "OK"
            for pattern, answer in _SIDE:
                if pattern.search(system):
                    side = answer if answer is not None else (conv or {}).get("title", "Demo chat")
                    break
        if side is not None or conv is None:
            text = side if side is not None else OFF_SCRIPT
            if body.get("stream"):
                return self._stream([{"content": text}], finish="stop")
            return self._json(200, {"id": "demo-" + uuid.uuid4().hex[:8], "object": "chat.completion",
                                    "model": self.model_id,
                                    "choices": [{"index": 0, "finish_reason": "stop",
                                                 "message": {"role": "assistant", "content": text}}],
                                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        step_no, ctx["results"] = self.progress.advance(turn, first, ctx["results"])
        step = turn["steps"][step_no]
        deltas: List[Dict[str, Any]] = []
        if step.get("think"):
            deltas += [{"reasoning_content": w} for w in _words(step["think"])]
        # A step makes one call (`call`, `args`) or several at once (`calls`, a
        # list of them) — the second is a model asking for two things in one
        # message, which is where a card can stop a round part-way.
        calls = step.get("calls") or ([{"call": step["call"], "args": step["args"]}]
                                      if "call" in step else [])
        calls = [(c["call"], c["args"](ctx) if callable(c["args"]) else c["args"]) for c in calls]
        if calls and conv.get("fenced"):
            # A conversation on an endpoint that is sent no tools: the calls are
            # written into the reply as fenced blocks, the way such a model
            # calls a tool, and Pantheon's parser finds them.
            text = "".join(f"\n\n```{name}\n{json.dumps(args)}\n```" for name, args in calls)
            deltas += [{"content": w} for w in _words((step.get("say") or "") + text)]
            return self._stream(deltas, finish="stop")
        if calls and body.get("tools"):
            deltas.append({"tool_calls": [{"index": n, "id": "call_" + uuid.uuid4().hex[:12],
                                           "type": "function",
                                           "function": {"name": name,
                                                        "arguments": json.dumps(args)}}
                                          for n, (name, args) in enumerate(calls)]})
            return self._stream(deltas, finish="tool_calls")
        deltas += [{"content": w} for w in _words(step.get("say") or "Done.")]
        return self._stream(deltas, finish="stop")

    def _vllm_refusal(self, body: Dict[str, Any]) -> Optional[str]:
        """What vLLM's OpenAI server answers a request it will not run, or None.

        `B1029`. With `max_model_len` set, this model checks a request the way
        vLLM's `OpenAIServing._validate_input` does — read from vLLM's source at
        v0.6.6, v0.8.5, v0.10.1 and v0.11.0, the same rule in all four: the
        prompt must be shorter than the window, and the prompt plus
        `max_completion_tokens or max_tokens` may not exceed it; anything else
        is a 400 `BadRequestError` before a token is generated, with this
        message (v0.10.1's words). vLLM counts the prompt with the model's own
        tokenizer over the rendered chat template, tools included; this one
        counts a token per four characters of the messages and tools as JSON —
        the rule is vLLM's, the count is an approximation of one.
        """
        if not self.max_model_len:
            return None
        window = self.max_model_len
        prompt = (len(json.dumps(body.get("messages") or [])) + len(json.dumps(body.get("tools") or []))) // 4
        if prompt >= window:
            return (f"This model's maximum context length is {window} tokens. However, your "
                    f"request has {prompt} input tokens. Please reduce the length of the input messages.")
        asked = body.get("max_completion_tokens") or body.get("max_tokens")
        if asked is not None and prompt + asked > window:
            return (f"'max_tokens' or 'max_completion_tokens' is too large: {asked}. This model's "
                    f"maximum context length is {window} tokens and your request has {prompt} "
                    f"input tokens ({asked} > {window} - {prompt}).")
        return None

    def _stream(self, deltas: List[Dict[str, Any]], finish: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        cid = "demo-" + uuid.uuid4().hex[:8]

        def send(delta, reason=None):
            chunk = {"id": cid, "object": "chat.completion.chunk", "model": self.model_id,
                     "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.flush()

        try:
            send({"role": "assistant"})
            for d in deltas:
                send(d)
                if self.pace and ("content" in d or "reasoning_content" in d):
                    time.sleep(self.pace)
            send({}, finish)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Pantheon stopped reading (a stopped turn): nothing left to send to


def _words(text: str) -> List[str]:
    """Split keeping the spaces, so the stream reassembles to the exact text.

    The space leads the word, the way a tokenizer streams it (`" are"`, not
    `"are "`): sent trailing, the chat drew *Remindersare* for a frame while a
    bold run was still open, an artefact of this script and not of a model."""
    return re.findall(r"\s*\S+|\s+$", text)


class DemoModel:
    """The scripted model on a loopback port, in a daemon thread."""

    def __init__(self, port: int = 0, pace: float = 0.0, log: Optional[list] = None,
                 conversations: Optional[List[Dict[str, Any]]] = None,
                 max_model_len: Optional[int] = None, model_id: str = MODEL_ID):
        """`conversations` replaces the showcase's script (a test plays its own
        through the same model); `log` receives every request it is sent;
        `max_model_len` serves it the way vLLM serves a model with that window
        (`_Handler._vllm_refusal`, `B1029`); `model_id` is the name it lists and
        answers under — a test that needs Pantheon to treat it as one model
        family or another (a `pantheon-qwen3` finetune, `B1090`)
        gives it that family's name. The showcase keeps `MODEL_ID`."""
        handler = type("Handler", (_Handler,), {"pace": pace, "log": log, "progress": _Progress(),
                                                "conversations": conversations,
                                                "max_model_len": max_model_len,
                                                "model_id": model_id})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def set_pace(self, seconds: float) -> None:
        self.httpd.RequestHandlerClass.pace = seconds

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
