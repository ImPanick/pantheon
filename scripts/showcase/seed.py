# SPDX-License-Identifier: AGPL-3.0-or-later
"""The showcase's demo world, and the calls that put it into a fresh Pantheon.

Everything here is **fictional**: the person (Rowan Hale), the studio, its two
clients, every document, task, skill, note, event and memory. Addresses use the
reserved `example.com` domain (RFC 2606). There is no API key, token or real
credential anywhere in this file — the account password is made up per run by
`capture.py` — and `tests/test_the_showcase_pipeline.py` scans every string
below for anything shaped like one.

**Through the real API wherever one exists.** Each `seed_*` function takes an
`httpx.Client` already pointed at a Pantheon (a live server in `capture.py`, a
`TestClient` in the test — the same interface) and makes the requests a person's
browser would. The one exception is the imported skill package: the import route
fetches from GitHub, which a capture must never do (`Law 16`), so
`install_demo_package` hands a package to `SkillsManager.install_package` — the
function the import route calls once its fetch is done — on the data directory,
before the server starts. That is the only write that does not go through a
route, and it is the importer's own code doing it.

Dates are relative to the day the capture runs (this week's calendar, this
week's tasks), so a regenerated screenshot is never a picture of last year.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Dict, Iterable, List, Optional

import demo_model  # sibling module; capture.py and the test put this folder on sys.path

PERSON = {"username": "rowan", "display": "Rowan Hale"}

# The scripted model the chats run on — see `demo_model.py`. Named for what it
# is, because it shows in the model picker and a screenshot must not pass a
# script off as a model.
DEMO_MODEL_ID = "scripted-demo"
DEMO_ENDPOINT_NAME = "Demo model (scripted)"


class SeedError(RuntimeError):
    """A seeding request was refused. Carries what the server said."""


def _ok(resp, what: str) -> Any:
    if resp.status_code >= 400:
        raise SeedError(f"{what}: HTTP {resp.status_code} {resp.text[:400]}")
    try:
        return resp.json()
    except ValueError:
        return resp.text


# ── the account ──────────────────────────────────────────────────────────────

def setup_admin(client, password: str, username: str = PERSON["username"]) -> None:
    """First-run setup, then sign in — the cookie stays on `client`."""
    _ok(client.post("/api/auth/setup", json={"username": username, "password": password}),
        "first-run setup")
    _ok(client.post("/api/auth/login",
                    json={"username": username, "password": password, "remember": True}),
        "sign in")


# ── documents, in folders (P21) ──────────────────────────────────────────────

FOLDERS = [
    "Clients/Bramblewick Bakery",
    "Clients/Quillfeather Cycles",
    "Projects/Lumen 2.0",
    "Projects/Lumen 2.0/Research",
    "Finance/2026",
    "Personal",
]

LAUNCH_CHECKLIST = """# Lumen 2.0 — launch checklist

Ship date: **Friday**. Owner: Rowan.

## Before Wednesday's review
- [x] Freeze the feature list
- [x] Final copy for the onboarding screens
- [ ] Release notes reviewed by Jun
- [ ] Pricing page — annual plan toggle
- [ ] Accessibility pass on the new timeline view

## Launch day
- [ ] Publish the release notes
- [ ] Send the customer email (draft in *Projects/Lumen 2.0*)
- [ ] Watch the error dashboard for two hours
- [ ] Thank-you note to the beta group

## Risks
| Risk | Likelihood | Plan |
|---|---|---|
| Sync migration slow on large libraries | Medium | Batch it; show progress |
| App-store review delay | Low | Submitted Monday |
| Support spike | Medium | Two extra people on Friday |
"""

RELEASE_NOTES = """# Lumen 2.0 release notes (draft)

## What's new
- **Timeline view** — every habit on one scrolling line, with streaks you can tap.
- **Shared spaces** — invite a partner or a team; each person keeps their own reminders.
- **Quiet hours** — reminders wait until the morning, on every device.

## Better
- Sync is about three times faster on libraries over 10,000 entries.
- The widget follows your light or dark setting.

