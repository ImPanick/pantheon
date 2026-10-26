# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1273` — with the documents switched off, a page load does not ask for a
Documents Tidy plan.

**Measured before this file** (`fx4-archive`'s drive for `B1194`, 8 of 8 loads):
`tasks.js` schedules `_offerWaitingDocumentPlans` at load, which asks
`GET /api/document-folders/plans` — a route behind
`require_feature("document_editor")` — so with *Document Editor* off every page
load was refused with a 403 the function swallowed and the console showed.

Now `offerWaitingDocumentPlans` waits for the tool switches and asks only while
the Library (the documents) is shown to this person: off for everyone, off for
them, or hidden in this browser, it asks nothing. Driven (`Law 20`): the real
`documentPlanNotice.js` and the real `ui_visibility.js` under node, in the
sandbox `tests/test_the_documents_tidy_asks_first.py` built for the notice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_the_documents_tidy_asks_first import _node, notice_sandbox  # noqa: E402,F401

_ASK = """
globalThis.__waiting = [];
const shown = await notice.offerWaitingDocumentPlans();
console.log(JSON.stringify({ shown, urls: sent.map((s) => s.url) }));
"""

_ON = {"features": {}, "auth": True, "isAdmin": True, "privileges": {}}


@pytest.mark.parametrize("switches", [
    {**_ON, "features": {"document_editor": False}},              # off for everyone
    {**_ON, "isAdmin": False, "privileges": {"can_use_documents": False}},   # off for this person
    {**_ON, "ui": {"tool-library": False}},                        # hidden in this browser
], ids=["everyone", "person", "browser"])
def test_documents_off_asks_for_no_plan(notice_sandbox, switches):
    out = _node(notice_sandbox, _ASK, switches=switches)
    assert out == {"shown": 0, "urls": []}, out


def test_documents_on_still_asks(notice_sandbox):
    """`Law 1`: with the documents on, the waiting proposals are asked for."""
    out = _node(notice_sandbox, _ASK, switches=_ON)
    assert out["urls"] == ["/api/document-folders/plans"], out
