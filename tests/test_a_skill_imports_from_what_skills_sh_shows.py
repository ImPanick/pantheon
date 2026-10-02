# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B926`. A skill imports from what a person actually has in hand.

The owner, 2026-09-30: *"I tried to import a skills by pasting a github link in
the 'import url' - and it didnt do anything. No success, no progress, and very
seldom a failure message."* And: *"I was trying to import skills from
https://skills.sh - although I'm not entirely what to paste from there.. Is it
the full npx line? or just the github url...?"* And: *"I got an error adding
https://github.com/vercel-labs/agent-browser - said 'File too large'"*.

Pinned here, by driving the importer against a fake GitHub:

  * **every form skills.sh shows is accepted** — the page link, the
    `npx skills add <repo> --skill <name>` line (with or without the trailing
    backslash a copy picks up), `owner/repo@skill`, and a bare repository that
    is one skill named after itself;
  * **a skill named, not located, is found** in the usual folders, on `main`
    or `master`, and through one tree request when it is anywhere else;
  * **a listing GitHub refuses does not sink the import** — SKILL.md is kept
    and the person is told what was left out and why;
  * **one big file does not sink it either** — it is left out by name, and a
    dependency lockfile is never fetched;
  * **the files land beside SKILL.md**, and a renamed import says so;
  * **the route does not stop the server** while GitHub is being paced.
