# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-16` · An agent's evaluation set, and the harness that runs it.

The plan (`D-2026-10-22-01`, § 8): an agent is listed as fit for a model only
when it has been measured doing its job on that model. Each agent may ship
`evals.json` beside its `AGENT.md` — 1 to 10 cases, each a small **world**,
the **inputs** a hirer would give, and the **checks** on top of the manifest's
own `delivers`:

    {"cases": [{
      "id": "vip-mail-is-urgent",
      "inputs": {"vip": ["ana@example.com"]},
      "world": {
        "emails":  [{"id": "m1", "from": "ana@example.com", "subject": "...", "body": "...", "date": "..."}],
        "web":     {"https://example.org/x": "page text"},
        "search":  {"solar": [{"title": "...", "url": "...", "snippet": "..."}]},
        "shell":   [{"match": "df -P", "output": "...", "exit_code": 0}],
        "documents": [{"title": "...", "content": "..."}],
        "research": [{"id": "r1", "query": "...", "summary": "...", "sources": [{"title": "...", "url": "..."}]}],
        "memories": [{"text": "Ana started pottery in May", "category": "fact"}],
        "chats": [{"title": "Trip to Lisbon", "messages": [{"role": "user", "content": "..."}]}],
        "screens": [{"screen": "Shop home — a [Basket] button at (1180, 40)"},
                    {"after": "click at (1180, 40)", "screen": "Basket — 1 item, £12.00"}],
        "models":  {"qwen3-8b": [{"match": "bakery", "reply": "..."}], "llama-3.1-8b": "..."}
      },
      "answers": ["deny"],
      "notebook": "- sorted: m0",
      "script": [ {"call": [["list_emails", {"unread_only": true}]]}, {"say": "..."} ],
      "checks": [ {"document": {"title": "Inbox triage", "contains": ["Urgent", "Ana"]}},
                  {"not_called": "send_email"} ]
    }]}

**One harness, two models.** `run_case` drives the real scheduler —
`_execute_task`, the hire's run plan, the real agent loop, the real effects
gate, parking, the contract check and the report — inside an isolated world:
a fresh SQLite file and data folder, so nothing touches the install's own.
What the agent reads from *outside* (mail, the web, a shell on another
machine) is answered from the case's world and every call is recorded;
Pantheon's own stores (documents, notes, calendar, tasks, files) are the real
ones, in the throwaway folder. The model is either the case's `script` — CI,
every commit, no model at all — or a real endpoint (`proof runs`, `P24-18`),
run with `python -m src.agents.evals`.

A case never reaches the internet, a mailbox or a host: a tool the world does
not answer and Pantheon does not own is refused in the world's words. A
world's `research` is finished deep-research reports in its own research
folder; with the key present (even empty) the world also starts research when
asked, and without it `trigger_research` is refused like any other tool that
would leave the install (`P24-27`). A case's `notebook` is what the hire's last
run carried forward, so "new since last time" can be measured; its `trigger`
is the webhook payload or app event that started the run.

`B1602`. A world has its own memory and its own chats — `manage_memory`,
`list_sessions` and `search_chats` answer from them (they answered *not
available* in every case, or from whatever the process had set) — and a
case makes no loopback call: `resolve_contact` asks the world's mailbox for
the mail history, and any request to the install's own address is refused
in the world's words, so no case reads or writes a running install.

`B1607`. A world has a screen and other models. `screens` is what the
workstation's screen shows — the entry with no `after` before any action, and
each entry's `screen` once an action whose words hold its `after` is done (a
URL typed, "click at (1100, 600)") — kept until the next action changes it, so
`computer` shows the page the agent is on; with no `screens` it answers by its
shell rules as before. `models` is each model's replies, by words in the
message (or one reply for any), and `list_models` lists them as it lists an
endpoint's; `chat_with_model` answers from them, refuses a model the world
does not have in the real tool's words, and without `models` is refused as
any tool that would leave the install.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Dict, List, Optional, Tuple

EVAL_FILE = "evals.json"
MAX_CASES = 10
EVAL_OWNER = "eval"
SCRIPTED_MODEL = "scripted"
SCRIPTED_URL = "http://127.0.0.1:9/v1"

# What the world answers: everything that would reach outside the install.
MAIL_TOOLS = {"list_email_accounts", "list_emails", "search_emails", "read_email",
              "scan_email_unsubscribes", "download_attachment"}
SEND_TOOLS = {"send_email", "reply_to_email", "bulk_email", "unsubscribe_email",
              "archive_email", "delete_email", "mark_email_read"}
DRAFT_TOOLS = {"draft_email", "draft_email_reply", "ai_draft_email_reply"}
WEB_TOOLS = {"web_search", "web_fetch"}
SHELL_TOOLS = {"bash", "python", "computer", "host_shell"}
WORLD_TOOLS = MAIL_TOOLS | SEND_TOOLS | DRAFT_TOOLS | WEB_TOOLS | SHELL_TOOLS
#: `P24-27`. A tool with any of these effects reaches outside the install. One
#: the world answers is above; any other — `trigger_research`, `search_hf_models`,
#: `chat_with_model`, `network` — asks the install's own server or the network
#: for real, so the world answers it or refuses it, never the real one.
OUTSIDE_EFFECTS = frozenset({"network_egress", "brokered_network_read", "external_side_effect"})

CHECK_KINDS = ("answer_contains", "answer_lacks", "document", "no_document", "called",
               "not_called", "drafts_at_most", "draft_to", "no_draft_to", "status",
               "file", "notebook_contains")
WORLD_KEYS = ("emails", "web", "search", "shell", "documents", "notes", "calendar", "files", "accounts",
              "research", "memories", "chats", "screens", "models")
#: `B1607`. Where a world's `models` are listed — an endpoint no request
#: reaches (the discard port, as the scripted model's): `chat_with_model` is
#: the world's, and `list_models` reads the row, not the address.
WORLD_MODELS_URL = "http://127.0.0.1:9/world-models/v1"
WORLD_MODELS_ENDPOINT = "World models"
#: What the screen shows when a world gives `screens` but no starting one.
BLANK_SCREEN = "The workstation's browser, on an empty tab."


class EvalRefused(ValueError):
    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


# ── The file ────────────────────────────────────────────────────────────────

def _need(ok: bool, sentence: str) -> None:
    if not ok:
        raise EvalRefused(sentence)