## Fixed
- A reminder set for 00:30 no longer fires a day early.
- Exported CSVs keep their accents.
"""

ROADMAP = """# Q4 roadmap

| Month | Theme | Headline |
|---|---|---|
| October | Launch | Lumen 2.0, shared spaces |
| November | Listen | Interviews, the 2.1 shortlist |
| December | Polish | Performance, accessibility, the widget |

**Not this quarter:** a web app, Android tablets, integrations.
"""

INTERVIEWS = """# Interview notes — September

Eight conversations, 30 minutes each.

1. *"I stopped because the reminders came at the wrong time."* — five of eight said something like it.
2. People keep two or three habits, not ten. The empty state should suggest fewer.
3. Shared spaces were the most requested feature — mostly couples, two small teams.

**Next:** quiet hours ship in 2.0; test a three-habit starter set in 2.1.
"""

SURVEY = """question,agree,neutral,disagree
Reminders arrive at a useful time,41,22,37
I would share a space with someone,58,25,17
The timeline is easy to read,66,21,13
I would pay for an annual plan,47,30,23
"""

PROPOSAL = """# Spring menu site — proposal

**For:** Bramblewick Bakery · **From:** Tidewater Studio · **Status:** sent, awaiting reply

## The brief
A one-page site the bakery can update itself each season: the menu, opening hours,
and a pre-order form for celebration cakes.

## What we will make
1. A menu page that reads well on a phone held in one hand.
2. A pre-order form with a pickup-time picker and allergy notes.
3. A short guide so the team can change prices and photos without us.

## Timeline and fee
Three weeks from sign-off. Fixed fee, half on sign-off and half on launch.
"""

BRAND_NOTES = """# Bramblewick — brand notes

- Warm, plain, a little playful. Never "artisanal".
- Colours: oat, rye brown, a jam red for buttons.
- Photos: daylight only, flour on the bench is fine.
- Contact: Mira Okafor, mira@example.com
"""

QUOTE = """# Quillfeather Cycles — quote 0142

| Item | Days | Amount |
|---|---|---|
| Fitting-booking flow (design) | 4 | 2,400 |
| Prototype and two test rounds | 3 | 1,800 |
| Hand-off to their developer | 1 | 600 |
| **Total** | **8** | **4,800** |

Valid for 30 days.
"""

BOOKING_FLOW = """<h1>Fitting booking — flow</h1>
<ol>
  <li>Pick a bike type (road, gravel, city)</li>
  <li>Pick a fitter and a 90-minute slot</li>
  <li>Height, inseam and any injuries</li>
  <li>Confirm — a reminder the day before</li>
</ol>
"""

BUDGET = """month,income,studio,software,travel
July,9200,3100,420,180
August,8700,3100,440,0
September,11400,3100,460,620
October,10800,3100,460,240
"""

INVOICE = """item,qty,unit,amount
Discovery workshop,1,1200,1200
Design days,6,600,3600
Prototype hosting,1,40,40
"""

MEETING = """# Team sync — 28 September

**Present:** Rowan, Jun, Priya

- Launch moves to Friday; the store review cleared early.
- Jun owns the release notes; Priya takes the accessibility pass.
- Bramblewick wants the pre-order form before Easter.

**Actions**
- [ ] Rowan — book the launch review for Wednesday
- [ ] Jun — first draft of the release notes by Tuesday
- [ ] Priya — screen-reader run on the timeline
"""

IDEAS = """Ideas for 2.1
- a three-habit starter set
- streak freeze, one per month
- a calmer sound for quiet-hours reminders
"""

AGENDA = """# Quillfeather kickoff — agenda

1. Introductions (5 min)
2. What a good fitting feels like — their words (15 min)
3. Today's booking: phone, email, walk-in (10 min)
4. What success looks like in three months (10 min)
5. Next steps
"""

INVOICE_0143 = """item,qty,unit,amount
Menu photography,1,450,450
Pre-order form build,2,600,1200
"""

PACKING = """Lisbon — packing
- passports, chargers
- the small camera
- walking shoes
"""

TRIP = """# Lisbon, November