"""

import asyncio
import json
import time
import types

import httpx
import pytest
from fastapi import FastAPI

import services.memory.skill_importer as si
from services.memory.skill_importer import SkillImportError, parse_skill_source
from services.memory.skills import SkillsManager

SKILL_MD = "---\nname: {name}\ndescription: Does {name} things.\n---\n\n# {name}\n\nSee forms.md.\n"


class _Resp:
    def __init__(self, url, status=200, body=b"", payload=None):
        self.url = url
        self.status_code = status
        self.content = body if isinstance(body, bytes) else str(body).encode()
        self._payload = payload
        self.headers = {}
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        if self._payload is not None:
            return self._payload
        return json.loads(self.text or "null")


class _FakeGitHub:
    """Answers `_get_checked` from a table; records what was asked."""

    def __init__(self, raw=None, api=None, api_limited=False):
        self.raw = dict(raw or {})        # "owner/repo/ref/path" -> text
        self.api = dict(api or {})        # full api URL -> payload
        self.api_limited = api_limited
        self.asked = []

    def __call__(self, url, *, headers=None, timeout=30.0):
        self.asked.append(url)
        if url.startswith("https://api.github.com/"):
            if self.api_limited:
                raise SkillImportError(
                    "api.github.com has rate-limited us; not retrying for 22 minutes. "
                    "(API rate limit exceeded for 1.2.3.4.)")
            if url in self.api:
                return _Resp(url, payload=self.api[url])
            return _Resp(url, status=404, body=b'{"message": "Not Found"}')
        prefix = "https://raw.githubusercontent.com/"
        if url.startswith(prefix):
            key = url[len(prefix):]
            if key in self.raw:
                return _Resp(url, body=self.raw[key])
            return _Resp(url, status=404, body=b"404: Not Found")
        return _Resp(url, status=404)


@pytest.fixture
def github(monkeypatch):
    def install(**kw):
        fake = _FakeGitHub(**kw)
        monkeypatch.setattr(si, "_get_checked", fake)
        return fake
    return install


def _contents(owner, repo, path, ref, entries):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    return url, [
        {"name": n, "type": "file", "size": size,
         "download_url": f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}/{n}"}
        for n, size in entries
    ]


# ── what can be pasted ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text,owner,repo,skill", [
    ("npx skills add https://github.com/anthropics/skills --skill frontend-design",
     "anthropics", "skills", "frontend-design"),
    ("npx skills add https://github.com/anthropics/skills --skill frontend-design\\",
     "anthropics", "skills", "frontend-design"),
    ("  npx skills add vercel-labs/agent-skills --skill react-best-practices -g -y ",
     "vercel-labs", "agent-skills", "react-best-practices"),
    ("npx skills add anthropics/skills@pdf", "anthropics", "skills", "pdf"),
    ("npx skills add --agent claude-code anthropics/skills --skill=xlsx",
     "anthropics", "skills", "xlsx"),
    ("https://skills.sh/anthropics/skills/frontend-design", "anthropics", "skills", "frontend-design"),
    ("https://www.skills.sh/mattpocock/skills/grill-me", "mattpocock", "skills", "grill-me"),
    ("skills.sh/vercel-labs/agent-browser/agent-browser", "vercel-labs", "agent-browser", "agent-browser"),
])
def test_every_form_skills_sh_shows_names_the_skill(text, owner, repo, skill):
    src = parse_skill_source(text)
    assert (src.owner, src.repo, src.skill, src.path) == (owner, repo, skill, "")
    assert src.ref_known is False


def test_a_skills_sh_page_that_is_not_a_skill_says_what_to_paste():
    with pytest.raises(SkillImportError, match="npx skills add"):
        parse_skill_source("https://skills.sh/")


def test_the_github_forms_that_already_worked_still_do():
    src = parse_skill_source("https://github.com/anthropics/skills/tree/main/skills/pdf")
    assert (src.path, src.ref, src.ref_known, src.skill) == ("skills/pdf", "main", True, "")
    bare = parse_skill_source("https://github.com/vercel-labs/agent-browser")
    assert (bare.path, bare.ref_known) == ("", False)


def test_a_name_that_is_not_a_name_is_refused_before_anything_is_fetched(github):
    fake = github()
    with pytest.raises(SkillImportError):
        si.fetch_skill_bundle_report("npx skills add anthropics/skills --skill ../../etc")
    assert fake.asked == []


# ── finding a named skill ───────────────────────────────────────────────────

def test_a_named_skill_is_found_in_the_usual_folder(github):
    github(raw={"anthropics/skills/main/skills/frontend-design/SKILL.md": SKILL_MD.format(name="frontend-design")},
           api_limited=True)
    files, src, notes = si.fetch_skill_bundle_report(
        "npx skills add https://github.com/anthropics/skills --skill frontend-design")
    assert list(files) == ["skills/frontend-design/SKILL.md"]
    assert src.path == "skills/frontend-design"


def test_master_is_tried_when_main_has_nothing(github):
    github(raw={"o/r/master/r-skill/SKILL.md": SKILL_MD.format(name="r-skill")}, api_limited=True)
    files, src, _ = si.fetch_skill_bundle_report("https://skills.sh/o/r/r-skill")
    assert src.ref == "master" and "r-skill/SKILL.md" in files


def test_a_skill_anywhere_else_is_found_with_one_tree_request(github):
    tree_url = "https://api.github.com/repos/mattpocock/skills/git/trees/main?recursive=1"
    fake = github(
        raw={"mattpocock/skills/main/skills/engineering/grill-me/SKILL.md": SKILL_MD.format(name="grill-me")},
        api={tree_url: {"tree": [
            {"type": "blob", "path": "README.md"},
            {"type": "blob", "path": "skills/engineering/grill-me/SKILL.md"},
            {"type": "blob", "path": "skills/engineering/other/SKILL.md"},
        ]}},
    )
    files, src, _ = si.fetch_skill_bundle_report("https://skills.sh/mattpocock/skills/grill-me")
    assert src.path == "skills/engineering/grill-me"
    assert "skills/engineering/grill-me/SKILL.md" in files
    assert fake.asked.count(tree_url) == 1


def test_a_missing_skill_says_so_and_what_to_do(github):
    github(api={"https://api.github.com/repos/o/r/git/trees/main?recursive=1": {"tree": []}})
    with pytest.raises(SkillImportError, match="Couldn't find a skill called “nope” in o/r"):
        si.fetch_skill_bundle_report("npx skills add o/r --skill nope")


def test_a_rate_limited_search_is_said_in_words_not_githubs(github):
    github(api_limited=True)
    with pytest.raises(SkillImportError) as e:
        si.fetch_skill_bundle_report("https://skills.sh/o/r/hidden-skill")
    assert "rate-limited this server for 22 minutes" in str(e.value)
    assert "PANTHEON_GITHUB_TOKEN" in str(e.value)


def test_a_bare_repository_that_is_one_skill_imports(github):
    # vercel-labs/agent-browser keeps skills/agent-browser/SKILL.md.
    github(raw={"vercel-labs/agent-browser/main/skills/agent-browser/SKILL.md": SKILL_MD.format(name="agent-browser")},
           api_limited=True)
    files, src, _ = si.fetch_skill_bundle_report("https://github.com/vercel-labs/agent-browser")
    assert src.path == "skills/agent-browser"


def test_a_repository_of_many_skills_is_not_walked(github):
    fake = github(raw={}, api={})
    with pytest.raises(SkillImportError, match="whole repository, not one skill"):
        si.fetch_skill_bundle_report("https://github.com/anthropics/skills")
    assert not any("/contents/" in u for u in fake.asked)


# ── what comes back ─────────────────────────────────────────────────────────

def test_a_refused_listing_keeps_skill_md_and_says_why(github):
    github(raw={"anthropics/skills/main/skills/pdf/SKILL.md": SKILL_MD.format(name="pdf")}, api_limited=True)
    files, _, notes = si.fetch_skill_bundle_report("https://github.com/anthropics/skills/tree/main/skills/pdf")
    assert list(files) == ["skills/pdf/SKILL.md"]
    assert len(notes) == 1 and notes[0].startswith("Only SKILL.md was imported")
    assert "resets in 22 minutes" in notes[0] and "PANTHEON_GITHUB_TOKEN" in notes[0]


def test_one_big_file_is_left_out_by_name_and_a_lockfile_is_never_fetched(github):
    url, entries = _contents("vercel-labs", "agent-browser", "skills/agent-browser", "main", [
        ("SKILL.md", 400), ("forms.md", 100), ("huge.json", si.MAX_FILE_BYTES + 1),
        ("package-lock.json", 900),
    ])
    base = "vercel-labs/agent-browser/main/skills/agent-browser"
    fake = github(raw={f"{base}/SKILL.md": SKILL_MD.format(name="agent-browser"),
                       f"{base}/forms.md": "forms", f"{base}/package-lock.json": "{}"},
                  api={url: entries})
    files, _, notes = si.fetch_skill_bundle_report("https://github.com/vercel-labs/agent-browser")
    assert set(files) == {"skills/agent-browser/SKILL.md", "skills/agent-browser/forms.md"}
    assert any("huge.json" in n and "limit for one file" in n for n in notes), notes
    assert any("package-lock.json" in n and "lockfile" in n for n in notes), notes
    assert not any(u.endswith("package-lock.json") or u.endswith("huge.json") for u in fake.asked)


def test_the_limits_are_the_raised_ones():
    """The owner asked for them raised (2026-09-30); they stay caps."""
    assert si.MAX_FILE_BYTES >= 2_000_000
    assert si.MAX_TOTAL_BYTES >= 10_000_000
    assert si.MAX_FILES >= 256


def test_files_land_beside_skill_md_and_a_rename_is_said(tmp_path):
    sm = SkillsManager(str(tmp_path), library_root="")
    files = {"skills/pdf/SKILL.md": SKILL_MD.format(name="pdf"), "skills/pdf/forms.md": "forms"}
    first = sm.import_bundle_from_files(dict(files), source_url="https://example.test/pdf")
    assert "_renamed_from" not in first
    folder = tmp_path / "skills" / "imported" / "pdf"
    assert (folder / "forms.md").read_text() == "forms"
    assert not (folder / "skills").exists()
    second = sm.import_bundle_from_files(dict(files))
    assert second["name"] == "pdf-2" and second["_renamed_from"] == "pdf"


# ── the route ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_server_keeps_answering_while_an_import_is_paced(tmp_path, monkeypatch):
    """`fetch_skill_bundle_report` sleeps between GitHub requests. It ran on the
    event loop, so every other request waited for the whole import."""
    import routes.skills_routes as routes

    monkeypatch.setattr(routes, "require_admin", lambda request: None)

    def slow_fetch(url):
        time.sleep(1.0)
        # `P8-49`: the source comes back as the real fetch returns it, because
        # the route now files the skill under the package it came from.
        return ({"SKILL.md": SKILL_MD.format(name="slow")},
                si.ResolvedSource(owner="o", repo="r", ref="main", path="slow"), ["a note"])

    monkeypatch.setattr(si, "fetch_skill_bundle_report", slow_fetch)
    app = FastAPI()
    app.include_router(routes.setup_skills_routes(SkillsManager(str(tmp_path), library_root="")))

    @app.get("/ping")
    async def ping():
        return {"t": time.monotonic()}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        started = time.monotonic()
        imp = asyncio.create_task(client.post("/api/skills/import-from-url",
                                              json={"url": "https://github.com/o/r/tree/main/slow"}))
        await asyncio.sleep(0.2)
        pong = await client.get("/ping")
        answered_at = pong.json()["t"]
        res = await imp
    assert answered_at - started < 0.9, "the ping waited for the import"
    body = res.json()
    assert res.status_code == 200 and body["skill"]["name"] == "slow"
    assert body["notes"] == ["a note"]


@pytest.mark.asyncio
async def test_an_unexpected_failure_says_what_failed(tmp_path, monkeypatch):
    import routes.skills_routes as routes

    monkeypatch.setattr(routes, "require_admin", lambda request: None)

    def broken(url):
        raise KeyError("frontmatter")

    monkeypatch.setattr(si, "fetch_skill_bundle_report", broken)
    app = FastAPI()
    app.include_router(routes.setup_skills_routes(SkillsManager(str(tmp_path), library_root="")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        res = await client.post("/api/skills/import-from-url", json={"url": "https://github.com/o/r/tree/main/x"})
    assert res.status_code == 500
    assert res.json()["detail"].startswith("Skill import failed — KeyError")


# ── the browser ─────────────────────────────────────────────────────────────
# `importSkillFromUrl` and its status line, cut out of the real `skills.js` and
# run under node against the DOM shim, with `fetch` answered by the test.

import shutil as _shutil
from pathlib import Path as _Path

from test_tool_effect_surfaces_js import _DOM
from tests.helpers.js_source import js_definition

_SKILLS_JS = _Path(__file__).resolve().parents[1] / "static" / "js" / "skills.js"


def _cut(name: str) -> str:
    src = _SKILLS_JS.read_text(encoding="utf-8")
    for opener in (f"async function {name}(", f"function {name}(", f"let {name} ="):
        at = src.find(opener)
        if at >= 0:
            return js_definition(src, at)
    raise AssertionError(f"{name} is not in skills.js")


def _drive_import(tmp_path, answer: dict, *, status: int = 200, url: str = "npx skills add o/r --skill s",
                  after: str = "") -> dict:
    if not _shutil.which("node"):
        pytest.skip("node binary not on PATH")
    import subprocess
    (tmp_path / "dom.js").write_text(_DOM)
    case = """
