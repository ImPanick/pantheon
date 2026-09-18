# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-09` — what is consuming the window, on the wire.

The composer's surface is `static/`, which this agent does not own. What is
built here is the half that has to exist before any surface can draw: the
budgets and their source layer, and the **real** per-attachment spend —
computed by `build_user_content` on every turn since it was written, and
discarded on every one of them. That is `P4`'s shape (a value computed, used,
and never shown) in `P12`'s phase.

Four of the five segments the row names — system prompt, skills, retrieved
memory, history — are assembled in `src/agent_loop.py` and are reported
`measured: false`, never `0`. A meter that draws an unmeasured segment as empty
is `Law 10`'s polarity incident in a bar chart.
"""
import types

import pytest

from src import roles as roles_mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    import src.settings as settings_mod
    roles_mod.clear_role_layer()
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    settings_mod._invalidate_caches()
    yield
    roles_mod.clear_role_layer()
    settings_mod._invalidate_caches()


class _Handler:
    def __init__(self, uploads, upload_dir):
        self.uploads = uploads
        self.upload_dir = upload_dir

    def resolve_upload(self, fid, owner=None):
        return self.uploads.get(fid)

    def _inside_upload_dir(self, path):
        return True

    def is_image_file(self, display_name, mime):
        return False

    def is_audio_file(self, display_name, mime):
        return False

    def is_document_file(self, display_name, mime):
        return True

    def validate_upload_id(self, fid):
        return fid in self.uploads


def _upload(tmp_path, name, body):
    (tmp_path / name).write_text(body, encoding="utf-8")
    return {"path": str(tmp_path / name), "name": name, "mime": "text/plain"}


def test_build_user_content_reports_the_spend_it_already_computed(tmp_path):
    import src.document_processor as dp

    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 4000),
               "b": _upload(tmp_path, "b.txt", "B" * 4000)}
    report = {}
    dp.build_user_content("hi", ["a", "b"], str(tmp_path),
                          _Handler(uploads, str(tmp_path)),
                          owner="bob", budget_report=report)
    assert report["total_chars"] == 24000
    assert report["used_chars"] > 8000
    assert report["used_chars"] + report["remaining_chars"] == 24000
    assert [a["name"] for a in report["attachments"]] == ["a.txt", "b.txt"]
    assert {a["state"] for a in report["attachments"]} == {"full"}


def test_the_three_attachment_states_are_three_values_not_a_boolean(tmp_path):
    import src.document_processor as dp
    import src.settings as settings_mod

    settings_mod.save_settings({**settings_mod.load_settings(),
                                "context_attachment_total_chars": 3000})
    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 2000),
               "b": _upload(tmp_path, "b.txt", "B" * 2000),
               "c": _upload(tmp_path, "c.txt", "C" * 2000)}
    report = {}
    dp.build_user_content("hi", ["a", "b", "c"], str(tmp_path),
                          _Handler(uploads, str(tmp_path)),
                          owner="bob", budget_report=report)
    assert [a["state"] for a in report["attachments"]] == \
        ["full", "truncated", "omitted"]


def test_an_omitted_attachment_is_not_reported_as_free(tmp_path):
    """The number that matters for a meter: the omitted file spent the
    remainder of the budget on its own banner, not zero."""
    import src.document_processor as dp
    import src.settings as settings_mod

    settings_mod.save_settings({**settings_mod.load_settings(),
                                "context_attachment_total_chars": 2200})
    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 3000),
               "b": _upload(tmp_path, "b.txt", "B" * 3000)}
    report = {}
    dp.build_user_content("hi", ["a", "b"], str(tmp_path),
                          _Handler(uploads, str(tmp_path)),
                          owner="bob", budget_report=report)
    assert report["remaining_chars"] == 0
    assert report["used_chars"] == 2200


def test_the_report_names_every_budget_its_value_and_who_decided_it():
    from src.context_budget import CONTEXT_BUDGETS, context_window_report
    import src.settings as settings_mod

    out = context_window_report("bob")
    assert [b["key"] for b in out["budgets"]] == list(CONTEXT_BUDGETS)
    assert out["ceiling_key"] == "context_attachment_total_chars"
    assert all(b["source"] == "default" for b in out["budgets"])
    assert all(b["label"] for b in out["budgets"])
    assert sum(1 for b in out["budgets"] if b["is_ceiling"]) == 1

    settings_mod.save_settings({**settings_mod.load_settings(),
                                "context_attachment_total_chars": 9000})
    out = context_window_report("bob")
    ceiling = next(b for b in out["budgets"] if b["is_ceiling"])
    assert (ceiling["chars"], ceiling["source"]) == (9000, "setting")


def test_an_unmeasured_segment_says_so_rather_than_drawing_a_zero():
    from src.context_budget import CONTEXT_SEGMENTS, context_window_report

    out = context_window_report("bob")
    assert [s["key"] for s in out["segments"]] == list(CONTEXT_SEGMENTS)
    for seg in out["segments"]:
        assert seg["measured"] is False
        assert "chars" not in seg
    assert out["measured_segments"] == []
    assert "agent_loop" in out["unmeasured_reason"]


def test_the_attachment_segment_becomes_measured_when_a_turn_is_supplied():
    from src.context_budget import context_window_report

    turn = {"total_chars": 24000, "used_chars": 8100, "remaining_chars": 15900,
            "attachments": [{"id": "a", "name": "a.txt", "chars": 8100,
                             "state": "full"}]}
    out = context_window_report("bob", turn=turn)
    seg = next(s for s in out["segments"] if s["key"] == "attachments")
    assert seg["measured"] is True
    assert seg["chars"] == 8100
    assert seg["tokens"] == 2434          # the product's own estimator, not a second one
    assert out["measured_segments"] == ["attachments"]


async def test_the_upload_response_carries_what_the_attachment_will_cost(tmp_path):
    """On the wire, on the response to the request that changed the answer.

    A GET endpoint would have been the obvious shape and could not merge: its
    only caller is a composer in `static/`, which this row does not own, and
    `.pantheon/check-unreachable.py` holds a ceiling of 90 routes with no
    frontend caller precisely so an unwired half cannot land (`Law 13`). The
    upload response is a wire the composer already reads.
    """
    import routes.upload_routes as up

    uploads = {}
    handler = _Handler(uploads, str(tmp_path))
    handler.upload_rate_log = {}
    handler.upload_burst_limit = 50
    handler.upload_burst_window_seconds = 10

    def _save(u, client_ip, owner=None):
        fid = u.filename
        uploads[fid] = _upload(tmp_path, u.filename, "A" * 4000)
        return {"id": fid, "name": u.filename, "mime": "text/plain", "size": 4000,
                "hash": "h", "uploaded_at": "now", "width": None, "height": None,
                "is_duplicate": False}

    handler.save_upload = _save
    router, _ = up.setup_upload_routes(handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/upload"
                    and "POST" in getattr(r, "methods", set()))
    req = types.SimpleNamespace(client=types.SimpleNamespace(host="1.2.3.4"),
                                state=types.SimpleNamespace(current_user="bob"))
    files = [types.SimpleNamespace(filename="a.txt"),
             types.SimpleNamespace(filename="b.txt")]

    out = await endpoint(req, files)
    budget = out["context_budget"]
    seg = next(s for s in budget["segments"] if s["key"] == "attachments")
    assert seg["measured"] is True
    assert [i["name"] for i in seg["items"]] == ["a.txt", "b.txt"]
    assert seg["chars"] > 8000
    assert seg["budget_chars"] == 24000
    assert budget["ceiling_key"] == "context_attachment_total_chars"
    assert budget["measured_segments"] == ["attachments"]


async def test_the_wire_reports_the_uploader_own_budget_not_the_instance_default(tmp_path):
    """The meter has to be the caller's. A breakdown drawn from somebody else's
    ceiling is a number that disagrees with what their send will do."""
    import importlib

    import routes.upload_routes as up

    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("bob", "pw-123456")
    mgr.define_role("tight", {"context_attachment_total_chars": 3000})
    mgr.set_user_role("bob", "tight")
    roles_mod.install_role_layer(mgr)

    uploads = {}
    handler = _Handler(uploads, str(tmp_path))
    handler.upload_rate_log = {}
    handler.upload_burst_limit = 50
    handler.upload_burst_window_seconds = 10

    def _save(u, client_ip, owner=None):
        uploads[u.filename] = _upload(tmp_path, u.filename, "A" * 4000)
        return {"id": u.filename, "name": u.filename, "mime": "text/plain",
                "size": 4000, "hash": "h", "uploaded_at": "now", "width": None,
                "height": None, "is_duplicate": False}

    handler.save_upload = _save
    router, _ = up.setup_upload_routes(handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/upload"
                    and "POST" in getattr(r, "methods", set()))
    req = types.SimpleNamespace(client=types.SimpleNamespace(host="1.2.3.4"),
                                state=types.SimpleNamespace(current_user="bob"))
    out = await endpoint(req, [types.SimpleNamespace(filename="a.txt")])
    budget = out["context_budget"]
    ceiling = next(b for b in budget["budgets"] if b["is_ceiling"])
    assert (ceiling["chars"], ceiling["source"]) == (3000, "role")
    seg = next(s for s in budget["segments"] if s["key"] == "attachments")
    assert seg["budget_chars"] == 3000


async def test_a_meter_that_cannot_be_read_is_not_a_failed_upload(tmp_path):
    """The files are already on disk when this runs. A breakdown that raises
    must cost the preview, never the upload."""
    import routes.upload_routes as up

    handler = _Handler({}, str(tmp_path))
    handler.upload_rate_log = {}
    handler.upload_burst_limit = 50
    handler.upload_burst_window_seconds = 10
    handler.save_upload = lambda u, ip, owner=None: {
        "id": "nope", "name": u.filename, "mime": "text/plain", "size": 1,
        "hash": "h", "uploaded_at": "now", "width": None, "height": None,
        "is_duplicate": False}

    def _boom(*a, **kw):
        raise RuntimeError("no")

    router, _ = up.setup_upload_routes(handler)
    endpoint = next(r.endpoint for r in router.routes
                    if getattr(r, "path", None) == "/api/upload"
                    and "POST" in getattr(r, "methods", set()))
    import src.document_processor as dp
    original = dp.build_user_content
    dp.build_user_content = _boom
    try:
        req = types.SimpleNamespace(client=types.SimpleNamespace(host="1.2.3.4"),
                                    state=types.SimpleNamespace(current_user="bob"))
        out = await endpoint(req, [types.SimpleNamespace(filename="a.txt")])
    finally:
        dp.build_user_content = original
    assert out["files"][0]["name"] == "a.txt"
    assert "context_budget" not in out