- Flights booked; seats 14A / 14B
- Two nights in Alfama, one in Cascais
- Pack the small camera
"""

# (folder, title, language, content) — titles are ordinary file names, the way
# a person names the files they import (`P21-03`).
DOCUMENTS = [
    ("Projects/Lumen 2.0", "launch-checklist.md", "markdown", LAUNCH_CHECKLIST),
    ("Projects/Lumen 2.0", "release-notes-v2.0.md", "markdown", RELEASE_NOTES),
    ("Projects/Lumen 2.0", "Q4 roadmap.md", "markdown", ROADMAP),
    ("Projects/Lumen 2.0/Research", "interview-notes-september.md", "markdown", INTERVIEWS),
    ("Projects/Lumen 2.0/Research", "survey-results.csv", "csv", SURVEY),
    ("Clients/Bramblewick Bakery", "Spring menu site - proposal.docx", "markdown", PROPOSAL),
    ("Clients/Bramblewick Bakery", "brand-notes.md", "markdown", BRAND_NOTES),
    ("Clients/Quillfeather Cycles", "quote-0142.md", "markdown", QUOTE),
    ("Clients/Quillfeather Cycles", "fitting-booking-flow.html", "html", BOOKING_FLOW),
    ("Finance/2026", "budget-2026.csv", "csv", BUDGET),
    ("Finance/2026", "invoice-0142.csv", "csv", INVOICE),
    ("Personal", "lisbon-trip.md", "markdown", TRIP),
    # Unfiled — the agent files the first three in a chat; the filing GIF drags the last two.
    ("", "meeting-notes-2026-09-28.md", "markdown", MEETING),
    ("", "Quillfeather kickoff agenda.md", "markdown", AGENDA),
    ("", "ideas-for-2.1.txt", "text", IDEAS),
    ("", "invoice-0143.csv", "csv", INVOICE_0143),
    ("", "packing-list.txt", "text", PACKING),
]


def seed_documents(client) -> Dict[str, str]:
    """Folders first (an empty one stays, `P21-01`), then each document in its
    folder through the create route, which files it on the way in (`B997`).
    Returns `{title: id}`."""
    for path in FOLDERS:
        _ok(client.post("/api/document-folders", json={"folder": path}), f"folder {path}")
    ids: Dict[str, str] = {}
    for folder, title, language, content in DOCUMENTS:
        body = {"title": title, "language": language, "content": content,
                "source_name": title}
        if folder:
            body["folder"] = folder
        out = _ok(client.post("/api/document", json=body), f"document {title}")
        ids[title] = out.get("id") or (out.get("document") or {}).get("id")
    return ids


# ── automations: a chain with a failure branch, and a dry run (P22) ──────────

# (key, fields). `then`/`else` name other keys and are wired after creation,
# with the same PUT the Workbench's drag sends.
TASKS = [
    ("metrics", {"name": "Collect weekly metrics",
                 "prompt": "Pull last week's sign-ups, active users and churn from the dashboard export and list them.",
                 "schedule": "weekly", "scheduled_day": 0, "scheduled_time": "08:00",
                 "max_retries": 2, "timeout_seconds": 600}),
    ("report", {"name": "Draft the weekly report",
                "prompt": "Turn the metrics into a short report: three numbers, one chart, one sentence on each."}),
    ("share", {"name": "Share the report",
               "prompt": "Post the report to the team's weekly chat and pin it."}),
    ("alert", {"name": "Tell me the metrics run failed",
               "prompt": "Tell me which step failed and why, in one line."}),
    ("briefing", {"name": "Morning briefing",
                  "prompt": "Summarise today's calendar, anything due and the notes I pinned.",
                  "schedule": "daily", "scheduled_time": "07:30"}),
    ("backup", {"name": "Back up my notes",
                "prompt": "Export my notes to the backups folder.",
                "schedule": "daily", "scheduled_time": "02:00"}),
    ("backup_alert", {"name": "Message me about the backup",
                      "prompt": "Say the backup failed and when it last worked."}),
    ("tidy", {"name": "Tidy documents", "task_type": "action", "action": "tidy_documents",
              "schedule": "weekly", "scheduled_day": 6, "scheduled_time": "18:00"}),
]

CHAINS = [("metrics", "then", "report"), ("report", "then", "share"),
          ("metrics", "else", "alert"), ("backup", "else", "backup_alert")]

# The head the dry run plans, end to end (`P22-04`).
DRY_RUN_HEAD = "metrics"


def seed_tasks(client, *, model: Optional[str] = None,
               endpoint_url: Optional[str] = None) -> Dict[str, str]:
    """Create the automations, wire the chains, plan the chain once.

    A step with no schedule is reached only through its chain, so it is made
    with a webhook trigger — the shape the Workbench's own *New step* gives a
    step that nothing schedules. Returns `{key: id}`."""
    ids: Dict[str, str] = {}
    for key, fields in TASKS:
        body = {"task_type": "llm", "output_target": "session", **fields}
        if "schedule" not in fields:
            body["trigger_type"] = "webhook"
        if body["task_type"] == "llm" and model:
            body["model"] = model
            if endpoint_url:
                body["endpoint_url"] = endpoint_url
        out = _ok(client.post("/api/tasks", json=body), f"task {fields['name']}")
        ids[key] = str(out.get("id") or (out.get("task") or {}).get("id"))
    for src, when, dst in CHAINS:
        field = "then_task_id" if when == "then" else "else_task_id"
        _ok(client.put(f"/api/tasks/{ids[src]}", json={field: ids[dst]}),
            f"chain {src} {when} {dst}")
    plan = _ok(client.post(f"/api/tasks/{ids[DRY_RUN_HEAD]}/run",
                           params={"dry": "true", "chain": "true"}), "chain dry run")
    if len(plan.get("chain") or []) < 3:
        raise SeedError(f"the dry run planned {len(plan.get('chain') or [])} steps, expected 4")
    return ids


# ── skills: the person's own, an imported package, and a group ─────────────

SKILLS = [
    {"name": "release-notes-writer", "category": "writing",
     "description": "Turn a changelog into release notes people actually read.",
     "when_to_use": "When a version is about to ship and there is a changelog or a list of merged changes.",
     "procedure": ["Group changes into New, Better and Fixed.",
                   "Lead each line with what the person can now do.",
                   "Cut anything only the team would care about."],
     "pitfalls": ["Ticket numbers in user-facing text."],
     "verification": ["Every line starts with a verb or a feature name."],
     "tags": ["writing", "release"], "status": "active"},
    {"name": "meeting-summary", "category": "writing",
     "description": "Decisions, owners and dates from a meeting's notes.",
     "when_to_use": "After a meeting, when someone pastes notes or a transcript.",
     "procedure": ["List decisions first.", "Then actions as owner — task — date.",
                   "Keep open questions separate."],
     "tags": ["meetings"], "status": "active"},
    {"name": "support-triage", "category": "support",
     "description": "Sort incoming support mail into fix-now, reply, and later.",
     "when_to_use": "When the support inbox has more than a handful of new messages.",
     "procedure": ["Read the subject and first paragraph.", "Tag by product area.",
                   "Draft a reply for anything answerable from the docs."],
     "tags": ["email", "support"], "status": "draft"},
    {"name": "sprint-planner", "category": "planning",
     "description": "A two-week plan from a backlog and who is available.",
     "when_to_use": "At the start of a sprint, given a backlog and the team's days off.",
     "procedure": ["Estimate in days, not points.", "Fill each person to 70%.",
                   "Name the one thing that must ship."],
     "tags": ["planning"], "status": "active"},
    {"name": "invoice-check", "category": "finance",
     "description": "Check an invoice CSV against the quote it came from.",
     "when_to_use": "Before sending an invoice to a client.",
     "procedure": ["Match each line to the quote.", "Flag any day over the estimate.",
                   "Total it twice."],
     "tags": ["finance"], "status": "active"},
]

# The imported package — fictional, installed offline (see the module docstring).
PACKAGE = {
    "owner": "tidewater-demo", "repo": "field-guides", "title": "Field guides",
    "description": "Writing and research habits from a small design studio.",
    "version": "1.2.0",
    "sections": [
        {"id": "writing", "title": "Writing", "folders": ["writing/plain-language", "writing/headline-polish"]},
        {"id": "research", "title": "Research", "folders": ["research/interview-synthesis"]},
    ],
    "skills": [
        ("writing/plain-language", "plain-language",
         "Rewrite a paragraph so a busy reader gets it on the first pass.",
         ["Find the one sentence that matters and move it first.",
          "Swap every abstract noun for the verb inside it.",
          "Read it aloud; cut what you skip."]),
        ("writing/headline-polish", "headline-polish",
         "Five headline options in different registers, then pick one.",
         ["Write five: plain, curious, numeric, outcome, question.",
          "Strike any that promise more than the piece delivers."]),
        ("research/interview-synthesis", "interview-synthesis",
         "Patterns across interview notes, with quotes that back each one.",
         ["Pull every quote onto its own line.", "Cluster by what the person wanted, not by topic.",
          "Name each cluster in the interviewee's words."]),
    ],
}

GROUP = {"title": "Launch week",
         "skills": ["release-notes-writer", "sprint-planner", "headline-polish"]}


def _package_skill_md(name: str, description: str, steps: List[str]) -> str:
    lines = ["---", f"name: {name}", f"description: {description}", "---", "",
             f"# {name}", "", "## Procedure"]
    lines += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    return "\n".join(lines) + "\n"


def demo_package():
    """The fictional package as the importer's own `FetchedPackage`."""
    from services.memory.skill_importer import (
        FetchedPackage, PackageSection, PackageSkill, ResolvedSource)

    src = ResolvedSource(owner=PACKAGE["owner"], repo=PACKAGE["repo"], ref="main", path="")
    section_of = {f: s["id"] for s in PACKAGE["sections"] for f in s["folders"]}
    skills = [PackageSkill(folder=folder, name=name,
                           files={"SKILL.md": _package_skill_md(name, desc, steps)},
                           section=section_of[folder])
              for folder, name, desc, steps in PACKAGE["skills"]]
    sections = [PackageSection(id=s["id"], title=s["title"], folders=list(s["folders"]))
                for s in PACKAGE["sections"]]
    return FetchedPackage(src=src, title=PACKAGE["title"], description=PACKAGE["description"],
                          version=PACKAGE["version"], commit="0" * 40, skills=skills,
                          sections=sections)