import { installDom } from './dom.js';
const document = installDom();
// The browser has it; the shim does not.
if (!Node.prototype.removeAttribute) Node.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
const API = '';
const seen = { toasts: [], errors: [], opened: [], loads: 0, posts: 0, busyWhilePending: null, statusWhilePending: null };
const uiModule = { showToast: (m) => seen.toasts.push(m), showError: (m) => seen.errors.push(m) };
async function loadSkills() { seen.loads += 1; }
function openSkill(n) { seen.opened.push(n); }
let release;
globalThis.fetch = async (u, init) => {
  seen.posts += 1;
  seen.busyWhilePending = document.getElementById('skill-import-url-btn').disabled;
  seen.statusWhilePending = document.getElementById('skill-import-status').textContent;
  await new Promise((r) => { release = r; setTimeout(r, 30); });
  return { ok: %(ok)s, status: %(status)d, json: async () => (%(answer)s) };
};
const input = document.body.appendChild(document.createElement('input'));
input.setAttribute('id', 'skill-import-url'); input.value = %(url)s;
const btn = document.body.appendChild(document.createElement('button'));
btn.setAttribute('id', 'skill-import-url-btn'); btn.innerHTML = '<svg></svg>Import';
const statusEl = document.body.appendChild(document.createElement('p'));
statusEl.setAttribute('id', 'skill-import-status'); statusEl.hidden = true;
%(defs)s
// `P22-21`. The import reaches its box, button and line through a mount — the
// window's, made by the shipped `_makeMount`, whose ids are the page's own.
const m = _makeMount(document.body);
const first = importSkillFromUrl(m);
const second = importSkillFromUrl(m);   // Enter pressed again while it runs
await first; await second;
%(after)s
console.log(JSON.stringify({ ...seen,
  status: statusEl.textContent, statusClass: statusEl.className, statusHidden: statusEl.hidden,
  btnDisabled: btn.disabled, btnHtml: btn.innerHTML,
  openButton: statusEl.querySelectorAll('.skill-import-open').length }));
