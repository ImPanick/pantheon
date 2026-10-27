# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1256` — offline, the four loaders do not log a network failure as an error.

After `B1245` an offline reload shows one line and no toast, and the console
still said `Failed to load skills` (`skills.js`), `Failed to fetch notes`
(`notes.js`), `Calendar: failed to fetch events` (`calendar.js`) and
`Failed to check TTS availability` (`tts-ai.js`) at error level on every
offline load. Each loader now tells a request that never reached Pantheon from
one that came back wrong, through the one pair beside `B1245`'s line in
`presets.js` (`markUnreached`, `quietIfUnreached`): the first warns once per
loader per page, the second is still an error.

Driven under node: `skills.js` whole, in the Workshop sandbox; the other three
loaders' own function bodies cut out of the shipped files (`js_function`) and
called with the real `presets.js` helpers, because their modules' import chains
cannot be loaded in isolation (`Law 20`, option 2 — scope first, then call).

`Verify:` an offline reload logs no `error`-level line from a loader.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.helpers.js_source import js_function
from test_the_workshop_surfaces_js import _skills, skills_sandbox  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "static" / "js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")

# The two worlds every case runs in: the request never arrives, and it arrives
# and the answer is unreadable.
_HARNESS = """
const { markUnreached, quietIfUnreached } = await import(%s);
const out = {};
let mode = 'offline';
let errors = [], warns = [];
console.error = (...a) => errors.push(a.map(String).join(' '));
console.warn = (...a) => warns.push(a.map(String).join(' '));
globalThis.fetch = async () => {
  if (mode === 'offline') throw new TypeError('Failed to fetch');
  return { ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token <'); } };
};
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
async function both(load) {
  mode = 'offline'; errors = []; warns = [];
  await load(); await settle(); await load(); await settle();
  out.offline = { errors, warns };
  mode = 'garbled'; errors = []; warns = [];
  await load(); await settle();
  out.garbled = { errors, warns };
  console.log(JSON.stringify(out));
}
""" % json.dumps((JS / "presets.js").as_uri())


def _node(tmp_path: Path, body: str) -> dict:
    entry = tmp_path / "case.mjs"
    entry.write_text(_HARNESS + body, encoding="utf-8")
    proc = subprocess.run(["node", str(entry)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _cut(name: str, signature: str) -> str:
    return js_function((JS / name).read_text(encoding="utf-8"), signature)


def _assert_quiet_offline_loud_when_garbled(out, what):
    assert out["offline"]["errors"] == [], f"{what}: an offline load logged an error"
    assert len(out["offline"]["warns"]) == 1, f"{what}: not said once — {out['offline']['warns']}"
    assert "could not be reached" in out["offline"]["warns"][0]
    assert len(out["garbled"]["errors"]) == 1, \
        f"{what}: a response that came back wrong is no longer an error"


def test_the_notes_loader(tmp_path):
    # `B1228`: the list is read through `appConfig.getNotes` (the real module,
    # which has no imports), and a read is remembered in `_activeNotesRead`.
    out = _node(tmp_path, """
        // `B730`: `_notesError`, the reason a read failed, which the empty
        // list now says instead of "No notes yet."
        let _loading = false, _notes = null, _showingArchived = false, _activeNotesRead = false, _notesError = '';
        const { getNotes } = await import(%s);
        const API_BASE = 'http://x';
        async function _fetchNotes() %s
        await both(_fetchNotes);
    """ % (json.dumps((JS / "appConfig.js").as_uri()), _cut("notes.js", "async function _fetchNotes(")))
    _assert_quiet_offline_loud_when_garbled(out, "notes")


def test_the_calendar_loader(tmp_path):
    out = _node(tmp_path, """
        let _events = [], _allEvents = {}, _fetchedRanges = [], _open = false;
        const API_BASE = 'http://x';
        const _rangeIsCached = () => false, _filterPool = () => [];
        const _saveCache = () => {}, _render = () => {};
        async function _fetchEvents(start, end, force) %s
        await both(() => _fetchEvents('2026-10-01', '2026-11-01', true));
    """ % _cut("calendar.js", "async function _fetchEvents("))
    _assert_quiet_offline_loud_when_garbled(out, "calendar")


def test_the_speech_loader(tmp_path):
    out = _node(tmp_path, """
        const getSettings = async () => ({ tts_enabled: true });
        const manager = { available: true, async checkAvailability() %s };
        await both(() => manager.checkAvailability());
    """ % _cut("tts-ai.js", "async checkAvailability()"))
    _assert_quiet_offline_loud_when_garbled(out, "speech")


def test_the_skills_loader(skills_sandbox):  # noqa: F811
    out = _skills(skills_sandbox, """
        let mode = 'offline', errors = [], warns = [];
        console.error = (...a) => errors.push(a.map(String).join(' '));
        console.warn = (...a) => warns.push(a.map(String).join(' '));
        mockFetch((url) => {
          if (/\\/api\\/skills$/.test(url)) {
            if (mode === 'offline') throw new TypeError('Failed to fetch');
            return { ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token <'); } };
          }
          return res(200, {});
        });
        await skillsModule.loadSkills(); await tick(); await skillsModule.loadSkills(); await tick();
        const offline = { errors: errors.filter((e) => /skills/i.test(e)), warns };
        mode = 'garbled'; errors = []; warns = [];
        await skillsModule.loadSkills(); await tick();
        console.log(JSON.stringify({ offline, garbled: { errors: errors.filter((e) => /skills/i.test(e)), warns } }));
    """)
    _assert_quiet_offline_loud_when_garbled(out, "skills")