def install_demo_package(data_dir: str, owner: str = PERSON["username"]) -> Dict:
    """Install the package with the importer's `install_package`, on `data_dir`.

    Run in the server's interpreter before the server starts (`capture.py`
    spawns `offline_package.py` for it), or in-process by the test."""
    from services.memory.skills import SkillsManager

    return SkillsManager(data_dir).install_package(demo_package(), owner=owner)


def seed_skills(client) -> Dict[str, Any]:
    """The person's own skills, then a group that reaches across them and the
    package (`P8-50`: a group lists skills by reference)."""
    made = []
    for sk in SKILLS:
        out = _ok(client.post("/api/skills/add", json={**sk, "source": "user"}),
                  f"skill {sk['name']}")
        made.append((out.get("skill") or {}).get("name") or sk["name"])
    group = _ok(client.post("/api/skills/groups", json=GROUP), "skill group")
    return {"skills": made, "group": (group.get("group") or {}).get("id")}


# ── notes, calendar, memories ───────────────────────────────────────────────

NOTES = [
    {"title": "Launch week", "note_type": "checklist", "pinned": True, "color": "yellow",
     "items": [{"text": "Release notes reviewed", "done": True},
               {"text": "Pricing page toggle", "done": False},
               {"text": "Customer email scheduled", "done": False},
               {"text": "Thank the beta group", "done": False}]},
    {"title": "Ideas for 2.1", "note_type": "note", "color": "blue", "label": "lumen",
     "content": "Three-habit starter set. Streak freeze, one a month. A softer sound for quiet hours."},
    {"title": "Quillfeather call", "note_type": "note", "color": "green", "label": "clients",
     "content": "They book fittings by phone today. Wants deposits taken online. Ask about their calendar tool."},
    {"title": "Weekend", "note_type": "checklist", "color": "pink",
     "items": [{"text": "Market — sourdough, figs", "done": False},
               {"text": "Call Mum", "done": True},
               {"text": "Bike service", "done": False}]},
]


