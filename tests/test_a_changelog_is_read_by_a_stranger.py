# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B25` — the changelog claimed an AGPL §13 source link that never shipped.

`CHANGELOG.md` listed *"Source link in the UI footer, per AGPL-3.0 §13"* under
`#### Added` from the fork baseline. There was no such link anywhere in the UI:
the only repository URL in the frontend was an issue-tracker fallback behind the
admin panel (`static/js/admin.js`), and `static/index.html` had no `<footer>`
at all.

`D-2026-09-08-06` settled what to do and settled it the other way round from
what the row assumed: **the line came out at once** rather than waiting for the
repository to go public. A changelog is what a stranger reads to audit
conformance, and a false compliance claim was worse while the repository was
private, not better — nobody could check it. The link itself is `P0-17`: built
on 2026-09-18 and left dark against an address that shipped empty.

**Since 2026-10-02 it is drawn by default** (`D-2026-10-02-04` §2: the
repository is public, so an unmodified install offers it), and the newest
release lists it again. So the rule these tests hold is the one the withdrawal
note promised — *"it goes back in this file when it renders"* — in both
directions, against the page the server actually sends (`Law 20`): the newest
release claims the link exactly when an unconfigured install draws it, and the
release that never drew it (`0.1.0`) still does not claim it.

**This is an engineering read of the licence text and not legal advice**: §13's
obligation attaches to whoever *offers* a modified version over a network.
"""
import re
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
_RELEASE = re.compile(r"^## \[(\d+\.\d+\.\d+)\](?: — \d{4}-\d{2}-\d{2})?\s*$", re.M)


def _releases() -> dict:
    """`{version: body}` for every release heading, newest first."""
    marks = list(_RELEASE.finditer(CHANGELOG))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(CHANGELOG)
        out[m.group(1)] = CHANGELOG[m.end():end].split("\n## ", 1)[0]
    return out


def _listed_added(body: str) -> list:
    """What a release's `#### Added` LISTS — bullets, not the withdrawal note
    (a record of what was claimed is the point of a withdrawal note)."""
    added = body.split("#### Added", 1)[1].split("\n####", 1)[0]
    added = re.sub(r"<!--.*?-->", "", added, flags=re.S)
    items, current = [], None
    for ln in added.splitlines():
        if ln.startswith("- "):
            current = [ln]
            items.append(current)
        elif current is not None and ln.startswith("  "):
            current.append(ln)
        else:
            current = None
    return [" ".join(" ".join(i).split()) for i in items]


def _claims_the_link(items: list) -> list:
    return [i for i in items if "§13" in i or "AGPL" in i]


def _an_unconfigured_install_draws_the_link(monkeypatch) -> bool:
    """The login page, served by the one front door, with nothing configured."""
    pytest.importorskip("fastapi")
    from starlette.datastructures import Headers

    from src.app_helpers import _PAGE_CACHE, serve_html_with_nonce

    monkeypatch.delenv("PANTHEON_SOURCE_URL", raising=False)
    _PAGE_CACHE.clear()
    try:
        request = types.SimpleNamespace(state=types.SimpleNamespace(csp_nonce="n"),
                                        headers=Headers({}))
        body = serve_html_with_nonce(request, str(ROOT / "static" / "login.html")).body
    finally:
        _PAGE_CACHE.clear()
    return b'data-source-offer="1"' in body


def test_the_newest_release_claims_the_link_exactly_when_the_product_draws_it(monkeypatch):
    """Replaced, on 2026-10-02, a test that looked for `github.com` in the two
    static HTML files: the link is injected when the page is served, so that
    test could not see it either way and passed while the link was drawn."""
    newest = next(iter(_releases().values()))
    claimed = _claims_the_link(_listed_added(newest))
    drawn = _an_unconfigured_install_draws_the_link(monkeypatch)
    assert bool(claimed) == drawn, (
        f"an unconfigured install {'draws' if drawn else 'does not draw'} the §13 "
        f"link and the newest release's Added {'does not list' if not claimed else 'lists'} "
        f"it: {claimed}")


def test_the_release_that_never_drew_it_still_does_not_claim_it():
    """`0.1.0`'s heading is dated 2026-09-17, before `P0-17` was built at all."""
    listed = _listed_added(_releases()["0.1.0"])
    assert listed, "0.1.0's Added section lists nothing — the parse is wrong"
    assert not _claims_the_link(listed), listed


def test_the_line_was_withdrawn_rather_than_quietly_deleted():
    """`Law 1`'s cousin: a record of what was claimed is evidence, and a
    silently corrected record is a different kind of dishonesty (`B44`)."""
    assert "B25" in CHANGELOG
    assert "D-2026-09-08-06" in CHANGELOG
