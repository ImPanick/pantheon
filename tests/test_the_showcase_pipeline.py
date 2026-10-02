# SPDX-License-Identifier: AGPL-3.0-or-later
"""The README's pictures, and the pipeline that makes them (`scripts/showcase/`).

Three promises, each checked where it is kept:

  * **What the README shows is here, and small.** Every picture it points at
    exists under `docs/media/`, is inside the budget `media.py` states, says in
    its `alt` what it shows, and nothing sits in `docs/media/` that no page
    shows. A picture that is referenced and missing is a broken front page; one
    that is present and unreferenced is weight in every clone.
  * **The demo world is fictional.** Every string the seed writes and every
    word the scripted model says is scanned for anything shaped like a
    credential or a real address — and the scanner is shown to catch one, so a
    green run is not a scanner that finds nothing.
  * **The seed runs against the real API.** `capture.py`'s own `Server` boots
    this checkout's `app.py` on a temporary data directory, the importer's
    `install_package` files the demo package, and `seed.seed_all` makes the
    whole world through the routes — including the chats, whose tools Pantheon
    runs for real while `demo_model` plays the script. Then the world is read
    back through the API, not through the seed's own return values.

No browser: the capture itself drives Chromium for minutes and is not run here.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "scripts" / "showcase"
MEDIA_DIR = ROOT / "docs" / "media"
README = ROOT / "README.md"
sys.path.insert(0, str(SHOWCASE))

import demo_model  # noqa: E402
import media  # noqa: E402
import seed  # noqa: E402


# ── what the README shows ───────────────────────────────────────────────────

_TAG = re.compile(r"<(img|source)\b[^>]*>", re.I | re.S)
_ATTR = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"', re.S)
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)")


def _pictures(text: str):
    """`[(kind, path, alt)]` for every picture in a Markdown/HTML page."""
    out = []
    for m in _TAG.finditer(text):
        attrs = dict((k.lower(), v) for k, v in _ATTR.findall(m.group(0)))
        if m.group(1).lower() == "img":
            out.append(("img", attrs.get("src", ""), attrs.get("alt")))
        else:
            for part in attrs.get("srcset", "").split(","):
                if part.strip():
                    out.append(("source", part.strip().split()[0], None))
    for alt, path in _MD_IMAGE.findall(text):
        out.append(("md", path, alt))
    return out


def _local_media(text: str):
    return [p for _, p, _ in _pictures(text) if p.startswith("docs/media/")]


def test_the_readme_shows_the_showcase():
    """The ask: pictures near the top. The hero sits before the first section."""
    text = README.read_text(encoding="utf-8")
    first_section = text.index("\n## ")
    head = text[:first_section]
    assert _local_media(head), "no showcase picture before the first section of the README"
    assert len(set(_local_media(text))) >= 10


def test_every_picture_the_readme_shows_is_here_and_within_budget():
    text = README.read_text(encoding="utf-8")
    shown = _local_media(text)
    assert shown
    for rel in shown:
        path = ROOT / rel
        assert path.is_file(), f"README shows {rel}, which does not exist"
        budget = {".png": media.PNG_BUDGET, ".gif": media.GIF_BUDGET}.get(path.suffix)
        assert budget, f"{rel}: only PNG and GIF are budgeted"
        assert path.stat().st_size <= budget, (
            f"{rel} is {path.stat().st_size} bytes, over its {budget}-byte budget")


def test_every_picture_says_what_it_shows():
    for kind, path, alt in _pictures(README.read_text(encoding="utf-8")):
        if path.startswith("docs/media/") and kind in ("img", "md"):
            assert alt and len(alt.strip()) >= 12, f"{path} has no useful alt text: {alt!r}"


def test_the_showcase_points_only_at_files_in_this_repository():
    """Relative paths into `docs/media/` — never an absolute or a URL — so the
    pictures render on any fork and in an offline clone."""
    for _, path, _ in _pictures(README.read_text(encoding="utf-8")):
        if "docs/media" in path:
            assert path.startswith("docs/media/"), f"not a relative path: {path}"


def test_docs_media_holds_only_what_a_page_shows_and_fits_its_budget():
    shown = set(_local_media(README.read_text(encoding="utf-8")))
    on_disk = {f"docs/media/{p.name}" for p in MEDIA_DIR.iterdir()
               if p.suffix in (".png", ".gif")}
    assert on_disk, "docs/media is empty"
    assert on_disk - shown == set(), f"in docs/media and shown nowhere: {sorted(on_disk - shown)}"
    total = sum(p.stat().st_size for p in MEDIA_DIR.iterdir() if p.is_file())
    assert total <= media.TOTAL_BUDGET, f"docs/media is {total} bytes, over {media.TOTAL_BUDGET}"


def test_every_shown_picture_is_one_the_pipeline_makes():
    """No hand-made picture slips in beside the generated ones: each file is a
    scene's output, so regenerating replaces all of it."""
    import scenes

    made = set()
    for sc in scenes.SCENES:
        base = sc.name[:-4] if sc.name.endswith("-gif") else sc.name
        if sc.kind == "png":
            made |= {f"{base}-{t}.png" for t in scenes.THEMES}
        elif sc.kind == "phone":
            made.add(f"{base}.png")
        else:
            made.add(f"{base}.gif")
    for rel in set(_local_media(README.read_text(encoding="utf-8"))):
        assert Path(rel).name in made, f"{rel} is not made by any scene in scripts/showcase/scenes.py"