def seed_notes(client) -> int:
    for note in NOTES:
        _ok(client.post("/api/notes", json=note), f"note {note['title']}")
    return len(NOTES)


# (weekday 0=Mon, start "HH:MM" or None for all-day, minutes, summary, location)
EVENTS = [
    (0, "09:30", 30, "Team stand-up", "Studio"),
    (1, "14:00", 60, "Bramblewick menu review", "Bramblewick Bakery"),
    (2, "10:00", 60, "Lumen 2.0 launch review", "Studio"),
    (2, "16:30", 45, "Dentist", "High Street"),
    (3, "13:00", 90, "Quillfeather fitting-flow workshop", "Quillfeather Cycles"),
    (4, None, 0, "Lumen 2.0 ships", ""),
    (4, "17:30", 90, "Launch drinks", "The Anchor"),
]


def seed_calendar(client, today: Optional[_dt.date] = None) -> int:
    monday = demo_model.demo_monday(today or _dt.date.today())
    for day, start, minutes, summary, location in EVENTS:
        date = monday + _dt.timedelta(days=day)
        if start is None:
            body = {"summary": summary, "dtstart": date.isoformat(), "all_day": True}
        else:
            hh, mm = (int(x) for x in start.split(":"))
            begin = _dt.datetime.combine(date, _dt.time(hh, mm))
            body = {"summary": summary, "dtstart": begin.isoformat(),
                    "dtend": (begin + _dt.timedelta(minutes=minutes)).isoformat()}
        if location:
            body["location"] = location
        _ok(client.post("/api/calendar/events", json=body), f"event {summary}")
    return len(EVENTS)


