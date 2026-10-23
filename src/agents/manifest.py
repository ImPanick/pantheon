# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-01` · `AGENT.md` — the manifest, its parser and its lint.

An agent is one file: YAML frontmatter that Pantheon reads, then a runbook in
prose that the model reads — the shape `SKILL.md` already has, so a person who
has written a skill has already written most of an agent.

    ---
    id: morning-brief
    name: Morning Brief
    tagline: Today's calendar, urgent mail, due tasks and what changed overnight.
    section: personal-home
    version: 1.0.0
    wave: 1
    starred: true
    inputs:
      - {key: at, kind: time, label: When it arrives, default: "07:30"}
    triggers:
      - {on: daily, at: "{at}"}
    tools: [manage_calendar, list_emails, manage_tasks]
    skills: []
    needs: {connectors: [], min_context: 16000}
    delivers:
      - {kind: answer, must_contain: [Today]}
    effects: {read_private: allow, write_private: allow}
    budget: {runs_per_day: 4, max_steps: 20, max_minutes: 10}
    memory: own
    ---
    ## Runbook
    1. …

**The frontmatter is a small, closed subset of YAML** — `key: scalar`,
`key: [flow, list]`, `key: {flow: map}`, a block list of scalars or flow maps
under a bare `key:`, and a block map of scalars under a bare `key:`. Pantheon
does not depend on PyYAML (`services/memory/skill_format.py` made the same
call for skills), and an agent's frontmatter never needs more than this.