""" % {
        "ok": "true" if status < 400 else "false",
        "status": status,
        "answer": json.dumps(answer),
        "url": json.dumps(url),
        "defs": "const _SCOPE_KEY = 'skillsScope';\n" + "\n".join(
            _cut(n) for n in ("_readScope", "_makeMount", "_importStatus", "_importInFlight",
                              "importSkillFromUrl")),
        "after": after,
    }
    (tmp_path / "case.mjs").write_text(case)
    out = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_while_it_runs_the_button_and_the_line_say_so(tmp_path):
    out = _drive_import(tmp_path, {"ok": True, "skill": {"name": "s"}, "files": 1, "notes": []})
    assert out["busyWhilePending"] is True
    assert out["statusWhilePending"].startswith("Downloading from GitHub…")


def test_a_second_press_while_it_runs_starts_nothing(tmp_path):
    out = _drive_import(tmp_path, {"ok": True, "skill": {"name": "s"}, "files": 1, "notes": []})
    assert out["posts"] == 1


def test_success_is_said_beside_the_box_with_what_was_left_out(tmp_path):
    out = _drive_import(tmp_path, {"ok": True, "skill": {"name": "frontend-design"}, "files": 1,
                                   "notes": ["Only SKILL.md was imported: GitHub allows 60 …"]})
    assert out["status"].startswith("Imported frontend-design — 1 file.")
    assert "Only SKILL.md was imported" in out["status"]
    assert "is-warn" in out["statusClass"] and out["statusHidden"] is False
    assert out["openButton"] == 1 and out["opened"] == ["frontend-design"]
    assert out["toasts"] == ["Imported frontend-design (1 file)"] and out["loads"] == 1
    assert out["btnDisabled"] is False and out["btnHtml"] == "<svg></svg>Import"


def test_a_failure_is_said_beside_the_box_too(tmp_path):
    out = _drive_import(tmp_path, {"detail": "Couldn't find a skill called “s” in o/r."}, status=400)
    assert out["status"] == "Import failed: Couldn't find a skill called “s” in o/r."
    assert "is-error" in out["statusClass"]
    assert out["errors"] == ["Import failed: Couldn't find a skill called “s” in o/r."]
    assert out["btnDisabled"] is False


def test_what_github_says_reaches_the_line_as_text(tmp_path):
    out = _drive_import(tmp_path, {"detail": '<img src=x onerror="alert(1)">'}, status=400,
                        after="seen.markup = statusEl._html;")
    assert '<img src=x onerror="alert(1)">' in out["status"]
    assert not out.get("markup")
