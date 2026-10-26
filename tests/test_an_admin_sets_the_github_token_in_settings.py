# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B927` — the skill importer's GitHub token has a panel, and the panel works.

A token lifts skill imports from GitHub's 60 lookups an hour to 5,000, and
until this row only `data/settings.json` or `PANTHEON_GITHUB_TOKEN` could set
one; the importer's own sentence told a person to set an environment variable.

Driven, not read (`Law 20`):

  * the real app, booted with two accounts (`tests/helpers/gated_app.py`): the
    admin saves a token through `POST /api/auth/settings`, the state route says
    it is set and never says what it is, a member and a stranger are refused,
    a value that could not travel in a header is refused, and the importer then
    *uses* it — an import that a token-less server is rate-limited on lists the
    whole folder;
  * the panel module (`static/js/githubToken.js`) under node: hidden for a
    viewer the route refuses, never filled from the server, saves what was
    typed and clears the box, and Remove sends the empty value.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.gated_app import gated_app_probe

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "ghp_B927abcdefghijklmnopqrstuvwxyz0123"

_PROBE = r'''
from services.memory import skill_importer as si
from services.memory.skill_importer import SkillImportError

TOKEN = %(token)r
os.environ.pop("PANTHEON_GITHUB_TOKEN", None)
admin, member, stranger = client(ADMIN), client(MEMBER), client(None)

RESULT["before"] = admin.get("/api/skills/github-token").json()
RESULT["member_get"] = member.get("/api/skills/github-token").status_code
RESULT["stranger_get"] = stranger.get("/api/skills/github-token").status_code
RESULT["member_post"] = member.post("/api/auth/settings", json={"github_token": TOKEN}).status_code

bad = admin.post("/api/auth/settings", json={"github_token": "ghp_two words"})
RESULT["bad"] = [bad.status_code, bad.json().get("detail")]
RESULT["after_bad"] = admin.get("/api/skills/github-token").json()["configured"]

saved = admin.post("/api/auth/settings", json={"github_token": "  " + TOKEN + "\n"})
RESULT["saved"] = saved.status_code
state = admin.get("/api/skills/github-token")
RESULT["state"] = state.json()
RESULT["state_carries_token"] = TOKEN in state.text
RESULT["credential"] = si._github_credentials()

# The next import: a GitHub that rate-limits the API for a server with no token
# and answers one with a token, asked through the importer's own fetch seam.
SKILL = "---\nname: pdf\ndescription: Read PDFs.\n---\nUse it.\n"
listing = [{"name": n, "type": "file", "size": 10,
            "download_url": "https://raw.githubusercontent.com/o/r/main/skills/pdf/" + n}
           for n in ("SKILL.md", "forms.md", "reference.md")]

class _Resp:
    def __init__(self, url, payload=None, body=b""):
        self.url, self.status_code, self.headers = url, 200, {}
        self._payload = payload
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode()
    def json(self):
        return self._payload
    def raise_for_status(self):
        pass

def _github(url, *, headers=None, timeout=30.0, **kw):
    if url.startswith("https://api.github.com/"):
        if not si._github_credentials():
            raise SkillImportError("api.github.com has rate-limited us; not retrying for 22 minutes.")
        return _Resp(url, payload=listing)
    return _Resp(url, body=SKILL if url.endswith("SKILL.md") else "text")

si._get_checked = _github
files, _, notes = si.fetch_skill_bundle_report("https://github.com/o/r/tree/main/skills/pdf")
RESULT["imported"] = sorted(files)
RESULT["notes"] = notes

removed = admin.post("/api/auth/settings", json={"github_token": ""})
RESULT["removed"] = [removed.status_code, admin.get("/api/skills/github-token").json()]
os.environ["PANTHEON_GITHUB_TOKEN"] = "ghp_fromenv"
RESULT["env"] = admin.get("/api/skills/github-token").json()
''' % {"token": TOKEN}


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    return gated_app_probe(tmp_path_factory.mktemp("b927"), _PROBE)


def test_the_premise_holds(probe):
    assert probe["premise"]["auth_enabled"] and probe["premise"]["admin_is_admin"]
    assert not probe["premise"]["member_is_admin"]


def test_an_admin_sees_whether_one_is_set_and_never_what_it_is(probe):
    assert probe["before"]["configured"] is False and probe["before"]["source"] == ""
    assert probe["before"]["rate_without"] == 60 and probe["before"]["rate_with"] == 5000
    assert probe["saved"] == 200
    assert probe["state"]["configured"] is True and probe["state"]["source"] == "settings"
    assert probe["state_carries_token"] is False


def test_only_an_admin_may_ask_or_set(probe):
    assert probe["member_get"] == 403
    assert probe["stranger_get"] == 401
    assert probe["member_post"] == 403