**The lint is the one rule for what an agent may be** (`Law 7`). The catalogue
asks it of every file it reads and lists a file that fails it as broken, never
as hireable; the hire route asks it again of the manifest it is about to hire,
so a file edited between the listing and the click cannot slip past. Every
refusal is a sentence naming the field (`Law 10`, `Law 15`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── The vocabulary ──────────────────────────────────────────────────────────

#: The hall's sections, in the order it shows them, each with its family. The
#: plan's § 7 table, one row per chip. An id is what a manifest writes; the
#: label is what a person reads.
SECTIONS: Tuple[Tuple[str, str, str], ...] = (
    ("email", "Email & Inbox", "everyday"),
    ("personal-home", "Personal & Home", "everyday"),
    ("learning", "Learning & Coaching", "everyday"),
    ("creative", "Creative & Media", "everyday"),
    ("research", "Research & Intelligence", "knowledge"),
    ("writing", "Writing & Documents", "knowledge"),
    ("knowledge", "Knowledge & Memory", "knowledge"),
    ("development", "Development", "engineering"),
    ("testing", "Testing & QA", "engineering"),
    ("ai-engineering", "AI Engineering", "engineering"),
    ("workstation", "Workstation & Desktop", "engineering"),
    ("devops", "DevOps & Infrastructure", "engineering"),
    ("home-lab", "Home Lab & Network", "engineering"),
    ("security", "Security & Compliance", "engineering"),
    ("data-analytics", "Data & Analytics", "engineering"),
    ("databases", "Data & Databases", "engineering"),
    ("design", "Design & UX", "business"),
    ("product", "Product & Projects", "business"),
    ("marketing", "Marketing & Content", "business"),
    ("seo", "SEO & Growth", "business"),
    ("social", "Social Media", "business"),
    ("sales", "Sales & CRM", "business"),
    ("support", "Support", "business"),
    ("finance", "Finance & Operations", "business"),
    ("legal-people", "Legal & People", "business"),
    ("ecommerce", "E-commerce", "business"),
)
SECTION_IDS = tuple(s[0] for s in SECTIONS)
FAMILIES: Tuple[Tuple[str, str], ...] = (
    ("everyday", "Everyday"),
    ("knowledge", "Knowledge"),
    ("engineering", "Engineering"),
    ("business", "Business"),
)

#: What a hire form can ask for. Each kind is a picker the form knows how to
#: draw and a value `check_inputs` knows how to check.
INPUT_KINDS = (
    "text", "long_text", "list", "number", "time", "choice", "boolean",
    "email_account", "folder", "url",
)

#: When a hire starts. `daily`/`weekly`/`cron` are a schedule, `event` is the
#: event bus, `webhook` is a URL, `hand` is *Run now* alone.
TRIGGER_KINDS = ("daily", "weekly", "cron", "event", "webhook", "hand")
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAYS_SETS = ("every", "weekdays", "weekends")

MEMORY_MODES = ("own", "shared", "none")
EFFECT_RULES = ("allow", "ask", "never")
BUDGET_KEYS = ("runs_per_day", "max_steps", "max_minutes")
DELIVER_KINDS = ("answer", "document", "email_draft", "file")
NATIVE_TOOLS = ("required", "preferred", "no")
WAVES = (1, 2, 3)

#: The most a manifest may ask for, whatever it says. A run is a scheduled
#: task, and these are the scheduler's own ceilings stated once for agents.
MAX_STEPS_CEILING = 60
MAX_MINUTES_CEILING = 60
RUNS_PER_DAY_CEILING = 96
RUNBOOK_MAX_CHARS = 12_000
MANIFEST_MAX_BYTES = 64 * 1024

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_INPUT_REF_RE = re.compile(r"^\{([a-z][a-z0-9_]{0,31})\}$")


class ManifestRefused(ValueError):
    """A manifest Pantheon will not list as hireable, and the one sentence why."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


# ── The frontmatter subset ─────────────────────────────────────────────────

def _split_top(s: str, sep: str = ",") -> List[str]:
    """Split on `sep` outside quotes, `[]` and `{}`."""
    out: List[str] = []
    buf: List[str] = []
    depth = 0
    quote: Optional[str] = None
    prev = ""          # the last character that was not a space
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        # A quote opens a value only where a value starts, so the apostrophe
        # in `The project's folder` is a letter, as YAML reads it.
        if ch in ("'", '"') and prev in ("", "[", "{", ",", ":"):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                raise ManifestRefused(f"A bracket closes that never opened: {s.strip()[:60]}")
        if ch == sep and depth == 0:
            out.append("".join(buf).strip())
            buf = []
            prev = ch
            continue
        buf.append(ch)
        if not ch.isspace():
            prev = ch
    if quote or depth:
        raise ManifestRefused(f"A quote or bracket is left open: {s.strip()[:60]}")
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


# flag-spelling: the manifest's YAML subset is the skills reader's sibling and
# reads a boolean exactly as `services/memory/skill_format.py:_parse_scalar`
# does (`true`/`yes`, `false`/`no`) — the same file-format boundary, not a
# fifth vocabulary; its other rules (quotes, flow maps) are its own.
def _value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    if raw[0] == "[":
        if not raw.endswith("]"):
            raise ManifestRefused(f"A list is not closed: {raw[:60]}")
        return [_value(p) for p in _split_top(raw[1:-1])]
    if raw[0] == "{":
        if not raw.endswith("}"):
            raise ManifestRefused(f"A map is not closed: {raw[:60]}")
        out: Dict[str, Any] = {}
        for part in _split_top(raw[1:-1]):
            k, sep, v = part.partition(":")
            if not sep or not k.strip():
                raise ManifestRefused(f"“{part[:40]}” is not a key: value pair.")
            out[k.strip()] = _value(v)
        return out
    if raw[0] in ("'", '"'):
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise ManifestRefused(f"A quoted value is not closed: {raw[:60]}")
        return raw[1:-1]
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def _strip_comment(line: str) -> str:
    """Drop a `#` comment that is not inside quotes."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i].rstrip()
    return line.rstrip()


def split_manifest(text: str) -> Tuple[str, str]:
    """`(frontmatter text, runbook)` — refused if the file has no frontmatter."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    if not text.startswith("---\n"):
        raise ManifestRefused("An AGENT.md starts with a line of three dashes, then its frontmatter.")
    end = text.find("\n---", 3)
    if end < 0:
        raise ManifestRefused("The frontmatter is never closed by a line of three dashes.")
    rest = text[end + 4:]
    if rest and not rest.startswith("\n"):
        raise ManifestRefused("The frontmatter is never closed by a line of three dashes.")
    return text[4:end], rest.strip("\n")


def parse_frontmatter(fm_text: str) -> Dict[str, Any]:
    """The frontmatter subset, as a dict. Refuses what it cannot read rather
    than guessing, because a guessed tool list is a tool list nobody wrote."""
    out: Dict[str, Any] = {}
    pending: Optional[str] = None
    for n, line in enumerate(fm_text.split("\n"), start=1):
        line = _strip_comment(line)
        if not line.strip():
            continue
        indented = line[:1].isspace()
        if not indented:
            key, sep, val = line.partition(":")
            key = key.strip()
            if not sep or not re.fullmatch(r"[a-z_][a-z0-9_]*", key):
                raise ManifestRefused(f"Line {n} of the frontmatter is not “key: value”.")
            if key in out:
                raise ManifestRefused(f"“{key}” is written twice in the frontmatter.")
            if val.strip():
                out[key] = _value(val)
                pending = None
            else:
                out[key] = None
                pending = key
            continue
        if pending is None:
            raise ManifestRefused(f"Line {n} of the frontmatter is indented under nothing.")
        body = line.strip()
        if body.startswith("- ") or body == "-":
            if out[pending] is None:
                out[pending] = []
            if not isinstance(out[pending], list):
                raise ManifestRefused(f"“{pending}” mixes list items with map entries.")
            out[pending].append(_value(body[1:]))
        else:
            k, sep, v = body.partition(":")
            if not sep or not k.strip():
                raise ManifestRefused(f"Line {n} of the frontmatter is not “key: value”.")
            if out[pending] is None:
                out[pending] = {}
            if not isinstance(out[pending], dict):
                raise ManifestRefused(f"“{pending}” mixes list items with map entries.")
            out[pending][k.strip()] = _value(v)
    return out


# ── The manifest ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    tagline: str
    section: str
    version: str
    wave: int
    starred: bool
    icon: str
    inputs: Tuple[Dict[str, Any], ...]
    triggers: Tuple[Dict[str, Any], ...]
    tools: Tuple[str, ...]
    skills: Tuple[str, ...]
    needs: Dict[str, Any]
    delivers: Tuple[Dict[str, Any], ...]
    effects: Dict[str, str]
    budget: Dict[str, int]
    memory: str
    runbook: str
    source: str = "shipped"           # shipped | own
    path: str = ""

    def section_label(self) -> str:
        return next((label for sid, label, _f in SECTIONS if sid == self.section), self.section)

    def to_public(self) -> Dict[str, Any]:
        """What the hall reads. The runbook rides along: a person hiring an
        agent may read every word the model will be told."""
        return {
            "id": self.id, "name": self.name, "tagline": self.tagline,
            "section": self.section, "section_label": self.section_label(),
            "version": self.version, "wave": self.wave, "starred": self.starred,
            "icon": self.icon,
            "inputs": [dict(i) for i in self.inputs],
            "triggers": [dict(t) for t in self.triggers],
            "tools": list(self.tools), "skills": list(self.skills),
            "needs": dict(self.needs),
            "delivers": [dict(d) for d in self.delivers],
            "effects": dict(self.effects), "budget": dict(self.budget),
            "memory": self.memory, "runbook": self.runbook, "source": self.source,
            "starts_on": describe_triggers(
                self.triggers, {i["key"]: i.get("default") for i in self.inputs}),
        }


def _known_tools() -> frozenset:
    from src.tool_policy import selectable_tool_names
    return frozenset(selectable_tool_names())


def _known_events() -> Tuple[str, ...]:
    from src.event_bus import EVENT_NAMES
    return tuple(EVENT_NAMES)


def _known_effects() -> Tuple[str, ...]:
    from src.tool_capabilities import ToolEffect
    return tuple(e.value for e in ToolEffect)


def _need(cond: bool, sentence: str) -> None:
    if not cond:
        raise ManifestRefused(sentence)


def _str(fm: Dict[str, Any], key: str, *, limit: int, required: bool = True) -> str:
    raw = fm.get(key)
    if raw is None or raw == "":
        _need(not required, f"“{key}” is missing.")
        return ""
    _need(isinstance(raw, (str, int, float)) and not isinstance(raw, bool),
          f"“{key}” is not a line of text.")
    text = str(raw).strip()
    _need(len(text) <= limit, f"“{key}” is longer than {limit} characters.")
    return text


def _list(fm: Dict[str, Any], key: str) -> list:
    raw = fm.get(key)
    if raw is None or raw == "":
        return []
    _need(isinstance(raw, list), f"“{key}” is not a list.")
    return raw


def _map(fm: Dict[str, Any], key: str) -> dict:
    raw = fm.get(key)
    if raw is None or raw == "":
        return {}
    _need(isinstance(raw, dict), f"“{key}” is not a map.")
    return raw


def _check_inputs(raw: list) -> Tuple[Dict[str, Any], ...]:
    out = []
    seen = set()
    for i, item in enumerate(raw, start=1):
        _need(isinstance(item, dict), f"Input {i} is not a map like {{key: …, kind: …, label: …}}.")
        key = str(item.get("key") or "")
        _need(bool(_KEY_RE.match(key)), f"Input {i}'s key “{key}” is not a short lower-case name.")
        _need(key not in seen, f"Two inputs are called “{key}”.")
        seen.add(key)
        kind = item.get("kind")
        _need(kind in INPUT_KINDS,
              f"Input “{key}” has kind “{kind}”, which is not one of: {', '.join(INPUT_KINDS)}.")
        label = str(item.get("label") or "").strip()
        _need(bool(label) and len(label) <= 80, f"Input “{key}” needs a label of at most 80 characters.")
        if kind == "choice":
            choices = item.get("choices")
            _need(isinstance(choices, list) and choices and all(isinstance(c, str) for c in choices),
                  f"Input “{key}” is a choice and lists no choices.")
        if kind == "time" and item.get("default") not in (None, ""):
            _need(bool(_TIME_RE.match(str(item["default"]))),
                  f"Input “{key}”'s default “{item['default']}” is not a time like 07:30.")
        extra = set(item) - {"key", "kind", "label", "optional", "default", "choices", "help"}
        _need(not extra, f"Input “{key}” has a field nothing reads: {', '.join(sorted(extra))}.")
        out.append({k: item[k] for k in item})
    return tuple(out)


def _check_triggers(raw: list, inputs: Tuple[Dict[str, Any], ...]) -> Tuple[Dict[str, Any], ...]:
    _need(bool(raw), "“triggers” is empty — say when the agent starts, even if only {on: hand}.")
    input_kinds = {i["key"]: i["kind"] for i in inputs}
    events = _known_events()
    out = []
    for i, item in enumerate(raw, start=1):
        _need(isinstance(item, dict), f"Trigger {i} is not a map like {{on: daily, at: \"08:00\"}}.")
        on = item.get("on")
        _need(on in TRIGGER_KINDS,
              f"Trigger {i} starts on “{on}”, which is not one of: {', '.join(TRIGGER_KINDS)}.")
        allowed = {"on", "label"}
        if on in ("daily", "weekly"):
            at = str(item.get("at") or "")
            ref = _INPUT_REF_RE.match(at)
            if ref:
                _need(input_kinds.get(ref.group(1)) == "time",
                      f"Trigger {i} takes its time from “{ref.group(1)}”, which is not a time input.")
            else:
                _need(bool(_TIME_RE.match(at)), f"Trigger {i}'s time “{at}” is not like 07:30.")
            allowed |= {"at"}
            if on == "daily":
                days = item.get("days", "every")
                _need(days in DAYS_SETS, f"Trigger {i}'s days “{days}” is not one of: {', '.join(DAYS_SETS)}.")
                allowed |= {"days"}
            else:
                day = item.get("day")
                _need(day in DAY_NAMES, f"Trigger {i}'s day “{day}” is not one of: {', '.join(DAY_NAMES)}.")
                allowed |= {"day"}
        elif on == "cron":
            expr = str(item.get("cron") or "")
            _need(len(expr.split()) == 5, f"Trigger {i}'s cron “{expr}” is not five fields.")
            try:
                from croniter import croniter
                croniter(expr)
            except Exception:
                raise ManifestRefused(f"Trigger {i}'s cron “{expr}” is not a schedule cron can read.")
            from src.task_scheduler import cron_floor_problem
            too_fast = cron_floor_problem(expr)
            _need(too_fast is None, f"Trigger {i}: {too_fast}")
            allowed |= {"cron"}
        elif on == "event":
            ev = item.get("event")
            _need(ev in events, f"Trigger {i} waits for “{ev}”, which is not an event Pantheon raises "
                                f"({', '.join(events)}).")
            every = item.get("every", 1)
            _need(isinstance(every, int) and 1 <= every <= 100,
                  f"Trigger {i}'s “every” is not a whole number from 1 to 100.")
            allowed |= {"event", "every"}
        extra = set(item) - allowed
        _need(not extra, f"Trigger {i} has a field nothing reads: {', '.join(sorted(extra))}.")
        out.append(dict(item))
    hands = [t for t in out if t["on"] in ("hand", "webhook")]
    _need(len(hands) <= 1, "Only one of {on: hand} and {on: webhook} — both mean “when asked”.")
    return tuple(out)


def _check_tools(raw: list) -> Tuple[str, ...]:
    _need(bool(raw), "“tools” is empty — an agent with no tools can only talk, and a chat already does that.")
    known = _known_tools()
    seen = []
    for name in raw:
        _need(isinstance(name, str) and name in known,
              f"“{name}” is not a tool Pantheon has. Tools are named as the model calls them, "
              f"e.g. web_search, list_emails, create_document.")
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def _check_effects(raw: dict) -> Dict[str, str]:
    known = _known_effects()
    out = {}
    for eff, rule in raw.items():
        _need(eff in known, f"“{eff}” is not an effect. Effects are: {', '.join(known)}.")
        _need(rule in EFFECT_RULES, f"Effect “{eff}” is “{rule}”; it can only be allow, ask or never.")
        out[eff] = rule
    return out


def _check_budget(raw: dict) -> Dict[str, int]:
    ceilings = {"runs_per_day": RUNS_PER_DAY_CEILING, "max_steps": MAX_STEPS_CEILING,
                "max_minutes": MAX_MINUTES_CEILING}
    out = {"runs_per_day": 24, "max_steps": 20, "max_minutes": 10}
    for k, v in raw.items():
        _need(k in BUDGET_KEYS, f"“budget.{k}” is not a budget. Budgets are: {', '.join(BUDGET_KEYS)}.")
        _need(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= ceilings[k],
              f"“budget.{k}” must be a whole number from 1 to {ceilings[k]}.")
        out[k] = v
    return out


def _check_delivers(raw: list) -> Tuple[Dict[str, Any], ...]:
    out = []
    for i, item in enumerate(raw, start=1):
        _need(isinstance(item, dict), f"Deliverable {i} is not a map like {{kind: answer}}.")
        kind = item.get("kind")
        _need(kind in DELIVER_KINDS,
              f"Deliverable {i} is a “{kind}”, which is not one of: {', '.join(DELIVER_KINDS)}.")
        mc = item.get("must_contain", [])
        _need(isinstance(mc, list) and all(isinstance(x, str) and x for x in mc),
              f"Deliverable {i}'s must_contain is not a list of words.")
        extra = set(item) - {"kind", "must_contain", "title", "max", "label"}
        _need(not extra, f"Deliverable {i} has a field nothing reads: {', '.join(sorted(extra))}.")
        out.append(dict(item))
    return tuple(out)


def _check_needs(raw: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {"connectors": [], "min_context": 0, "native_tools": "preferred"}
    for k, v in raw.items():
        if k == "connectors":
            _need(isinstance(v, list) and all(isinstance(x, str) and x for x in v),
                  "“needs.connectors” is not a list of names.")
            out[k] = list(v)
        elif k == "min_context":
            _need(isinstance(v, int) and 0 <= v <= 1_000_000, "“needs.min_context” is not a token count.")
            out[k] = v
        elif k == "native_tools":
            _need(v in NATIVE_TOOLS, f"“needs.native_tools” is one of: {', '.join(NATIVE_TOOLS)}.")
            out[k] = v
        else:
            raise ManifestRefused(f"“needs.{k}” is not something an agent can need.")
    return out


_FIELDS = {"id", "name", "tagline", "section", "version", "wave", "starred", "icon", "inputs",
           "triggers", "tools", "skills", "needs", "delivers", "effects", "budget", "memory"}


def lint(fm: Dict[str, Any], runbook: str, *, source: str = "shipped", path: str = "") -> Manifest:
    """The one rule. Answers a `Manifest`, or raises `ManifestRefused`."""
    extra = set(fm) - _FIELDS
    _need(not extra, f"The frontmatter has a field nothing reads: {', '.join(sorted(extra))}.")
    aid = _str(fm, "id", limit=48)
    _need(bool(_ID_RE.match(aid)), f"The id “{aid}” is not lower-case words joined by dashes.")
    name = _str(fm, "name", limit=48)
    tagline = _str(fm, "tagline", limit=140)
    section = _str(fm, "section", limit=40)
    _need(section in SECTION_IDS, f"The section “{section}” is not one of the hall's sections.")
    version = _str(fm, "version", limit=20)
    _need(bool(_VERSION_RE.match(version)), f"The version “{version}” is not like 1.0.0.")
    wave = fm.get("wave", 2)
    _need(wave in WAVES, "“wave” is 1, 2 or 3.")
    starred = fm.get("starred", False)
    _need(isinstance(starred, bool), "“starred” is true or false.")
    icon = _str(fm, "icon", limit=32, required=False)
    inputs = _check_inputs(_list(fm, "inputs"))
    triggers = _check_triggers(_list(fm, "triggers"), inputs)
    tools = _check_tools(_list(fm, "tools"))
    skills = tuple(str(s) for s in _list(fm, "skills"))
    _need(all(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", s) for s in skills),
          "“skills” names skills by their lower-case names.")
    needs = _check_needs(_map(fm, "needs"))
    delivers = _check_delivers(_list(fm, "delivers"))
    effects = _check_effects(_map(fm, "effects"))
    budget = _check_budget(_map(fm, "budget"))
    memory = fm.get("memory", "own")
    _need(memory in MEMORY_MODES, f"“memory” is one of: {', '.join(MEMORY_MODES)}.")
    if memory == "shared":
        _need("manage_memory" in tools, "“memory: shared” needs manage_memory among the tools.")
    body = (runbook or "").strip()
    _need(len(body) >= 40, "The runbook under the frontmatter is empty — it is what the model is told to do.")
    _need(len(body) <= RUNBOOK_MAX_CHARS, f"The runbook is longer than {RUNBOOK_MAX_CHARS} characters.")
    return Manifest(
        id=aid, name=name, tagline=tagline, section=section, version=version, wave=wave,
        starred=starred, icon=icon, inputs=inputs, triggers=triggers, tools=tools,
        skills=skills, needs=needs, delivers=delivers, effects=effects, budget=budget,
        memory=memory, runbook=body, source=source, path=path,
    )


def parse_manifest(text: str, *, source: str = "shipped", path: str = "") -> Manifest:
    """A file's text → a `Manifest`, or `ManifestRefused` with the sentence."""
    if len(text.encode("utf-8", "replace")) > MANIFEST_MAX_BYTES:
        raise ManifestRefused(f"The file is larger than {MANIFEST_MAX_BYTES // 1024} KiB.")
    fm_text, runbook = split_manifest(text)
    return lint(parse_frontmatter(fm_text), runbook, source=source, path=path)


# ── Words a person reads ────────────────────────────────────────────────────

_DAY_WORDS = {"mon": "Mondays", "tue": "Tuesdays", "wed": "Wednesdays", "thu": "Thursdays",
              "fri": "Fridays", "sat": "Saturdays", "sun": "Sundays"}
_EVENT_WORDS = {
    "email_received": "new mail", "document_created": "a new document",
    "document_updated": "an edited document", "session_created": "a new chat",
    "message_sent": "a message you send", "memory_added": "a new memory",
    "research_completed": "finished research", "skill_added": "a new skill",
}


def describe_trigger(t: Dict[str, Any], inputs: Optional[Dict[str, Any]] = None) -> str:
    on = t.get("on")
    at = str(t.get("at") or "")
    ref = _INPUT_REF_RE.match(at)
    if ref:
        at = str((inputs or {}).get(ref.group(1)) or "your time")
    if on == "daily":
        days = t.get("days", "every")
        return {"every": f"daily at {at}", "weekdays": f"weekdays at {at}",
                "weekends": f"weekends at {at}"}[days]
    if on == "weekly":
        return f"{_DAY_WORDS.get(t.get('day'), 'weekly')} at {at}"
    if on == "cron":
        return t.get("label") or f"on the schedule {t.get('cron')}"
    if on == "event":
        return _EVENT_WORDS.get(t.get("event"), str(t.get("event")))
    if on == "webhook":
        return "a webhook, or by hand"
    return "by hand"


def describe_triggers(triggers, inputs: Optional[Dict[str, Any]] = None) -> str:
    words = [describe_trigger(t, inputs) for t in triggers]
    if len(words) > 1 and "by hand" in words:
        words.remove("by hand")
    return "; ".join(words)
