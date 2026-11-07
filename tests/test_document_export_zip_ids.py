# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1988`. An export-zip body that was not a list of document ids was a 500.

`POST /api/documents/export-zip` read `data.get("ids") or []` from whatever
JSON it was sent. A body that is not an object (`[]`, `"x"`, `5`, `null`) has
no `.get`, so the route raised `AttributeError`; and ids that are not a list of
strings went on to the query, where `5` or `"abc"` raised out of `in_()` and
others were read as something nobody sent: `{"a": 1}` as the document `a`,
`["a", null]` as `a`. Each raised a 500 with a traceback in the log instead of
saying what was wrong. The Library always posts `{"ids": [<its own rows' ids>]}`,
so only a hand-built request (a script, an API token, the model's `app_api`)
reaches this.

Now a body that names no documents is told so, as an empty list always was, and
ids that are not a list of strings are refused before the database is asked;
a list of document ids is exported as before (`B1795`'s cases).

Ported from upstream Odysseus 2246215b (#6905) with its cases, and `null`,
driven through `B1795`'s app over a SQLite file rather than by calling the
handler. Upstream's integrations half is already Pantheon's (`P27-02`, which
answers "An integration is an object."), so its cases are not ported.
"""
import json

import pytest

from test_document_export_zip_filenames import exports  # noqa: F401  (`B1795`'s fixture, `Law 14`)

URL = "/api/documents/export-zip"


def test_a_body_that_names_no_documents_is_told_so(exports):  # noqa: F811
    client, _add = exports
    for body in ([], "x", 5, None, {}, {"ids": []}, {"ids": None}):
        response = client.post(URL, content=json.dumps(body), headers={"Content-Type": "application/json"})
        assert response.status_code == 400, (body, response.text)
        assert response.json()["detail"] == "No documents specified", body


@pytest.mark.parametrize("ids", [5, "abc", {"a": 1}, [1, 2], [["a"]], ["a", None]])
def test_ids_that_are_not_a_list_of_document_ids_are_refused_before_any_is_read(exports, ids):  # noqa: F811
    """`a` is a real document of this person's, so a shape the query reads
    loosely would export it."""
    client, add = exports
    add("a", "Notes", "markdown")
    response = client.post(URL, json={"ids": ids})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "ids must be a list of document ids"