# ── the demo world is fictional ─────────────────────────────────────────────

_SECRET_SHAPES = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "GitHub token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_\w{20,}"),
    "AWS key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}"),
    "Pantheon API token": re.compile(r"\bpan_[A-Za-z0-9]{16,}"),
    "long secret-like run": re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40,}(?![0-9a-fA-F])"
                                       r"|[A-Za-z0-9+/_-]{48,}={0,2}"),
    "password assignment": re.compile(r"(?i)\b(pass(word)?|secret|api[_-]?key|token)\s*[:=]\s*\S{6,}"),
}
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_URL = re.compile(r"\bhttps?://([^/\s\"'<>)]+)")
_RESERVED_DOMAINS = ("example.com", "example.org", "example.net")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _strings(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _strings(k, out)
            _strings(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            _strings(v, out)
    return out


def _demo_world():
    """Every string the seed writes and the script says (the `args` a step
    computes at run time are built from these plus ids and dates)."""
    data = [getattr(seed, name) for name in (
        "PERSON", "FOLDERS", "DOCUMENTS", "TASKS", "CHAINS", "SKILLS", "PACKAGE", "GROUP",
        "NOTES", "EVENTS", "MEMORIES")]
    data.append([{k: v for k, v in step.items() if not callable(v)}
                 for conv in demo_model.CONVERSATIONS for turn in conv["turns"]
                 for step in turn["steps"]])
    data.append([(c["title"], [t["user"] for t in c["turns"]]) for c in demo_model.CONVERSATIONS])
    data.append(demo_model.BRAMBLEWICK_PAGE)
    return _strings(data)


def _findings(strings):
    found = []
    for s in strings:
        for what, rx in _SECRET_SHAPES.items():
            if rx.search(s):
                found.append((what, s[:80]))
        for domain in _EMAIL.findall(s):
            if domain.lower() not in _RESERVED_DOMAINS:
                found.append(("address outside example.com", s[:80]))
        for host in _URL.findall(s):
            if host.split(":")[0] not in ("127.0.0.1", "localhost") and not host.startswith("[::1]"):
                found.append(("URL off this machine", s[:80]))
    return found


def test_the_demo_world_holds_nothing_shaped_like_a_secret_or_a_real_address():
    strings = _demo_world()
    assert len(strings) > 200, "the scan read too little to mean anything"
    assert _findings(strings) == []


def test_the_scan_is_not_vacuous():
    planted = [
        "my key is sk-" + "a1B2" * 6,
        "ghp_" + "A" * 36,
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "token = s3cr3t-value",
        "write to someone@realcompany.io",
        "see https://tracker.example-vendor.net/x",
        "pan_" + "Z" * 20,
        "0123456789abcdef" * 3,
    ]
    assert len(_findings(planted)) >= len(planted)
    assert _findings(["mira@example.com", "http://127.0.0.1:7000/v1"]) == []


def test_the_pipeline_source_carries_no_credential():
    """File-wide absence is the right question here (`Law 20`): no literal
    credential anywhere in the four scripts — the password is made per run."""
    for path in SHOWCASE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for what, rx in _SECRET_SHAPES.items():
            if what in ("long secret-like run", "password assignment"):
                continue
            assert not rx.search(text), f"{path.name}: {what}"
    assert "token_urlsafe" in (SHOWCASE / "capture.py").read_text(encoding="utf-8")


# ── the throwaway server inherits nothing real ──────────────────────────────

def test_the_throwaway_server_inherits_nothing_that_points_at_real_data(monkeypatch, tmp_path):
    """`app.py` reads this checkout's `.env` for any key the environment leaves
    unset, so the capture sets every address, key and token `.env.example`
    names — blank — and points the database at the throwaway directory. A
    developer's real database, models, keys and workstation never reach it."""
    import capture

    for key, value in {"DATABASE_URL": "postgresql://real-db/pantheon", "OPENAI_API_KEY": "real",
                       "LLM_HOST": "192.0.2.7", "PANTHEON_WORKSTATION_URL": "https://ws.lan:7040",
                       "PANTHEON_WORKSTATION_TOKEN": "real", "CHROMADB_HOST": "chroma.lan",
                       "SOME_UNRELATED_SETTING": "x"}.items():
        monkeypatch.setenv(key, value)
    env = capture.Server(sys.executable, tmp_path / "data", 7999).environment()
    assert env["DATABASE_URL"] == "sqlite:///" + (tmp_path / "data" / "app.db").as_posix()
    assert env["PANTHEON_DATA_DIR"] == str(tmp_path / "data")
    for key in ("OPENAI_API_KEY", "LLM_HOST", "PANTHEON_WORKSTATION_URL", "PANTHEON_WORKSTATION_TOKEN"):
        assert env[key] == "", key
    assert env["CHROMADB_HOST"] == "127.0.0.1"
    assert "SOME_UNRELATED_SETTING" not in env
    assert env["AUTH_ENABLED"] == "true" and env["APP_BIND"] == "127.0.0.1"
    # Derived from `.env.example`, so a new provider key is covered the day it is documented.
    assert {"OPENAI_API_KEY", "TAVILY_API_KEY", "PANTHEON_GITHUB_TOKEN"} <= set(capture.pointer_keys())


# ── the seed, against the real API ──────────────────────────────────────────

@pytest.fixture(scope="module")
def pantheon(tmp_path_factory):
    import capture

    work = tmp_path_factory.mktemp("showcase")
    data = work / "data"
    data.mkdir()
    subprocess.run([sys.executable, str(SHOWCASE / "offline_package.py"), "--data-dir", str(data),
                    "--owner", seed.PERSON["username"]], check=True, cwd=ROOT,
                   capture_output=True, timeout=120)
    server = capture.Server(sys.executable, data, capture._free_port(),
                            extra_env={"PANTHEON_DISABLE_MCP": "1"})
    try:
        server.start(timeout=150)
    except RuntimeError as e:
        server.stop()
        log = server.log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
        pytest.fail(f"{e}\n{log}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def seeded(pantheon):
    import httpx

    client = httpx.Client(base_url=pantheon.base, timeout=180)
    seed.setup_admin(client, secrets.token_urlsafe(18))
    today = dt.date.today()
    with demo_model.DemoModel() as model:
        report = seed.seed_all(client, model_base_url=model.base_url, today=today)
        yield client, report, today
    client.close()


def test_the_folders_and_documents_arrive_with_their_names(seeded):
    client, report, _ = seeded
    paths = {f["path"] for f in client.get("/api/document-folders").json()["folders"]}
    assert set(seed.FOLDERS) <= paths
    docs = client.get("/api/documents/library", params={"limit": 50}).json()
    rows = docs.get("documents") or docs.get("items") or []
    by_title = {d["title"]: d for d in rows}
    assert {t for _, t, _, _ in seed.DOCUMENTS} <= set(by_title)
    assert by_title["launch-checklist.md"]["folder"] == "Projects/Lumen 2.0"
    assert by_title["survey-results.csv"]["folder"] == "Projects/Lumen 2.0/Research"
    # The filing chat's agent moved the first three loose ones; the GIF's two stay loose.
    assert by_title["meeting-notes-2026-09-28.md"]["folder"] == "Projects/Lumen 2.0"
    assert by_title["Quillfeather kickoff agenda.md"]["folder"] == "Clients/Quillfeather Cycles"
    assert by_title["ideas-for-2.1.txt"]["folder"] == "Projects/Lumen 2.0/Research"
    assert not by_title["invoice-0143.csv"].get("folder")


def test_the_chain_has_both_branches_and_was_planned(seeded):
    client, report, _ = seeded
    ids = report["tasks"]
    tasks = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert tasks[ids["metrics"]]["then_task_id"] == ids["report"]
    assert tasks[ids["metrics"]]["else_task_id"] == ids["alert"]
    assert tasks[ids["report"]]["then_task_id"] == ids["share"]
    assert tasks[ids["backup"]]["else_task_id"] == ids["backup_alert"]
    plan = client.post(f"/api/tasks/{ids['metrics']}/run", params={"dry": "true", "chain": "true"}).json()
    assert [s["task_id"] for s in plan["chain"]][:1] == [ids["metrics"]]
    assert {s["task_id"] for s in plan["chain"]} == {ids[k] for k in ("metrics", "report", "share", "alert")}


def test_the_workflow_is_one_document_on_the_shelf_and_switched_on(seeded):
    """The Workbench's shelf shows a workflow (`P22-05`): the seed makes one
    through the workflow routes — two steps joined *if it works*, its start
    every day at 08:00, switched on."""
    client, report, _ = seeded
    (name, wf_id), = report["workflows"].items()
    listed = {w["id"]: w for w in client.get("/api/workflows").json()["workflows"]}
    assert listed[wf_id]["name"] == name == seed.WORKFLOW["name"]
    doc = client.get(f"/api/workflows/{wf_id}").json()["workflow"]
    assert [n["label"] for n in doc["graph"]["nodes"]] == [s[1] for s in seed.WORKFLOW["steps"]]
    assert doc["graph"]["edges"] == [{"from": "n1", "port": "success", "to": "n2"}]
    start = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}[doc["task_id"]]
    assert (start["task_type"], start["status"], start["schedule"], start["scheduled_time"]) == (
        "workflow", "active", "daily", "08:00")


def test_the_skills_package_and_group_are_there(seeded):
    client, _, _ = seeded
    col = client.get("/api/skills/collections").json()
    pkg = next(p for p in col["packages"] if p["id"] == "tidewater-demo--field-guides")
    assert set(pkg["skills"]) == {name for _, name, _, _ in seed.PACKAGE["skills"]}
    group = next(g for g in col["groups"] if g["title"] == seed.GROUP["title"])
    assert set(group["skills"]) == set(seed.GROUP["skills"])
    names = {s.get("name") for s in client.get("/api/skills").json().get("skills", [])}
    assert {s["name"] for s in seed.SKILLS} <= names


def test_notes_calendar_and_memories_are_there(seeded):
    client, _, today = seeded
    notes = client.get("/api/notes").json()
    titles = {n["title"] for n in (notes.get("notes") if isinstance(notes, dict) else notes)}
    assert {n["title"] for n in seed.NOTES} <= titles
    monday = demo_model.demo_monday(today)
    events = client.get("/api/calendar/events", params={
        "start": monday.isoformat() + "T00:00:00",
        "end": (monday + dt.timedelta(days=7)).isoformat() + "T00:00:00"}).json()
    rows = events.get("events") if isinstance(events, dict) else events
    summaries = {e["summary"] for e in rows}
    assert {e[3] for e in seed.EVENTS} <= summaries
    assert "Launch review prep" in summaries, "the agent's booking from the hero chat is missing"
    texts = {m["text"] for m in client.get("/api/memory").json()["memory"]}
    assert {t for t, _ in seed.MEMORIES} <= texts


def test_each_chat_holds_a_real_agent_turn(seeded):
    client, report, _ = seeded
    chats = {c["key"]: c["session_id"] for c in report["chats"]}
    assert set(chats) == {c["key"] for c in demo_model.CONVERSATIONS if not c.get("needs")}
    for conv in demo_model.CONVERSATIONS:
        if conv.get("needs"):
            continue
        msgs = client.get(f"/api/history/{chats[conv['key']]}").json()["history"]
        said = " ".join(str(m.get("content", "")) for m in msgs if m.get("role") == "assistant")
        assert demo_model.OFF_SCRIPT not in said
        final = conv["turns"][-1]["steps"][-1]["say"]
        assert re.sub(r"[*`|]", "", final.split("\n")[0])[:30].strip() in re.sub(r"[*`|]", "", said)
        assert any(m.get("role") == "user" and conv["turns"][0]["user"] in str(m.get("content", ""))
                   for m in msgs)


def test_a_chat_that_leaves_the_script_is_refused(seeded):
    """The seed's guard: a picture of the stand-in saying it has no script
    must never be captured. A question the script does not hold gets that
    sentence back, and the seed refuses the chat."""
    client, report, _ = seeded
    with pytest.raises(seed.SeedError, match="off its script"):
        seed.send_chat(client, report["model"]["endpoint_id"], None,
                       "Write me a limerick about sourdough starters, please.")


def test_a_plain_conversation_answers_the_workbenchs_plain_requests_and_side_requests_stay_ok():
    """`integrate-e` (`B1133`). The drafter and *Why did this
    fail?* ask one plain request — not streamed, no tools — and the stand-in
    answered every such request "OK", so neither could be scripted. A
    conversation marked `plain` now answers its own plain requests with the
    step's `say` (a dict as JSON), the repair round with the next step; every
    other plain request is still a side request."""
    import json as _json
    import urllib.request

    draft = {"name": "Bank mail to chat", "steps": [], "arrows": []}
    script = [{"key": "plain-draft", "plain": True, "title": "Draft",
               "turns": [{"user": "when mail arrives from my bank",
                          "steps": [{"say": draft}, {"say": "a repaired draft"}]}]}]

    def ask(model, messages, **extra):
        req = urllib.request.Request(model.base_url + "/chat/completions", method="POST",
                                     data=_json.dumps({"model": demo_model.MODEL_ID,
                                                       "messages": messages, **extra}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            return _json.loads(res.read())["choices"][0]["message"]["content"]

    log = []
    with demo_model.DemoModel(conversations=script, log=log) as model:
        first = [{"role": "system", "content": "Answer with one JSON object."},
                 {"role": "user", "content": "What the person wants:\nwhen mail arrives from my bank, post it"}]
        assert _json.loads(ask(model, first)) == draft
        again = first + [{"role": "assistant", "content": "{}"},
                         {"role": "user", "content": "That draft was refused. Answer again."}]
        assert ask(model, again) == "a repaired draft"
        side = [{"role": "system", "content": "You are a memory extraction assistant."},
                {"role": "user", "content": "Something else entirely."}]
        assert ask(model, side) == "[]"
        assert ask(model, [{"role": "user", "content": "Not in any script."}]) == "OK"
    assert [entry.get("plain", False) for entry in log] == [True, True, False, False]
