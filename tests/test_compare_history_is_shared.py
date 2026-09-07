"""H12 — the voting history lived in one browser and the server's copy was write-only.

The Scoreboard is reachable and always was; the row's headline was corrected on
2026-08-31 and this follows the corrected version. What was true is the half
underneath: `showScoreboard` read `Storage.getJSON(VOTES_STORAGE_KEY)` — browser
storage — while `POST /api/compare/record` wrote a server row that nothing ever
read back, and `GET /api/compare/history` and `DELETE /api/compare/{id}` had no
caller at all.

So the two copies drifted in both directions and neither was authoritative:
clear your site data and the visible history vanished while the server still
held every vote; vote from a second browser and the Scoreboard disagreed with
itself. Nothing told anyone which copy they were looking at.

Per `Law 20`, the JS assertions resolve a function's body before matching.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOREBOARD = (ROOT / "static" / "js" / "compare" / "scoreboard.js").read_text(encoding="utf-8")
VOTE = (ROOT / "static" / "js" / "compare" / "vote.js").read_text(encoding="utf-8")


def _js_fn(source, header):
    start = source.index(header)
    i = source.index("{", start)
    depth, j = 0, i
    while j < len(source):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
        j += 1
    raise AssertionError(f"unbalanced braces reading {header}")


class _Row:
    """A `Comparison` as `_history_row` sees it."""
    def __init__(self, blind_mapping=None, model_a="a", model_b="b"):
        self.id = "cmp-1"
        self.prompt = "p" * 300
        self.model_a, self.model_b = model_a, model_b
        self.winner, self.is_blind = "a", True
        self.voted_at = self.created_at = None
        self.blind_mapping = blind_mapping


@pytest.fixture
def history_row():
    from routes.compare.compare_routes import _history_row
    return _history_row


# ── the server row can rebuild a vote ──

def test_a_new_vote_round_trips_models_costs_and_mode(history_row):
    blob = json.dumps({"models": ["a", "b", "c"], "costs": [0.1, None, 0.3], "mode": "search"})
    row = history_row(_Row(blind_mapping=blob))
    assert row["models"] == ["a", "b", "c"]
    assert row["costs"] == [0.1, None, 0.3]
    assert row["mode"] == "search"


def test_a_two_model_vote_reads_back_like_a_three_model_one(history_row):
    """Before `H12` the blob was only written for N>2, so a two-model vote and
    a three-model vote read back in different shapes from the same endpoint."""
    blob = json.dumps({"models": ["a", "b"], "costs": [0.1, 0.2], "mode": "chat"})
    row = history_row(_Row(blind_mapping=blob))
    assert row["models"] == ["a", "b"]
    assert row["costs"] == [0.1, 0.2]


@pytest.mark.parametrize("blob,expected", [
    (None, ["a", "b"]),
    ('{"models": ["a", "b", "c"]}', ["a", "b", "c"]),
    ('not json at all', ["a", "b"]),
    ('{"left": "a", "right": "b"}', ["a", "b"]),
    ('[1, 2, 3]', ["a", "b"]),
], ids=["legacy-n2", "legacy-n3", "corrupt", "a-real-blind-mapping", "not-an-object"])
def test_every_older_row_still_yields_usable_models(history_row, blob, expected):
    """This history is about to become the source of truth, so every vote
    already in the table has to survive the change. `{"left": ...}` is the
    shape the FULL comparison flow writes into the same column — a different
    writer, a different meaning, and it must not be mistaken for a vote blob."""
    assert history_row(_Row(blind_mapping=blob))["models"] == expected


def test_the_existing_keys_are_untouched(history_row):
    """`/history` is public API. The new keys sit beside the old ones."""
    row = history_row(_Row())
    assert row["model_a"] == "a" and row["model_b"] == "b"
    assert len(row["prompt"]) == 100, "the 100-char truncation is part of the contract"
    assert {"id", "winner", "is_blind", "voted_at", "created_at"} <= set(row)


def test_what_the_writer_stores_is_what_the_reader_recovers():
    """The round trip, which is the only thing that makes the pair
    trustworthy. A mutation restoring the old `if len(models) > 2` condition —
    dropping costs and mode for every two-model vote — survived a version of
    this file that tested the reader against hand-built blobs."""
    from routes.compare.compare_routes import RecordVoteRequest, _vote_meta, _history_row
    for models, costs, mode in (
        (["a", "b"], [0.1, 0.2], "chat"),
        (["a", "b", "c"], [0.1, None, 0.3], "search"),
        (["a", "b"], None, None),
    ):
        body = RecordVoteRequest(prompt="p", models=models, winner=models[0],
                                 costs=costs, mode=mode)
        stored = json.dumps(_vote_meta(body))
        row = _history_row(_Row(blind_mapping=stored, model_a=models[0], model_b=models[1]))
        assert row["models"] == models
        assert row["costs"] == costs
        assert row["mode"] == mode


def test_the_route_actually_stores_the_meta_it_computes(monkeypatch):
    """One line unreachable from the tests above: the call site.

    `_vote_meta` being right does not mean `record_comparison` calls it — a
    mutation reinstating `if len(body.models) > 2` AT THE CALL SITE survived
    every test of the function itself. Ingredient, then recipe."""
    from unittest.mock import MagicMock
    import routes.compare.compare_routes as cr

    saved = []

    class _FakeSession:
        def add(self, obj): saved.append(obj)
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(cr, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(cr, "get_current_user", lambda request: "bob")
    router = cr.setup_compare_routes(MagicMock())
    record = next(r.endpoint for r in router.routes
                  if r.path == "/api/compare/record" and "POST" in r.methods)

    record(request=None, body=cr.RecordVoteRequest(
        prompt="p", models=["a", "b"], winner="a", costs=[0.1, 0.2], mode="chat"))

    assert len(saved) == 1
    blob = json.loads(saved[0].blind_mapping)
    assert blob == {"models": ["a", "b"], "costs": [0.1, 0.2], "mode": "chat"}, \
        "a two-model vote must store its costs and mode like any other"
    assert saved[0].owner == "bob"


def test_the_vote_endpoint_accepts_what_only_the_browser_knows():
    from routes.compare.compare_routes import RecordVoteRequest
    body = RecordVoteRequest(prompt="p", models=["a", "b"], winner="a",
                             costs=[0.1, None], mode="chat")
    assert body.costs == [0.1, None] and body.mode == "chat"
    # Both optional: an older client that sends neither must still record.
    assert RecordVoteRequest(prompt="p", models=["a"], winner="a").costs is None


# ── the browser stops being the only holder ──

def test_the_vote_is_sent_with_its_costs_and_mode():
    body = _js_fn(VOTE, "function _saveVote(")
    assert "costs: costs," in body
    assert "mode: record.mode," in body


def test_the_server_id_is_stored_so_the_two_copies_can_be_joined():
    body = _js_fn(VOTE, "function _saveVote(")
    assert "mine.server_id = data.id;" in body


def test_the_id_write_re_reads_rather_than_closing_over_a_stale_array():
    """Another vote can be recorded while the POST is in flight. Writing the
    array captured before the request would drop it."""
    body = _js_fn(VOTE, "function _saveVote(")
    after = body.split(".then((data)", 1)[1]
    assert "Storage.getJSON(VOTES_STORAGE_KEY, [])" in after


def test_recording_is_still_fire_and_forget():
    """A vote must not be lost because the network was busy — the local copy is
    written first and the request never blocks or throws."""
    body = _js_fn(VOTE, "function _saveVote(")
    local_at = body.index("Storage.setJSON(VOTES_STORAGE_KEY, votes)")
    fetch_at = body.index("api/compare/record")
    assert local_at < fetch_at, "the local copy must be written before the request"
    assert ".catch(() => {})" in body


# ── the Scoreboard reads the server ──

def test_the_scoreboard_asks_the_server_first():
    body = _js_fn(SCOREBOARD, "async function _loadVotes(")
    assert "/api/compare/history" in body


def test_it_falls_back_to_local_when_the_server_cannot_be_reached():
    body = _js_fn(SCOREBOARD, "async function _loadVotes(")
    assert "source: 'local'" in body
    assert "source: 'server'" in body


def test_it_says_which_copy_it_is_showing():
    """The defect was never that the numbers were wrong. It was that two copies
    existed, drifted, and nothing said which one you were looking at."""
    assert "loaded.source === 'server'" in SCOREBOARD
    assert "the server could not be reached" in SCOREBOARD
    assert "the same history on every browser" in SCOREBOARD


def test_votes_that_never_reached_the_server_are_kept_not_dropped():
    body = _js_fn(SCOREBOARD, "async function _loadVotes(")
    assert "local.filter((v) => !v.server_id)" in body
    assert "concat(undelivered)" in body


def test_a_vote_cast_elsewhere_still_shows_without_local_costs():
    """A row with no matching local record must survive the merge — that is the
    entire point of reading the server."""
    body = _js_fn(SCOREBOARD, "async function _loadVotes(")
    merge = body.split("rows.map(", 1)[1]
    assert "mine?.costs" in merge, "costs must be optional, not required"
    assert "row.costs ||" in merge, "the server's costs win when it has them"


def test_clear_history_clears_both_copies():
    """Clearing one and not the other is how they drifted: the local list
    emptied, the server kept everything, and the next browser showed a history
    the person believed they had deleted."""
    handler = SCOREBOARD.split("yesBtn.addEventListener", 1)[1].split("const noBtn", 1)[0]
    assert "method: 'DELETE'" in handler
    assert "/api/compare/" in handler
    assert "Storage.setJSON(VOTES_STORAGE_KEY, [])" in handler
    delete_at = handler.index("method: 'DELETE'")
    local_at = handler.index("Storage.setJSON(VOTES_STORAGE_KEY, [])")
    assert delete_at < local_at, \
        "the server ids come from the loaded list; clearing local first loses them"


def test_one_failed_delete_does_not_strand_the_rest():
    handler = SCOREBOARD.split("yesBtn.addEventListener", 1)[1].split("const noBtn", 1)[0]
    assert "catch (_)" in handler
    # The list it iterates, not merely that it iterates something: a mutation
    # to `for (const id of [])` kept every other assertion here true.
    assert re.search(r"for \(const id of \(loaded\.serverIds", handler)