def test_a_value_that_could_not_travel_in_a_header_is_refused_in_words(probe):
    status, detail = probe["bad"]
    assert status == 400 and "not a GitHub token" in detail
    assert probe["after_bad"] is False


def test_the_saved_token_is_the_one_the_importer_sends(probe):
    assert probe["credential"] == TOKEN   # stripped of the pasted whitespace


def test_the_next_import_lists_the_whole_folder(probe):
    """The row's `Verify:`. Without a token this fake GitHub rate-limits the
    listing and the import keeps SKILL.md alone, with a note."""
    assert probe["imported"] == ["skills/pdf/SKILL.md", "skills/pdf/forms.md", "skills/pdf/reference.md"]
    assert probe["notes"] == []


def test_remove_clears_it_and_the_environment_is_said_as_the_source(probe):
    status, state = probe["removed"]
    assert status == 200 and state["configured"] is False
    assert probe["env"]["configured"] is True and probe["env"]["source"] == "environment"
    assert probe["env"]["env_var"] == "PANTHEON_GITHUB_TOKEN"


# ── the panel ───────────────────────────────────────────────────────────────

def _drive_panel(tmp_path, *, state_status=200, state=None, then=""):
    if not shutil.which("node"):
        pytest.skip("node binary not on PATH")
    from test_tool_effect_surfaces_js import _DOM

    (tmp_path / "dom.js").write_text(_DOM)
    shutil.copy(ROOT / "static" / "js" / "githubToken.js", tmp_path / "githubToken.js")
    state = state or {"configured": False, "source": "", "env_var": "PANTHEON_GITHUB_TOKEN",
                      "rate_without": 60, "rate_with": 5000}
    case = """
import { installDom } from './dom.js';
const document = installDom();
const seen = { posts: [] };
let state = %(state)s;
globalThis.fetch = async (url, init = {}) => {
  if (url === '/api/skills/github-token') {
    return { ok: %(ok)s, status: %(status)d, json: async () => state };
  }
  const body = JSON.parse(init.body);
  seen.posts.push(body);
  if (body.github_token) state = { ...state, configured: true, source: 'settings' };
  else state = { ...state, configured: false, source: '' };
  return { ok: true, status: 200, json: async () => ({}) };
};
const mk = (tag, id) => { const n = document.body.appendChild(document.createElement(tag)); n.setAttribute('id', id); return n; };
const card = mk('div', 'github-token-card'); card.hidden = true;
mk('div', 'github-token-rate');
const input = mk('input', 'github-token-input');
mk('button', 'github-token-save');
const remove = mk('button', 'github-token-remove'); remove.hidden = true;
const out = mk('div', 'github-token-state');
const panel = await import('./githubToken.js');
await panel.mount();
seen.afterMount = { hidden: card.hidden, input: input.value, said: out.textContent, removeHidden: remove.hidden };
%(then)s
console.log(JSON.stringify({ ...seen, hidden: card.hidden, input: input.value,
  said: out.textContent, removeHidden: remove.hidden }));
""" % {"state": json.dumps(state), "ok": "true" if state_status < 400 else "false",
       "status": state_status, "then": then}
    (tmp_path / "case.mjs").write_text(case)
    out = subprocess.run(["node", str(tmp_path / "case.mjs")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_a_viewer_the_route_refuses_never_sees_the_card(tmp_path):
    out = _drive_panel(tmp_path, state_status=403)
    assert out["afterMount"]["hidden"] is True


def test_the_card_says_the_rate_a_token_buys_and_is_never_filled(tmp_path):
    out = _drive_panel(tmp_path, state={"configured": True, "source": "settings",
                                        "env_var": "PANTHEON_GITHUB_TOKEN",
                                        "rate_without": 60, "rate_with": 5000})
    after = out["afterMount"]
    assert after["hidden"] is False and after["input"] == ""
    assert "5,000 lookups an hour" in after["said"]
    assert after["removeHidden"] is False


def test_save_sends_what_was_typed_and_clears_the_box(tmp_path):
    out = _drive_panel(tmp_path, then=f"""
input.value = '  {TOKEN}  ';
await panel.save();
""")
    assert out["posts"] == [{"github_token": TOKEN}]
    assert out["input"] == ""
    assert "A token is saved" in out["said"] and out["removeHidden"] is False


def test_an_empty_box_leaves_the_saved_token_alone(tmp_path):
    out = _drive_panel(tmp_path, then="await panel.save();")
    assert out["posts"] == []
    assert "Paste a token first" in out["said"]


def test_remove_sends_the_empty_value(tmp_path):
    out = _drive_panel(tmp_path, then="""
input.value = 'ghp_x'; await panel.save(); await panel.remove();
""")
    assert out["posts"] == [{"github_token": "ghp_x"}, {"github_token": ""}]
    assert "No token" in out["said"] and out["removeHidden"] is True