def lint_evals(data: Any, manifest) -> List[Dict[str, Any]]:
    """The one rule for `evals.json`. Answers its cases or refuses in a sentence."""
    _need(isinstance(data, dict) and set(data) == {"cases"}, "evals.json is an object with one key, “cases”.")
    cases = data["cases"]
    _need(isinstance(cases, list) and 1 <= len(cases) <= MAX_CASES,
          f"An evaluation set has 1 to {MAX_CASES} cases.")
    keys = {i["key"] for i in manifest.inputs}
    seen = set()
    for n, case in enumerate(cases, start=1):
        _need(isinstance(case, dict), f"Case {n} is not an object.")
        cid = str(case.get("id") or "")
        _need(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", cid)), f"Case {n}'s id “{cid}” is not lower-case words joined by dashes.")
        _need(cid not in seen, f"Two cases are called “{cid}”.")
        seen.add(cid)
        extra = set(case) - {"id", "about", "inputs", "world", "answers", "script", "checks", "notebook", "trigger"}
        _need(not extra, f"Case “{cid}” has a field nothing reads: {', '.join(sorted(extra))}.")
        _need(isinstance(case.get("notebook", ""), str),
              f"Case “{cid}”'s notebook is the text the last run carried forward, not a list or a map.")
        trig = case.get("trigger")
        if trig is not None:
            from src.event_bus import EVENT_NAMES
            _need(isinstance(trig, dict) and (
                (set(trig) == {"webhook"} and isinstance(trig["webhook"], dict))
                or (set(trig) <= {"event", "data"} and trig.get("event") in EVENT_NAMES
                    and isinstance(trig.get("data", {}), dict))),
                f"Case “{cid}”'s trigger is {{\"webhook\": {{body, json, query, headers}}}} or "
                f"{{\"event\": <an event Pantheon raises>, \"data\": {{…}}}}.")
        unknown = set(case.get("inputs") or {}) - keys
        _need(not unknown, f"Case “{cid}” gives inputs the agent does not ask for: {', '.join(sorted(unknown))}.")
        world = case.get("world") or {}
        _need(isinstance(world, dict) and not (set(world) - set(WORLD_KEYS)),
              f"Case “{cid}”'s world has keys nothing reads; a world has: {', '.join(WORLD_KEYS)}.")
        _lint_screens_and_models(cid, world)
        for a in case.get("answers") or []:
            _need(a in ("approve_task", "deny"), f"Case “{cid}” answers “{a}”; an answer is approve_task or deny.")
        checks = case.get("checks") or []
        _need(isinstance(checks, list), f"Case “{cid}”'s checks are not a list.")
        for c in checks:
            _need(isinstance(c, dict) and len(c) == 1 and next(iter(c)) in CHECK_KINDS,
                  f"Case “{cid}” has a check Pantheon cannot run; a check is one of: {', '.join(CHECK_KINDS)}.")
        script = case.get("script")
        if script is not None:
            _need(isinstance(script, list) and all(
                isinstance(r, dict) and len(r) == 1 and next(iter(r)) in ("call", "say") for r in script),
                f"Case “{cid}”'s script is a list of rounds, each {{\"call\": [[tool, args], …]}} or {{\"say\": text}}.")
            for r in script:
                for call in r.get("call") or []:
                    _need(isinstance(call, list) and len(call) == 2 and isinstance(call[1], dict),
                          f"Case “{cid}” has a call that is not [tool, {{args}}].")
    return cases


def _lint_screens_and_models(cid: str, world: Dict[str, Any]) -> None:
    """`B1607`. A world's screen and models, each refused in a sentence."""
    if "screens" in world:
        screens = world["screens"]
        _need(isinstance(screens, list) and all(
            isinstance(r, dict) and isinstance(r.get("screen"), str) and r["screen"].strip()
            and set(r) <= {"after", "screen"} and isinstance(r.get("after", ""), str) for r in screens),
            f"Case “{cid}”'s screens are a list of {{\"screen\": what it shows}}, each but the first "
            f"with \"after\": words in the action that brings it up.")
        _need(sum(1 for r in screens if not r.get("after")) <= 1,
              f"Case “{cid}” gives more than one screen with no “after”; only the starting screen has none.")
    if "models" in world:
        models = world["models"]
        _need(isinstance(models, dict) and models and all(isinstance(k, str) and k.strip() for k in models),
              f"Case “{cid}”'s models are a map of model name → its replies.")
        for name, rules in models.items():
            _need(isinstance(rules, str) or (isinstance(rules, list) and all(
                isinstance(r, dict) and set(r) <= {"match", "reply", "error"}
                and (isinstance(r.get("reply"), str) != isinstance(r.get("error"), str)) for r in rules)),
                f"Case “{cid}”'s model “{name}” answers with one reply, or a list of "
                f"{{\"match\": words in the message, \"reply\": its answer}} (or \"error\": why it failed).")


def agent_dir(manifest) -> str:
    return os.path.dirname(manifest.path) if getattr(manifest, "path", "") else ""


def load_evals(manifest) -> List[Dict[str, Any]]:
    """The agent's cases, `[]` when it ships none. A broken file refuses."""
    path = os.path.join(agent_dir(manifest), EVAL_FILE)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise EvalRefused(f"evals.json is not JSON: {exc}.") from None
    return lint_evals(data, manifest)


# ── The world ───────────────────────────────────────────────────────────────

@dataclass
class World:
    """A case's outside world, and the record of every tool the run called."""
    fixture: Dict[str, Any]
    calls: List[Dict[str, Any]] = field(default_factory=list)
    drafts: List[Dict[str, Any]] = field(default_factory=list)
    sent: List[Dict[str, Any]] = field(default_factory=list)
    research: List[str] = field(default_factory=list)
    #: `B1602`. Every request a case made to the install's own address —
    #: refused, so none reached a running install; kept so a test can say so.
    loopback: List[str] = field(default_factory=list)
    #: `B1607`. What the screen shows now (`screens`), and every message a
    #: world model was asked, `(model, message)`.
    screen: Optional[str] = None
    asked: List[Tuple[str, str]] = field(default_factory=list)

    def _args(self, content: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(content or "{}")
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except ValueError:
            return {"text": content or ""}

    def answer(self, tool: str, content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """The world's answer, or `None` when the tool is Pantheon's own."""
        tool = tool.split("__")[-1] if tool.startswith("mcp__email__") else tool
        if tool not in WORLD_TOOLS:
            if not _reaches_outside(tool):
                return None
            out = self._outside(tool, self._args(content))
            text = json.dumps(out, indent=1)
            return f"{tool}: {text[:200]}", {"output": text, "exit_code": 0}
        args = self._args(content)
        out = self._answer(tool, args, content)
        text = out if isinstance(out, str) else json.dumps(out, indent=1)
        return f"{tool}: {text[:200]}", {"output": text, "exit_code": 0}

    def _file_attachment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """`B1600`. An attachment saved into a folder: the world's message
        holds it (`"attachments": [{"filename", "content"}]`), and it is saved
        where the real tool saves it — the world person's projects folder, by
        the same rule (`tool_execution.save_into_projects`), so a `file`
        check finds it and a destination outside is refused in its words."""
        from src.tool_execution import save_into_projects
        uid = str(args.get("uid") or args.get("id") or "")
        msg = next((m for m in self.fixture.get("emails") or [] if str(m.get("id")) == uid), None)
        try:
            index = int(args.get("index") or 0)
        except (TypeError, ValueError):
            index = -1
        files = (msg or {}).get("attachments") or []
        if msg is None or not 0 <= index < len(files):
            return {"error": f"Attachment index {args.get('index')} not found"}
        att = files[index]
        try:
            path = save_into_projects(EVAL_OWNER, str(args["destination"]).strip(),
                                      str(args.get("filename") or "").strip() or str(att.get("filename") or ""),
                                      str(att.get("content") or "").encode("utf-8"))
        except (ValueError, FileExistsError) as exc:
            return {"error": str(exc)}
        return {"path": path, "filename": att.get("filename"), "saved_as": os.path.basename(path)}

    def mail_contacts(self, name: str) -> List[Dict[str, str]]:
        """`B1602`. The mail history `resolve_contact` searches, from the
        world's mailbox — the mail route's own rule: each From, To or Cc entry
        whose text holds the name gives its address, at most ten."""
        q = str(name or "").strip().lower()
        out: List[Dict[str, str]] = []
        seen = set()
        for m in self.fixture.get("emails") or []:
            for key in ("from", "to", "cc"):
                for part in str(m.get(key) or "").split(","):
                    part = part.strip()
                    if not q or q not in part.lower():
                        continue
                    hit = re.search(r"<([^>]+)>", part)
                    addr = (hit.group(1) if hit else part).strip().lower()
                    if "@" in addr and addr not in seen:
                        seen.add(addr)
                        out.append({"email": addr, "name": part.split("<")[0].strip().strip('"') or addr})
        return out[:10]

    def _outside(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """`P24-27`. A tool that leaves the install and is not one of the
        world's own: deep research the world can start, or a refusal."""
        if tool == "chat_with_model" and "models" in self.fixture:
            return self._model(args)
        if tool == "trigger_research" and "research" in self.fixture:
            topic = str(args.get("topic") or args.get("query") or "").strip()
            self.research.append(topic)
            sid = f"started{len(self.research)}"
            return {"output": f"Deep research started: [{topic}](#research-{sid}).",
                    "session_id": sid, "exit_code": 0}
        return {"error": f"This world has no {tool}: an evaluation runs inside the install, and "
                         f"nothing in an evaluation leaves it.", "exit_code": 1}

    def _computer(self, content: str) -> Dict[str, Any]:
        """`B1607`. One action on the world's screen: the action the real tool
        would take (`computer_tools.parse_args`, refused in its words), then
        the screen it leaves — the entry whose `after` is in what was done, or
        the screen as it was. The picture is the screen's text: an evaluation
        has no display, and a model reads it as it would read a screenshot."""
        from src.agent_tools.computer_tools import SCREENSHOT, describe_action, parse_args
        args, problem = parse_args(content)
        if problem:
            return {"error": problem, "exit_code": 1}
        rules = self.fixture.get("screens") or []
        if self.screen is None:
            self.screen = next((r["screen"] for r in rules if not r.get("after")), BLANK_SCREEN)
        what = describe_action(args)
        if args["action"] != SCREENSHOT:
            done = (what + "\n" + json.dumps(args, ensure_ascii=False)).lower()
            hit = next((r for r in rules if r.get("after") and r["after"].lower() in done), None)
            if hit is not None:
                self.screen = hit["screen"]
        did = "Took a screenshot." if args["action"] == SCREENSHOT else f"Did: {what}."
        return {"output": f"{did} The screen shows: {self.screen}", "exit_code": 0,
                "screenshot_caption": "Screen" if args["action"] == SCREENSHOT else f"Screen after {what}"}

    def _model(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """`B1607`. `chat_with_model` from the world's `models`: the model by
        name (exact, then in part, as `_resolve_model` matches), the first
        reply whose `match` is in the message. A model the world lacks is
        refused in the real tool's words."""
        if "model" in args:
            spec, message = str(args.get("model") or ""), str(args.get("message") or "")
        else:
            spec, _, message = str(args.get("text") or "").strip().partition("\n")
        spec, message = spec.strip(), message.strip()
        if not spec:
            return {"error": "First line must be the model name"}
        if not message:
            return {"error": "No message provided (line 2+ is the message)"}
        name = spec.rsplit("@", 1)[0].strip().lower()
        models = self.fixture.get("models") or {}
        key = next((k for k in models if k.lower() == name), None) or next(
            (k for k in models if name and (name in k.lower() or k.lower() in name)), None)
        if key is None:
            return {"error": f"Model '{spec}' is not listed by any endpoint now. "
                             f"Call list_models for the names that are."}
        self.asked.append((key, message))
        rules = models[key]
        if isinstance(rules, str):
            return {"model": key, "response": rules}
        low = message.lower()
        hit = next((r for r in rules if not r.get("match") or str(r["match"]).lower() in low), None)
        if hit is None:
            return {"error": f"Failed to get response from {spec}: it gave no answer to that in this world.",
                    "untrusted_content": True}
        if "error" in hit:
            return {"error": f"Failed to get response from {spec}: {hit['error']}", "untrusted_content": True}
        return {"model": key, "response": hit["reply"]}

    def _answer(self, tool: str, args: Dict[str, Any], content: str):
        mails = self.fixture.get("emails") or []
        if tool == "list_email_accounts":
            return self.fixture.get("accounts") or [{"id": "inbox", "address": "me@example.com"}]
        if tool in ("list_emails", "search_emails"):
            words = str(args.get("query") or args.get("q") or "").lower().split()
            rows = []
            for m in mails:
                hay = " ".join(str(m.get(k, "")) for k in ("from", "subject", "body")).lower()
                if words and not any(w in hay for w in words if len(w) > 2):
                    continue
                rows.append({k: m.get(k) for k in ("id", "from", "to", "subject", "date") if m.get(k)}
                            | {"unread": m.get("unread", True)})
            return {"messages": rows}
        if tool == "read_email":
            mid = str(args.get("id") or args.get("message_id") or args.get("uid") or "")
            for m in mails:
                if str(m.get("id")) == mid:
                    return m
            return {"error": f"No message {mid}."}
        if tool == "scan_email_unsubscribes":
            return {"senders": [{"from": m.get("from"), "unsubscribe": m.get("unsubscribe")}
                                for m in mails if m.get("unsubscribe")]}
        if tool == "download_attachment":
            if str(args.get("destination") or "").strip():
                return self._file_attachment(args)
            return {"saved": args.get("filename") or "attachment"}
        if tool in DRAFT_TOOLS:
            self.drafts.append({"tool": tool, **args})
            return {"draft": "saved", "id": f"d{len(self.drafts)}"}
        if tool in SEND_TOOLS:
            self.sent.append({"tool": tool, **args})
            return {"ok": True}
        if tool == "web_search":
            q = str(args.get("query") or args.get("q") or "").lower()
            for key, results in (self.fixture.get("search") or {}).items():
                if key.lower() in q:
                    return {"results": results}
            return {"results": []}
        if tool == "web_fetch":
            url = str(args.get("url") or "")
            page = (self.fixture.get("web") or {}).get(url)
            return page if page is not None else {"error": f"{url} answered 404 in this world."}
        if tool == "computer" and "screens" in self.fixture:
            return self._computer(content)
        # A shell: the first rule whose `match` is in the command answers.
        cmd = str(args.get("command") or args.get("code") or args.get("action") or content or "")
        for rule in self.fixture.get("shell") or []:
            if rule.get("match", "") in cmd:
                return {"output": rule.get("output", ""), "exit_code": rule.get("exit_code", 0)}
        return {"output": "", "error": "This world has no machine that answers that command.", "exit_code": 127}


def _reaches_outside(tool: str) -> bool:
    from src.tool_capabilities import capabilities_for_tool
    caps = capabilities_for_tool(tool)
    return bool({e.value for e in caps.effects} & OUTSIDE_EFFECTS)


# ── Isolation ───────────────────────────────────────────────────────────────

class _Patches:
    def __init__(self):
        self._undo: List[Tuple[Any, str, Any]] = []

    def set(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name, None)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


@contextmanager
def isolated(root: Optional[str] = None):
    """A fresh SQLite file and data folder, swapped in for every module that
    holds the install's `SessionLocal` or `DATA_DIR`, and put back after."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    import core.database as cdb
    import src.constants as constants

    # `P24-27`. A world the harness makes is removed when it ends: each is a
    # SQLite file and a data folder, and a roster's evaluation runs hundreds.
    made_here = root is None
    root = root or tempfile.mkdtemp(prefix="pantheon-eval-")
    data = os.path.join(root, "data")
    os.makedirs(data, exist_ok=True)
    engine = create_engine(f"sqlite:///{os.path.join(root, 'eval.db')}",
                           connect_args={"check_same_thread": False}, poolclass=NullPool)
    cdb.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    p = _Patches()
    old_session, old_data = cdb.SessionLocal, constants.DATA_DIR

    def _swap(frm_session, to_session, frm_data, to_data, record):
        for mod in list(sys.modules.values()):
            try:
                if getattr(mod, "SessionLocal", None) is frm_session:
                    p.set(mod, "SessionLocal", to_session) if record else setattr(mod, "SessionLocal", to_session)
                if isinstance(frm_data, str) and getattr(mod, "DATA_DIR", None) == frm_data:
                    p.set(mod, "DATA_DIR", to_data) if record else setattr(mod, "DATA_DIR", to_data)
            except Exception:
                continue

    def _swap_paths(frm_data, to_data, record):
        """`P24-27`. A path the install derived from its data folder at
        import — `DEEP_RESEARCH_DIR`, `CONTACTS_FILE`, `COOKBOOK_STATE_FILE` —
        is the world's while it lasts: swapping `DATA_DIR` alone left
        `manage_research` reading the install's research and `manage_contact`
        writing its address book."""
        if not isinstance(frm_data, str) or not frm_data:
            return
        prefix = frm_data.rstrip(os.sep) + os.sep
        for mod in list(sys.modules.values()):
            name = getattr(mod, "__name__", "") or ""
            if not name.startswith(("src.", "routes.", "core.", "services.", "mcp_servers.")):
                continue
            try:
                found = [(k, v) for k, v in vars(mod).items()
                         if isinstance(v, (str, PurePath))
                         and (str(v).startswith(prefix) or str(v) == prefix.rstrip(os.sep))]
            except Exception:
                continue
            for k, v in found:
                # A `Path` stays a `Path` (`LOCAL_CONTACTS_FILE`, the contacts
                # route's own `DATA_DIR`): kept as a string-only swap, the
                # address book pointed into a world that was gone, and later
                # cases wrote into — and recreated — a deleted folder.
                moved = os.path.join(to_data, str(v)[len(prefix):]) if str(v).startswith(prefix) else to_data
                moved = type(v)(moved) if isinstance(v, PurePath) else moved
                p.set(mod, k, moved) if record else setattr(mod, k, moved)

    _swap(old_session, factory, old_data, data, True)
    _swap_paths(old_data, data, True)
    # A module may hold a session factory or data folder that is not the
    # install's current one (one copied while something else had swapped them
    # — a test, an earlier world). Every one of ours is swapped, so nothing a
    # case runs can write outside its world.
    from sqlalchemy.orm import sessionmaker as _sm
    for mod in list(sys.modules.values()):
        name = getattr(mod, "__name__", "") or ""
        if not name.startswith(("src.", "routes.", "core.", "services.")):
            continue
        try:
            if isinstance(getattr(mod, "SessionLocal", None), _sm) and mod.SessionLocal is not factory:
                p.set(mod, "SessionLocal", factory)
            if isinstance(getattr(mod, "DATA_DIR", None), str) and mod.DATA_DIR != data:
                p.set(mod, "DATA_DIR", data)
        except Exception:
            continue
    # `B1602`. The world's own memory and chats. `manage_memory` and the
    # session tools ask `ai_interaction`'s managers, which only the app's boot
    # sets: a case answered "Memory manager not available" — or, in a process
    # where something had set them, read and wrote that memory file and that
    # session cache. Made after the swap, so they read the world's database
    # and folder; the process's own are put back after.
    import core.models as core_models
    import src.ai_interaction as ai
    from core.session_manager import SessionManager
    from src.memory import MemoryManager
    world_sessions = SessionManager()
    p.set(ai, "_memory_manager", MemoryManager(data))
    p.set(ai, "_memory_vector", None)
    p.set(ai, "_session_manager", world_sessions)
    p.set(core_models, "_SESSION_MANAGER_INSTANCE", world_sessions)
    # The address book's one-minute cache is the process's: a copy read from
    # the install would answer a case's `resolve_contact`, and the world's
    # would answer the install's for a minute after.
    contacts_mod = sys.modules.get("routes.contacts.contacts_routes")
    if contacts_mod is not None:
        p.set(contacts_mod, "_contact_cache", {"contacts": [], "fetched_at": None})
    # No person is in the world, so a background run waits for nobody; the
    # variable is the install's again afterwards.
    old_gate = os.environ.get("BACKGROUND_TASK_FOREGROUND_GATE")
    os.environ["BACKGROUND_TASK_FOREGROUND_GATE"] = "0"
    try:
        yield factory, data
    finally:
        if old_gate is None:
            os.environ.pop("BACKGROUND_TASK_FOREGROUND_GATE", None)
        else:
            os.environ["BACKGROUND_TASK_FOREGROUND_GATE"] = old_gate
        p.undo()
        # A module first imported inside the world copied the world's names;
        # it is given the install's back, so nothing outlives the world.
        _swap(factory, old_session, data, old_data, False)
        _swap_paths(data, old_data, False)
        if contacts_mod is None and "routes.contacts.contacts_routes" in sys.modules:
            # First imported in the world: its cache holds the world's book.
            sys.modules["routes.contacts.contacts_routes"]._contact_cache = {"contacts": [], "fetched_at": None}
        engine.dispose()
        if made_here:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


# ── The model ───────────────────────────────────────────────────────────────

def scripted_model(script: List[Dict[str, Any]]):
    """The agent loop's model call, answered round by round from `script`;
    past its end it says only "Done." — a model that stopped."""
    rounds = iter(script)

    async def model(candidates, messages, **kwargs):
        step = next(rounds, {"say": "Done."})
        if "call" in step:
            calls = [{"name": n, "arguments": json.dumps(a)} for n, a in step["call"]]
            yield "data: " + json.dumps({"type": "tool_calls", "calls": calls}) + "\n\n"
        else:
            yield "data: " + json.dumps({"delta": step["say"]}) + "\n\n"
        yield "data: [DONE]\n\n"
    return model


def scripted_window(endpoint_url: str, model: str):
    """`P24-27`. The scripted model's context window: what asking its endpoint
    (the discard port) always answers — the default, as a fallback — without
    the request. A case reaches no host; a real endpoint is asked as ever."""
    from src import model_context as mc
    return mc.DEFAULT_CONTEXT, False, mc.BASIS_FALLBACK


# ── A run ───────────────────────────────────────────────────────────────────

def _trigger(spec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """`P24-27`. A case's `trigger` as the run would get it — the event bus's
    own envelope, so a webhook's payload keeps only what a webhook hands on."""
    if not spec:
        return None
    from src.event_bus import (TRIGGER_SOURCE_EVENT, TRIGGER_SOURCE_WEBHOOK,
                               WEBHOOK_PAYLOAD_FIELDS, build_trigger)
    if "webhook" in spec:
        return build_trigger(TRIGGER_SOURCE_WEBHOOK, TRIGGER_SOURCE_WEBHOOK, spec["webhook"],
                             fields=WEBHOOK_PAYLOAD_FIELDS)
    return build_trigger(TRIGGER_SOURCE_EVENT, spec["event"], spec.get("data") or {})


@dataclass
class CaseResult:
    agent: str
    case: str
    passed: bool
    status: str
    checks: List[Dict[str, Any]]
    minutes: float
    calls: List[str]
    report: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    #: `B1602`. Requests the case made to the install's own address, refused.
    loopback: List[str] = field(default_factory=list)
    #: `B1604`. The documents the run wrote, `{title, content}` — what a
    #: document agent delivers, which its short answer only names.
    documents: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"agent": self.agent, "case": self.case, "passed": self.passed, "status": self.status,
                "checks": self.checks, "minutes": round(self.minutes, 2), "calls": self.calls,
                "error": self.error}


def _when(text: str):
    """`today 09:00`, `tomorrow 14:30` or an ISO time, in the world's clock."""
    from datetime import datetime, timedelta
    m = re.fullmatch(r"(today|tomorrow|yesterday) (\d\d):(\d\d)", str(text).strip())
    if m:
        day = {"today": 0, "tomorrow": 1, "yesterday": -1}[m.group(1)]
        base = datetime.now().replace(hour=int(m.group(2)), minute=int(m.group(3)), second=0, microsecond=0)
        return base + timedelta(days=day)
    return datetime.fromisoformat(str(text))


def _seed(db, owner: str, world: Dict[str, Any], data_dir: str) -> Dict[str, str]:
    """Put the world's own stores in place. Answers the documents it seeded,
    id → text, so what a run wrote can be told from what it was given."""
    from datetime import timedelta
    from core.database import CalendarCal, CalendarEvent, Document, Note
    seeded: Dict[str, str] = {}
    for d in world.get("documents") or []:
        # `P24-27`. A document (and a note, below) may name its id, so a
        # script can open, change or delete it.
        did = str(d.get("id") or uuid.uuid4())
        seeded[did] = d.get("content", "")
        db.add(Document(id=did, owner=owner, title=d["title"], current_content=d.get("content", "")))
    for n in world.get("notes") or []:
        db.add(Note(id=str(n.get("id") or uuid.uuid4()), owner=owner, title=n.get("title", ""), content=n.get("content", ""),
                    due_date=n.get("due")))
    if world.get("calendar"):
        cal = CalendarCal(id=str(uuid.uuid4()), owner=owner, name="Personal")
        db.add(cal)
        db.flush()
        for e in world["calendar"]:
            start = _when(e["start"])
            db.add(CalendarEvent(uid=str(uuid.uuid4()), calendar_id=cal.id, summary=e["summary"],
                                 location=e.get("location", ""), dtstart=start,
                                 dtend=_when(e["end"]) if e.get("end") else start + timedelta(hours=1)))
    db.commit()
    if world.get("research"):
        # `P24-27`. Finished reports, where the real `manage_research` reads
        # them — the world's own research folder.
        import src.constants as constants
        os.makedirs(constants.DEEP_RESEARCH_DIR, exist_ok=True)
        for n, r in enumerate(world["research"], start=1):
            rid = re.sub(r"[^A-Za-z0-9_-]", "", str(r.get("id") or f"r{n}")) or f"r{n}"
            body = {"query": r.get("query", ""), "summary": r.get("summary", ""), "owner": owner,
                    "sources": r.get("sources") or [], "completed_at": r.get("completed_at", n)}
            with open(os.path.join(constants.DEEP_RESEARCH_DIR, f"{rid}.json"), "w", encoding="utf-8") as fh:
                json.dump(body, fh)
    if world.get("memories"):
        # `B1602`. What the person's memory holds, where `manage_memory` reads it.
        import src.ai_interaction as ai
        mm = ai._memory_manager
        entries = mm.load_all_for_update()
        for item in world["memories"]:
            item = {"text": item} if isinstance(item, str) else item
            entry = mm.add_entry(str(item["text"]), source="eval", owner=owner,
                                 category=str(item.get("category") or "fact"))
            # `P24-27`. A memory may name its id, as a document or a note may,
            # so a script can edit or delete it and an answer can quote it.
            if item.get("id"):
                entry["id"] = str(item["id"])
            entries.append(entry)
        mm.save(entries)
    if world.get("chats"):
        # `B1602`. The person's earlier chats, where the session tools and
        # `search_chats` read them.
        import src.ai_interaction as ai
        from core.models import ChatMessage
        sm = ai._session_manager
        for n, chat in enumerate(world["chats"], start=1):
            sid = str(chat.get("id") or uuid.uuid4())
            sm.create_session(sid, str(chat.get("title") or f"Chat {n}"), "", "", owner=owner)
            for msg in chat.get("messages") or []:
                sm.add_message(sid, ChatMessage(str(msg.get("role") or "user"), str(msg.get("content") or "")))
    if world.get("models"):
        # `B1607`. The world's models, where `list_models` reads an endpoint's.
        from core.database import ModelEndpoint
        db.add(ModelEndpoint(id=str(uuid.uuid4()), name=WORLD_MODELS_ENDPOINT, is_enabled=True,
                             base_url=WORLD_MODELS_URL, endpoint_kind="local",
                             cached_models=json.dumps(list(world["models"]))))
        db.commit()
    if world.get("files"):
        from src.tool_execution import projects_root
        root = projects_root(owner, create=True)
        for rel, text in world["files"].items():
            path = os.path.normpath(os.path.join(root, rel))
            if path.startswith(root + os.sep):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
    return seeded


def written_documents(db, owner: str, seeded: Dict[str, str]) -> List[Dict[str, str]]:
    """`B1604`. The documents a run wrote — made, or changed from what the
    world gave it — title and text, in the order they were made."""
    from core.database import Document
    rows = db.query(Document).filter(Document.owner == owner, Document.is_active == True).all()  # noqa: E712
    rows.sort(key=lambda d: (d.created_at is None, d.created_at, d.title or ""))
    return [{"title": d.title or "", "content": d.current_content or ""} for d in rows
            if d.id not in seeded or (d.current_content or "") != seeded[d.id]]


def _check(kind: str, want: Any, *, db, owner, answer, status, world: World, notebook: str,
           project_root: str) -> Dict[str, Any]:
    from core.database import Document
    called = [c["tool"] for c in world.calls]
    if kind == "answer_contains":
        missing = [w for w in want if w.lower() not in (answer or "").lower()]
        return {"check": f"the answer says {', '.join(want)}", "ok": not missing,
                "detail": f"It does not say: {', '.join(missing)}." if missing else "It does."}
    if kind == "answer_lacks":
        found = [w for w in want if w.lower() in (answer or "").lower()]
        return {"check": f"the answer never says {', '.join(want)}", "ok": not found,
                "detail": f"It says: {', '.join(found)}." if found else "It does not."}
    if kind in ("document", "no_document"):
        title = want["title"] if isinstance(want, dict) else str(want)
        docs = [d for d in db.query(Document).filter(Document.owner == owner).all()
                if title.lower() in (d.title or "").lower()]
        # `P24-27`. A document with exactly the title named is the one read:
        # an agent that writes "Restyled — Launch note" beside "Launch note"
        # left a check on the original reading the copy.
        docs = [d for d in docs if (d.title or "").strip().lower() == title.strip().lower()] or docs
        if kind == "no_document":
            return {"check": f"no document titled “{title}”", "ok": not docs,
                    "detail": "None was written." if not docs else f"“{docs[0].title}” was written."}
        if not docs:
            return {"check": f"a document titled “{title}”", "ok": False, "detail": "None was written."}
        text = docs[-1].current_content or ""
        miss = [w for w in want.get("contains", []) if w.lower() not in text.lower()]
        bad = [w for w in want.get("lacks", []) if w.lower() in text.lower()]
        ok = not miss and not bad
        detail = "; ".join(filter(None, [miss and f"it has no {', '.join(miss)}", bad and f"it says {', '.join(bad)}"]))
        return {"check": f"the document “{title}”", "ok": ok, "detail": (detail.capitalize() + ".") if detail else "It is right."}
    if kind == "called":
        return {"check": f"it called {want}", "ok": want in called,
                "detail": "It did." if want in called else f"It called only: {', '.join(called) or 'nothing'}."}
    if kind == "not_called":
        ran = [c for c in world.calls if c["tool"] == want and c["ran"]]
        return {"check": f"{want} never ran", "ok": not ran,
                "detail": "It did not." if not ran else f"It ran {len(ran)} time(s)."}
    if kind == "drafts_at_most":
        return {"check": f"at most {want} drafts", "ok": len(world.drafts) <= want,
                "detail": f"It made {len(world.drafts)}."}
    if kind in ("draft_to", "no_draft_to"):
        hits = [d for d in world.drafts if want.lower() in json.dumps(d).lower()]
        ok = bool(hits) if kind == "draft_to" else not hits
        return {"check": ("a draft to " if kind == "draft_to" else "no draft to ") + want, "ok": ok,
                "detail": f"{len(hits)} draft(s) mention {want}."}
    if kind == "status":
        return {"check": f"the run ends {want}", "ok": status == want, "detail": f"It ended {status}."}
    if kind == "file":
        path = os.path.normpath(os.path.join(project_root, want["path"]))
        exists = path.startswith(project_root + os.sep) and os.path.isfile(path)
        text = open(path, encoding="utf-8", errors="replace").read() if exists else ""
        miss = [w for w in want.get("contains", []) if w.lower() not in text.lower()]
        # `P24-27`. What the file must lack, as a document's check may say:
        # a mockup that loads a font from the internet breaks a *never*.
        bad = [w for w in want.get("lacks", []) if w.lower() in text.lower()]
        detail = "; ".join(filter(None, [miss and f"it has no {', '.join(miss)}", bad and f"it says {', '.join(bad)}"]))
        return {"check": f"the file {want['path']}", "ok": exists and not miss and not bad,
                "detail": "It is right." if exists and not detail else
                ("It is not there." if not exists else detail.capitalize() + ".")}
    if kind == "notebook_contains":
        return {"check": f"its notebook keeps {want}", "ok": want.lower() in (notebook or "").lower(),
                "detail": "It does." if want.lower() in (notebook or "").lower() else "It does not."}
    return {"check": kind, "ok": False, "detail": "Pantheon cannot run this check."}


def _is_loopback(url, base) -> bool:
    """Whether `url` is the install's own address (`internal_api_base`), on
    any of the names loopback goes by."""
    import httpx
    try:
        u, b = httpx.URL(str(url)), httpx.URL(base)
    except Exception:
        return False
    local = {"127.0.0.1", "localhost", "::1", "0.0.0.0", b.host}
    return u.host in local and (u.port or 80) == (b.port or 80)


def _refuse_loopback(p: "_Patches", world: World) -> None:
    """`B1602`. A case runs inside the install, not against it: a request to
    the install's own address — a tool that asks Pantheon's server over HTTP —
    would read or write whatever install is running on the machine. Every one
    is refused in the world's words and kept on `world.loopback`."""
    import httpx
    from src.constants import internal_api_base
    base = internal_api_base()

    def refusal(request):
        world.loopback.append(str(request.url))
        return httpx.ConnectError(
            f"This world has no Pantheon server to call ({request.url.path}): an evaluation runs "
            f"inside the install, and nothing in an evaluation calls it over the network.",
            request=request)

    real_async, real_sync = httpx.AsyncClient.send, httpx.Client.send

    async def send_async(self, request, *a, **kw):
        if _is_loopback(request.url, base):
            raise refusal(request)
        return await real_async(self, request, *a, **kw)

    def send_sync(self, request, *a, **kw):
        if _is_loopback(request.url, base):
            raise refusal(request)
        return real_sync(self, request, *a, **kw)

    p.set(httpx.AsyncClient, "send", send_async)
    p.set(httpx.Client, "send", send_sync)


async def run_case(manifest, case: Dict[str, Any], *, factory, data_dir: str,
                   endpoint: Optional[str] = None, model: Optional[str] = None) -> CaseResult:
    """One case, in a world `isolated()` already made. With no `endpoint` the
    case's `script` is the model."""
    import httpx
    from fastapi import FastAPI
    import src.agent_loop as agent_loop
    import src.tool_execution as tool_execution
    from core.database import AgentHire, AgentRunReport, ModelEndpoint, ScheduledTask, TaskRun
    from src.agents import hires as H
    from src.task_scheduler import TaskScheduler

    owner = EVAL_OWNER
    world = World(case.get("world") or {})
    p = _Patches()
    started = time.monotonic()
    real_impl = tool_execution._execute_tool_block_impl

    async def far_end(block, *a, **kw):
        tool = getattr(block, "tool_type", "")
        out = world.answer(tool, getattr(block, "content", ""))
        bare = tool[len("mcp__email__"):] if tool.startswith("mcp__email__") else tool
        world.calls.append({"tool": bare, "ran": True})
        if out is not None:
            return out
        return await real_impl(block, *a, **kw)

    p.set(tool_execution, "_execute_tool_block_impl", far_end)
    # `B1602`. `resolve_contact` searched the mail history by calling the
    # install's own mail route over loopback — whatever install was running on
    # the machine, its mailbox. The world's mailbox answers instead, as it
    # answers every other mail tool.
    import src.tools.contacts as contacts_tools

    async def world_mail_history(name, owner=None):
        return world.mail_contacts(name), None

    p.set(contacts_tools, "mail_history", world_mail_history)
    _refuse_loopback(p, world)
    # The world's one person is its admin: a case measures the agent, not
    # the privileges of whoever hires it (the hire form names what a run
    # will lack, `P24-13`).
    for mod in list(sys.modules.values()):
        for fname in ("_owner_is_admin", "owner_is_admin", "owner_has_admin_task_privileges"):
            fn = getattr(mod, fname, None)
            if callable(fn) and getattr(mod, "__name__", "").startswith(("src.", "routes.", "core.")):
                p.set(mod, fname, (lambda real: lambda o, *a, **k: o == EVAL_OWNER or real(o, *a, **k))(fn))
    p.set(agent_loop, "blocked_tools_for_owner", lambda o: set())
    # `B1607`. The world is the workstation: `computer` is answered from its
    # screens (or shell rules), so the loop offers it. It was withheld — no
    # workstation is set up in a world — so every case's `computer` call was
    # refused before the world could answer it, and Site Builder's sample
    # said "screenshot taken" over a refusal.
    p.set(agent_loop, "_computer_unavailable_reason", lambda owner, **kw: None)
    p.set(agent_loop, "get_mcp_manager", lambda: None)
    url, name = endpoint or SCRIPTED_URL, model or SCRIPTED_MODEL
    if endpoint is None:
        p.set(agent_loop, "stream_llm_with_fallback", scripted_model(case.get("script") or []))
        p.set(agent_loop, "_agent_route_tool_mode",
              lambda url, model, owner=None, headers=None: (True, False, False))
        import src.task_endpoint as task_endpoint
        p.set(task_endpoint, "resolve_task_candidates", lambda **kw: [])
        # `P24-27`. The run asked the scripted endpoint for its window about
        # twice a case — a loopback request each, 45% of an evaluation's time.
        import src.model_context as model_context
        real_window = model_context._query_context_length
        p.set(model_context, "_query_context_length",
              lambda u, m: scripted_window(u, m) if str(u).startswith(SCRIPTED_URL) and m == SCRIPTED_MODEL
              else real_window(u, m))
    try:
        db = factory()
        if not db.query(ModelEndpoint).filter(ModelEndpoint.base_url == url).first():
            db.add(ModelEndpoint(id=str(uuid.uuid4()), name="Evaluation", is_enabled=True, base_url=url,
                                 endpoint_kind="local", cached_models=json.dumps([name])))
        seeded = _seed(db, owner, case.get("world") or {}, data_dir)
        hire = H.make_hire(db, owner=owner, manifest=manifest, inputs=case.get("inputs") or {})
        # `P24-27`. What the last run carried forward, so a case can measure
        # "new since last time" — read by the run as its notebook always is.
        if case.get("notebook"):
            hire.notebook = case["notebook"]
        db.commit()
        tid = H.task_ids_of(db, hire.id)[0]
        task = db.get(ScheduledTask, tid)
        task.endpoint_url, task.model = url, name
        db.commit()
        hire_id = hire.id
        db.close()

        sched = TaskScheduler(None)
        sched._log_to_assistant = lambda *a, **k: None
        await sched._execute_task(tid, trigger=_trigger(case.get("trigger")))
        answers = list(case.get("answers") or [])
        app = FastAPI()

        @app.middleware("http")
        async def _who(request, call_next):
            request.state.current_user = owner
            return await call_next(request)

        import routes.task.task_routes as task_routes
        p.set(task_routes, "SessionLocal", factory)
        app.include_router(task_routes.setup_task_routes(sched))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval") as c:
            for _ in range(len(answers) + 1):
                waiting = (await c.get("/api/tasks/waiting")).json().get("waiting") or []
                mine = [q for q in waiting if q["task_id"] == tid and q.get("approval")]
                if not mine or not answers:
                    break
                q = mine[0]
                await c.post(f"/api/tasks/{tid}/runs/{q['run_id']}/answer",
                             json={"approval_id": q["approval"]["approval_id"], "decision": answers.pop(0)})
                for _ in range(400):
                    await asyncio.sleep(0.01)
                    if not sched._executing:
                        break

        db = factory()
        run = db.query(TaskRun).filter(TaskRun.task_id == tid).order_by(TaskRun.started_at.desc()).first()
        status = run.status if run else "none"
        answer = (run.result or "") if run else ""
        rep = db.get(AgentRunReport, run.id) if run else None
        report = json.loads(rep.report) if rep else None
        hire_row = db.get(AgentHire, hire_id)
        notebook = (hire_row.notebook or "") if hire_row else ""
        from src.tool_execution import projects_root
        proot = projects_root(owner, create=False)
        if report and report.get("answer"):
            answer = report["answer"]
        contract = list((report or {}).get("checks") or [])
        own = []
        for c in case.get("checks") or []:
            kind, want = next(iter(c.items()))
            own.append(_check(kind, want, db=db, owner=owner, answer=answer, status=status, world=world,
                              notebook=notebook, project_root=proot))
        documents = written_documents(db, owner, seeded)
        db.close()
        # A case that expects the run to fail (`{"status": "error"}`) is the
        # harness checking itself: its contract misses are what it expects.
        expects_failure = {"status": "error"} in (case.get("checks") or [])
        checks = contract + own
        passed = bool(own or contract) and all(c["ok"] for c in own) and (
            expects_failure or all(c["ok"] for c in contract))
        return CaseResult(manifest.id, case["id"], passed, status, checks,
                          (time.monotonic() - started) / 60, [c["tool"] for c in world.calls], report,
                          None if run is None else run.error, loopback=list(world.loopback),
                          documents=documents)
    finally:
        p.undo()


async def run_agent(manifest, *, endpoint=None, model=None, runs: int = 1, cases=None) -> List[CaseResult]:
    """Every case of one agent, each `runs` times, each in its own world."""
    out = []
    for case in (cases if cases is not None else load_evals(manifest)):
        for _ in range(runs):
            with isolated() as (factory, data):
                out.append(await run_case(manifest, case, factory=factory, data_dir=data,
                                          endpoint=endpoint, model=model))
    return out


# ── A proof row ─────────────────────────────────────────────────────────────

def proof_row(manifest, model: str, results: List[CaseResult]) -> Dict[str, Any]:
    """`P24-18`. One row: agent, version, model, pass rate, median minutes,
    the failures by check — what the fit badge reads."""
    by_case: Dict[str, List[CaseResult]] = {}
    for r in results:
        by_case.setdefault(r.case, []).append(r)
    mins = sorted(r.minutes for r in results) or [0.0]
    failures: Dict[str, int] = {}
    for r in results:
        for c in r.checks:
            if not c["ok"]:
                failures[c["check"]] = failures.get(c["check"], 0) + 1
    return {"agent": manifest.id, "version": manifest.version, "model": model,
            "runs": len(results),
            "cases": {cid: {"passed": sum(r.passed for r in rs), "of": len(rs)} for cid, rs in by_case.items()},
            "pass_rate": round(sum(r.passed for r in results) / max(1, len(results)), 3),
            "median_minutes": round(mins[len(mins) // 2], 2),
            "failures": failures, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def sample_report(result: CaseResult) -> Dict[str, Any]:
    """`P24-17`. What `sample.json` holds: a case's report — and, `B1604`, the
    documents the run wrote, since a document agent's answer only names the
    document it delivers. The key is there only when the run wrote one."""
    r0 = result.report or {}
    sample = {"case": result.case, "from": "its evaluation, with a scripted model",
              **{k: r0.get(k) for k in ("summary", "read", "wrote", "refused", "checks", "answer")}}
    if result.documents:
        sample["documents"] = [dict(d) for d in result.documents]
    return sample


def main(argv=None) -> int:
    """`python -m src.agents.evals <agent>|all [--endpoint URL --model NAME] [--runs N] [--out FILE]`"""
    import argparse
    ap = argparse.ArgumentParser(description="Run agents' evaluation sets in an isolated world.")
    ap.add_argument("agent")
    ap.add_argument("--endpoint")
    ap.add_argument("--model")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", help="append proof rows (JSON lines) here")
    ap.add_argument("--sample", action="store_true",
                    help="write each agent's first case's report beside it as sample.json")
    args = ap.parse_args(argv)
    from src.constants import DATA_DIR as install_data
    if args.model and not args.out:
        args.out = os.path.join(install_data, "agent_proofs.jsonl")
    if bool(args.endpoint) != bool(args.model):
        print("A proof run names both --endpoint and --model.")
        return 2
    from src.agents.catalogue import catalogue
    agents, _ = catalogue(None)
    chosen = [m for m in agents if args.agent in ("all", m.id)]
    if not chosen:
        print(f"There is no agent called {args.agent}.")
        return 2
    bad = 0
    for m in chosen:
        cases = load_evals(m)
        if not cases:
            continue
        results = asyncio.run(run_agent(m, endpoint=args.endpoint, model=args.model, runs=args.runs, cases=cases))
        for r in results:
            mark = "pass" if r.passed else "FAIL"
            print(f"{mark}  {m.id} / {r.case}  ({r.status}, {r.minutes:.2f} min)")
            for c in r.checks:
                if not c["ok"]:
                    print(f"      ✗ {c['check']}: {c['detail']}")
            bad += not r.passed
        if args.sample and results and results[0].report:
            sample = sample_report(results[0])
            with open(os.path.join(agent_dir(m), "sample.json"), "w", encoding="utf-8") as fh:
                json.dump(sample, fh, indent=1, ensure_ascii=False)
                fh.write("\n")
        if args.out and args.model:
            with open(args.out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(proof_row(m, args.model, results)) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