MEMORIES = [
    ("Rowan prefers short summaries: bullets first, detail after.", "preference"),
    ("Lumen 2.0 ships this Friday; the launch review is on Wednesday.", "project"),
    ("Jun writes the release notes; Priya owns the accessibility pass.", "project"),
    ("Bramblewick Bakery's contact is Mira Okafor (mira@example.com).", "contact"),
    ("The weekly report goes out on Monday mornings.", "fact"),
    ("Rowan runs Tidewater Studio, a two-person design studio.", "identity"),
    ("Quillfeather Cycles wants to take fitting deposits online.", "project"),
]


def seed_memories(client) -> int:
    for text, category in MEMORIES:
        _ok(client.post("/api/memory/add", json={"text": text, "category": category,
                                                 "source": "user"}), "memory")
    return len(MEMORIES)


# ── the scripted model, and the chats that run on it ────────────────────────

def register_demo_model(client, base_url: str) -> Dict[str, str]:
    """Add the scripted model as an ordinary OpenAI-compatible endpoint."""
    out = _ok(client.post("/api/model-endpoints",
                          data={"name": DEMO_ENDPOINT_NAME, "base_url": base_url,
                                "supports_tools": "true", "require_models": "true"}),
              "model endpoint")
    if DEMO_MODEL_ID not in (out.get("models") or []):
        raise SeedError(f"the demo endpoint listed {out.get('models')!r}, not {DEMO_MODEL_ID}")
    return {"endpoint_id": out["id"], "chat_url": base_url.rstrip("/") + "/chat/completions"}


def _sse_events(text: str) -> Iterable[Dict[str, Any]]:
    for line in text.splitlines():
        if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
            try:
                yield json.loads(line[6:])
            except ValueError:
                continue


