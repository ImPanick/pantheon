# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B69` — there were two email-account forms and one was mounted nowhere.

`static/js/settings.js` carried roughly 370 lines of a complete second
email-account form: a provider preset table, a create/edit form, a list
renderer, a save handler and an OAuth section, reaching
`set-email-accounts-list`, `-form`, `-msg` and `-add-btn`. **None of those four
ids exists in `static/index.html`**, and no script creates them, so `el()`
returned `null`, the block's own guard returned, and none of it ran on any page
load since the fork.

**IT ARRIVED DEAD.** Upstream `ea2778d9` — *"Move email account management to
integrations"* — removed the markup and left the JavaScript. At the fork point
`b4d1293` the markup count is already `0` and the reference count is `1`. A
migration that moved the hard part and stopped before the last step, which is
the pattern this fork's README is about.

**THE COST WAS MEASURED RATHER THAN ARGUED.** `P18-01` and the first pass of
`P18-07` both landed in it — two fixes, with passing tests, against code the
browser never ran. And `static/js/ui.js` and `static/js/settings/lifecycle.js`
had each grown a `'#unified-intg-form, #set-email-accounts-form'` fallback: the
shape of code written around a corpse.

`check-wiring.py` had reported all four ids as unresolved the whole time. They
sat inside the `--max 124` ceiling, so nothing failed — the ratchet doing
exactly its job of not growing, and exactly why a whole dead form could live
there unread. The ceiling comes down to 120 with this, which is the part that
makes the deletion stick.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = ROOT / "static" / "js" / "settings.js"
INDEX_HTML = ROOT / "static" / "index.html"
CI = ROOT / ".github" / "workflows" / "ci.yml"

DEAD_IDS = (
    "set-email-accounts-list",
    "set-email-accounts-form",
    "set-email-accounts-msg",
    "set-email-accounts-add-btn",
)


def test_nothing_looks_up_the_unmounted_ids_any_more():
    """Comments may name them; no code may reach for them."""
    code = "\n".join(
        line
        for line in SETTINGS_JS.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    )
    for dead in DEAD_IDS:
        assert f"el('{dead}')" not in code, f"{dead} is still looked up"
        assert f'"{dead}"' not in code
        assert f"#{dead}" not in code


def test_the_legacy_fallbacks_are_gone():
    """A querySelector listing a dead id second is how the corpse stayed warm."""
    for path in ("static/js/ui.js", "static/js/settings/lifecycle.js"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "set-email-accounts-form" not in text, path
        assert "#unified-intg-form" in text, f"{path} lost its live selector"


def test_exactly_one_email_account_form_remains():
    """Two `formEl.innerHTML` templates carrying IMAP fields is the defect itself."""
    text = SETTINGS_JS.read_text(encoding="utf-8")
    templates = [
        text[m.start() : text.index("`;", m.start())]
        for m in re.finditer(r"formEl\.innerHTML = `", text)
    ]
    email_forms = [t for t in templates if "imap-host" in t and "smtp-host" in t]
    assert len(email_forms) == 1, (
        f"{len(email_forms)} email-account forms; a second copy is how P18-01 "
        f"and P18-07 were both fixed in code nobody runs"
    )


def test_the_form_that_remains_is_the_mounted_one():
    text = SETTINGS_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    start = text.index("async function showEmailForm")
    container = re.findall(r"const formEl = el\('([\w-]+)'\)", text[:start])[-1]
    assert f'id="{container}"' in html


def test_the_live_buttons_beside_it_survived():
    """`Law 1`. The enclosing function was not wholly dead.

    `initEmailAccountsSettings` wires three buttons *before* it reached the
    unmounted ids and returned, so those three worked. Deleting the function
    wholesale would have taken them, which is the difference between removing
    dead code and removing code.
    """
    text = SETTINGS_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    for button in (
        "set-email-open-library-settings",
        "set-email-open-integrations",
        "set-email-open-tasks",
    ):
        assert button in text, f"{button} lost its handler"
        assert f'id="{button}"' in html, f"{button} is not in the markup"


def test_the_wiring_ceiling_came_down_with_the_ids():
    """A deletion that leaves the ceiling where it was buys nothing.

    The four ids were inside `--max 124`. Leaving the ceiling there would let
    four new unresolved lookups take their place silently, which is the failure
    mode a ratchet exists to prevent.
    """
    ci = CI.read_text(encoding="utf-8")
    ceilings = {int(n) for n in re.findall(r"check-wiring\.py --max (\d+)", ci)}
    assert ceilings == {120}, f"expected a single ceiling of 120, found {ceilings}"
