# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1826`. A file picked from disk for a mail or a markdown image never arrived.

The compose paperclip's "Upload from computer" and a markdown document's
image button open a file picker. Its change handler kept `e.target.files`,
cleared `e.target.value` so the same file can be picked again, and then
uploaded what it kept. In Chromium (Chrome, Edge, Brave) that list is live:
clearing the input empties it, so the uploader was handed nothing: the mail
got no attachment and no word of it, and the image button answered "Choose an
image file" to the image just chosen. Drag-and-drop and paste pass their own
list and worked, which is how it hid. Now both handlers copy the list before
clearing the input, as the document library's import (`libraryImportPicked`)
does.

Driven in headless Chromium: the two handlers cut from `static/js/document.js`
as they stand, on a real file input, with the uploader they call replaced by
one that records what it was handed. Upstream Odysseus fixed the same two
lines in c811f76d (#6935); its test needs a static origin Pantheon does not
have, so this one sets the page's content instead.
"""
import json
import subprocess
from pathlib import Path

import pytest

from test_the_command_palette_in_a_browser import NODE, _SKIP  # noqa: E402
from tests.helpers.js_source import js_function

pytestmark = pytest.mark.skipif(NODE is None, reason=_SKIP or "")

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_JS = ROOT / "static" / "js" / "document.js"

_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const { handler, name, uploader, selections } = JSON.parse(process.argv[1]);
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e.message || e)));
    await page.setContent('<input type="file" multiple>');
    await page.addScriptTag({ content: `
      window.handed = []; window.changes = 0;
      async function ${uploader}(files) {
        window.handed.push(Array.from(files || [], (f) => [f.name, f.size]));
      }
      ${handler}
      document.querySelector('input').addEventListener('change', async (e) => {
        await ${name}(e);
        window.changes++;
      });
    ` });
    const picks = [];
    for (const [i, names] of selections.entries()) {
      await page.setInputFiles('input', names.map((n) => ({
        name: n, mimeType: 'image/png', buffer: Buffer.from('picture ' + n),
      })));
      await page.waitForFunction((n) => window.changes === n, i + 1);
      picks.push({
        handed: await page.evaluate(() => window.handed.at(-1)),
        value: await page.inputValue('input'),
      });
    }
    console.log(JSON.stringify({ picks, errors }));
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
"""

HANDLERS = [("_handleAttachUpload", "_uploadComposeFiles"),
            ("_handleMarkdownImageUpload", "_uploadMarkdownImages")]


def _pick(name: str, uploader: str, selections: list) -> dict:
    signature = f"async function {name}(e)"
    handler = signature + " " + js_function(DOCUMENT_JS.read_text(encoding="utf-8"), signature)
    proc = subprocess.run(
        [NODE, "-e", _SCRIPT, json.dumps({"handler": handler, "name": name,
                                          "uploader": uploader, "selections": selections})],
        cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("name, uploader", HANDLERS, ids=["compose-attach", "markdown-image"])
@pytest.mark.parametrize("selections", [[["one.png"]], [["one.png", "two.png"]],
                                        [["one.png"], ["one.png"]]],
                         ids=["one-file", "two-files", "the-same-file-twice"])
def test_every_file_picked_reaches_the_uploader(name, uploader, selections):
    out = _pick(name, uploader, selections)
    assert out["errors"] == []
    for names, pick in zip(selections, out["picks"], strict=True):
        assert pick["handed"] == [[n, len("picture " + n)] for n in names], pick
        # The reset stays: picking the same file again is a change.
        assert pick["value"] == ""