def send_chat(client, endpoint_id: str, session_id: Optional[str], message: str,
              mode: str = "agent", allow_bash: bool = False,
              max_approvals: int = 6) -> Dict[str, Any]:
    """One turn through `/api/chat_stream`, as the composer sends it.

    Once a turn has read something it did not write — a recalled memory, a
    document's text — the agent asks before its next private read or write
    (the approval card). The person's answer is a second request carrying the
    card's id, which is what clicking **Allow for this task** sends; the seed
    answers each card that way, so the chat shows the cards it really asked.
    """
    if session_id is None:
        sess = _ok(client.post("/api/session", data={"endpoint_id": endpoint_id,
                                                     "model": DEMO_MODEL_ID}), "new chat")
        session_id = sess.get("session_id") or sess.get("id")
    form = {"message": message, "session": session_id, "mode": mode, "plan_mode": "false",
            "selected_model": DEMO_MODEL_ID, "selected_endpoint_id": endpoint_id,
            "allow_bash": "true" if allow_bash else "false", "allow_web_search": "false"}
    tools: List[str] = []
    approvals = 0
    while True:
        resp = client.post("/api/chat_stream", data=form)
        _ok(resp, "chat turn")
        events = list(_sse_events(resp.text))
        tools += [e.get("tool") for e in events
                  if e.get("type") == "tool_output" and e.get("status") != "pending_approval"
                  and "Waiting for an exact user approval" not in str(e.get("output"))]
        errors = [e for e in events if e.get("type") == "error"]
        if errors:
            raise SeedError(f"chat turn errored: {errors[:2]!r}")
        cards = [e["data"] for e in events if e.get("type") == "ask_user"
                 and (e.get("data") or {}).get("kind") == "tool_approval"]
        if not cards:
            break
        approvals += 1
        if approvals > max_approvals:
            raise SeedError(f"more than {max_approvals} approval cards in one turn")
        form = {**form, "message": "", "tool_approval_id": cards[-1]["approval_id"],
                "tool_approval_decision": "approve_task"}
    if not any(e.get("type") == "message_saved" for e in events):
        raise SeedError("chat turn ended without saving a reply")
    said = "".join(str(e.get("delta") or "") for e in events if not e.get("thinking"))
    if demo_model.OFF_SCRIPT in said:
        raise SeedError(f"the scripted model went off its script in {message[:60]!r}")
    return {"session_id": session_id, "tools": tools, "approvals": approvals}


def seed_chats(client, endpoint_id: str, have: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """The chats in `demo_model.CONVERSATIONS`, oldest first, so the hero —
    the last one — is at the top of the sidebar. A conversation that `needs`
    something (the workstation) is played only when `have` names it."""
    made = []
    for conv in demo_model.CONVERSATIONS:
        if conv.get("needs") and conv["needs"] not in set(have):
            continue
        sid = None
        for turn in conv["turns"]:
            out = send_chat(client, endpoint_id, sid, turn["user"], mode=turn.get("mode", "agent"),
                            allow_bash=bool(turn.get("allow_bash")))
            sid = out["session_id"]
            missing = [t for t in turn.get("expect_tools", []) if t not in out["tools"]]
            if missing:
                raise SeedError(f"chat {conv['key']!r} never called {missing} (called {out['tools']})")
        made.append({"key": conv["key"], "session_id": sid})
    return made


def counts(report: Dict[str, Any]) -> Dict[str, int]:
    """How much of each thing a `seed_all` report made, for the log line."""
    return {"documents": len(report.get("documents", {})), "automations": len(report.get("tasks", {})),
            "skills": len((report.get("skills") or {}).get("skills", [])), "notes": report.get("notes", 0),
            "events": report.get("events", 0), "memories": report.get("memories", 0),
            "chats": len(report.get("chats", []))}


def seed_all(client, *, model_base_url: Optional[str] = None,
             today: Optional[_dt.date] = None, have: Iterable[str] = ()) -> Dict[str, Any]:
    """Everything except the account and the package. Returns what was made."""
    report: Dict[str, Any] = {}
    model = None
    if model_base_url:
        model = register_demo_model(client, model_base_url)
        report["model"] = model
    report["documents"] = seed_documents(client)
    report["tasks"] = seed_tasks(client, model=DEMO_MODEL_ID if model else None,
                                 endpoint_url=model["chat_url"] if model else None)
    report["skills"] = seed_skills(client)
    report["notes"] = seed_notes(client)
    report["events"] = seed_calendar(client, today)
    report["memories"] = seed_memories(client)
    if model:
        report["chats"] = seed_chats(client, model["endpoint_id"], have)
    return report
