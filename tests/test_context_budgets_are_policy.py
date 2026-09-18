# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P12-04` — the character budgets stop being literals.

Seven budgets, re-measured 2026-09-18 against `src/document_processor.py` and
`src/agent_loop.py` rather than carried from the row (`Law 6`): the shared
24,000-character attachment budget, the per-text-file 30,000, the `.log`-only
10,000, and **three separate 15,000s** — the PDF extraction cap, the Office /
EPUB inline cap and the PDF body inlined into chat — plus the skill-injection
count. The row said "the PDF's 15,000" as though there were one.

Six of the seven become policy here. The seventh — `skill_max_injected` — is a
setting already, and its only consumer is `src/agent_loop.py`; it is named on
the row and filed as `B750` rather than half-wired from here.

`src/context_budget.py` already implemented the shape (`Law 14`): a pure
budget computation with `budget_is_explicit` beside it. It is extended. There
is no eighth module, and no second resolution chain — every budget below
resolves through `settings.resolve_limit` by way of `limit_policy`.

Everything here drives `build_user_content` or one of the processors it calls.
Nothing greps a source file (`Law 20`).
"""
import importlib

import pytest

from src import roles as roles_mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """A settings file of this test's own, and no leaked role provider."""
    import src.settings as settings_mod
    roles_mod.clear_role_layer()
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    settings_mod._invalidate_caches()
    yield
    roles_mod.clear_role_layer()
    settings_mod._invalidate_caches()


def _store(**values):
    import src.settings as settings_mod
    settings_mod.save_settings({**settings_mod.load_settings(), **values})


class _UploadHandler:
    def __init__(self, uploads):
        self.uploads = uploads

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


def _upload(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return {"path": str(path), "name": name, "mime": "text/plain"}


def _content(tmp_path, uploads, owner="bob"):
    import src.document_processor as dp
    return dp.build_user_content(
        "read these", list(uploads), str(tmp_path),
        _UploadHandler(uploads), owner=owner,
    )


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------

def test_the_six_character_budgets_are_one_registry_with_the_shipped_numbers():
    from src.context_budget import CONTEXT_BUDGETS

    assert CONTEXT_BUDGETS == {
        "context_attachment_total_chars": 24000,
        "context_text_file_chars": 30000,
        "context_log_file_chars": 10000,
        "context_pdf_extract_chars": 15000,
        "context_office_inline_chars": 15000,
        "context_pdf_inline_chars": 15000,
    }


def test_the_module_constants_are_the_registry_and_not_a_second_copy():
    """`Law 7`. `MAX_INLINE_ATTACHMENT_CHARS` survives (`Law 1`) and is the
    registry's own number, so the two cannot drift."""
    import src.document_processor as dp
    from src.context_budget import CONTEXT_BUDGETS

    assert dp.MAX_INLINE_ATTACHMENT_CHARS == CONTEXT_BUDGETS["context_attachment_total_chars"]


def test_every_budget_is_a_settable_nullable_limit():
    """They join the table `POST /api/auth/settings` validates and a role may
    carry — not a parallel vocabulary of their own."""
    from src.settings import DEFAULT_SETTINGS, LIMIT_RANGES
    from src.context_budget import CONTEXT_BUDGETS

    for key in CONTEXT_BUDGETS:
        assert key in LIMIT_RANGES, key
        assert key in DEFAULT_SETTINGS, key
        assert DEFAULT_SETTINGS[key] is None, key


# ---------------------------------------------------------------------------
# each budget, driven
# ---------------------------------------------------------------------------

def test_the_shared_attachment_budget_is_policy(tmp_path):
    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 4000),
               "b": _upload(tmp_path, "b.txt", "B" * 4000)}
    assert "=== File: b.txt ===" in _content(tmp_path, uploads)

    _store(context_attachment_total_chars=1200)
    shrunk = _content(tmp_path, uploads)
    assert "Attachment omitted from inline context: b.txt" in shrunk
    assert "1,200-character shared inline" in shrunk


def test_the_per_text_file_budget_is_policy(tmp_path):
    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 9000)}
    assert _content(tmp_path, uploads).count("A") == 9000

    _store(context_text_file_chars=500)
    assert _content(tmp_path, uploads).count("A") == 500


def test_the_log_budget_is_its_own_key_and_does_not_move_the_text_one(tmp_path):
    """The `.log` branch nobody had mentioned. It is a second number on one
    line — `30000 if ext != ".log" else 10000` — and it needs its own key or an
    operator raising the text budget silently raises the log one too."""
    uploads = {"a": _upload(tmp_path, "a.log", "Z" * 9000),
               "b": _upload(tmp_path, "b.txt", "Q" * 9000)}
    _store(context_log_file_chars=300, context_attachment_total_chars=100000)
    out = _content(tmp_path, uploads)
    assert out.count("Z") == 300
    assert out.count("Q") == 9000


def test_no_per_file_budget_may_exceed_the_shared_ceiling(tmp_path):
    """"A single coherent budget" is the row's own phrase, and this is the
    property that makes it one: the shared ceiling is the ceiling, so a
    per-file cap above it cannot hand one attachment more than the turn has."""
    from src.context_budget import resolve_context_budget

    _store(context_attachment_total_chars=5000)
    assert resolve_context_budget("context_text_file_chars", "bob") == 5000
    assert resolve_context_budget("context_pdf_extract_chars", "bob") == 5000
    assert resolve_context_budget("context_log_file_chars", "bob") == 5000
    # And below the ceiling the per-file number is still its own.
    _store(context_attachment_total_chars=50000)
    assert resolve_context_budget("context_text_file_chars", "bob") == 30000


def test_the_pdf_extraction_budget_is_policy(tmp_path, monkeypatch):
    import src.document_processor as dp

    _fake_pypdf(monkeypatch, "P" * 40000)
    assert len(dp._process_pdf(str(tmp_path / "x.pdf"))) > 15000
    _store(context_pdf_extract_chars=900, context_attachment_total_chars=100000)
    out = dp._process_pdf(str(tmp_path / "x.pdf"))
    # The budget bounds the assembled extraction — the page banners included,
    # because those are characters the model has to read too.
    body = out.split("[PDF content]:", 1)[1].split("\n[PDF content truncated]")[0]
    assert len(body) == 900
    assert "[PDF content truncated]" in out


def test_the_office_inline_budget_is_policy(tmp_path, monkeypatch):
    import src.document_processor as dp
    import src.markitdown_runtime as md

    monkeypatch.setattr(md, "is_office_format", lambda path: True)
    monkeypatch.setattr(md, "convert_to_markdown", lambda path: "O" * 40000)
    assert dp._process_office_document(str(tmp_path / "x.docx"), "x.docx").count("O") == 15000

    _store(context_office_inline_chars=700, context_attachment_total_chars=100000)
    assert dp._process_office_document(str(tmp_path / "x.docx"), "x.docx").count("O") == 700


def test_the_pdf_inline_budget_is_its_own_key(tmp_path, monkeypatch):
    """The third 15,000. It caps the PDF body copied into the chat message,
    which is a different decision from how much text the extractor keeps."""
    from src.context_budget import resolve_context_budget

    _store(context_pdf_extract_chars=14000, context_pdf_inline_chars=800,
           context_attachment_total_chars=100000)
    assert resolve_context_budget("context_pdf_extract_chars", "bob") == 14000
    assert resolve_context_budget("context_pdf_inline_chars", "bob") == 800


# ---------------------------------------------------------------------------
# the per-role ceiling the row asks for
# ---------------------------------------------------------------------------

def test_a_role_lowers_the_ceiling_for_one_person_and_nobody_else(tmp_path):
    from src.context_budget import resolve_context_budget

    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("bob", "pw-123456")
    mgr.create_user("eve", "pw-123456")
    mgr.define_role("tight", {"context_attachment_total_chars": 2000})
    mgr.set_user_role("bob", "tight")
    roles_mod.install_role_layer(mgr)

    assert resolve_context_budget("context_attachment_total_chars", "bob") == 2000
    # and the ceiling really is a ceiling: the per-file budgets follow it down.
    assert resolve_context_budget("context_text_file_chars", "bob") == 2000
    assert resolve_context_budget("context_attachment_total_chars", "eve") == 24000
    # 30,000 was never reachable: the turn only ever had 24,000 to give. That
    # incoherence is what the row means by "a single coherent budget".
    assert resolve_context_budget("context_text_file_chars", "eve") == 24000


def test_a_role_sets_a_per_file_budget_and_the_processor_honours_it(tmp_path):
    """Not only the ceiling. Each per-file budget carries the caller's owner
    into the resolution, or a role can shrink the turn and not the file."""
    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("bob", "pw-123456")
    mgr.create_user("eve", "pw-123456")
    mgr.define_role("terse", {"context_text_file_chars": 600,
                              "context_log_file_chars": 200})
    mgr.set_user_role("bob", "terse")
    roles_mod.install_role_layer(mgr)

    uploads = {"a": _upload(tmp_path, "a.txt", "Q" * 9000),
               "b": _upload(tmp_path, "b.log", "Z" * 9000)}
    mine = _content(tmp_path, uploads, owner="bob")
    assert mine.count("Q") == 600
    assert mine.count("Z") == 200
    theirs = _content(tmp_path, uploads, owner="eve")
    assert theirs.count("Q") == 9000
    assert theirs.count("Z") == 9000


def test_the_role_ceiling_reaches_the_real_attachment_path(tmp_path):
    """`Law 20`. The resolver answering is not the same claim as the product
    honouring it."""
    auth_mod = importlib.import_module("core.auth")
    auth_mod._hash_password = lambda password: f"hash:{password}"
    auth_mod._verify_password = lambda password, hashed: hashed == f"hash:{password}"
    mgr = auth_mod.AuthManager(str(tmp_path / "auth.json"))
    mgr.create_user("bob", "pw-123456")
    mgr.define_role("tight", {"context_attachment_total_chars": 1500})
    mgr.set_user_role("bob", "tight")
    roles_mod.install_role_layer(mgr)

    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 4000),
               "b": _upload(tmp_path, "b.txt", "B" * 4000)}
    assert "Attachment omitted from inline context: b.txt" in _content(tmp_path, uploads)
    assert "1,500-character shared inline" in _content(tmp_path, uploads)


def test_the_shared_ceiling_is_resolved_once_for_the_whole_turn(tmp_path, monkeypatch):
    """`P12-03`'s rule, held rather than claimed: a settings save or a role
    change landing between a message's first attachment and its last must not
    apply two different budgets to one message. Counted, because "resolved
    once" is not observable from the answer when nothing changed."""
    import src.limit_policy as lp

    real = lp.resolve_int_limit
    seen = []

    def _counting(key, **kw):
        seen.append(key)
        return real(key, **kw)

    monkeypatch.setattr(lp, "resolve_int_limit", _counting)
    uploads = {name: _upload(tmp_path, f"{name}.txt", "Q" * 100)
               for name in ("a", "b", "c", "d")}
    _content(tmp_path, uploads)
    assert seen.count("context_attachment_total_chars") == 1
    # and each file still resolves its own per-file budget
    assert seen.count("context_text_file_chars") == 4


# ---------------------------------------------------------------------------
# Law 1, and the floor
# ---------------------------------------------------------------------------

def test_the_module_constant_is_still_the_bottom_layer(tmp_path, monkeypatch):
    """The existing budget test patches `dp.MAX_INLINE_ATTACHMENT_CHARS` and
    must keep deciding: the constant is read as a live attribute, not closed
    over, exactly as `P12-03` left the byte caps."""
    import src.document_processor as dp

    monkeypatch.setattr(dp, "MAX_INLINE_ATTACHMENT_CHARS", 1200)
    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 1000),
               "b": _upload(tmp_path, "b.txt", "B" * 1000)}
    assert "1,200-character shared inline" in _content(tmp_path, uploads)


def test_a_stored_budget_beats_the_module_constant(tmp_path, monkeypatch):
    import src.document_processor as dp

    monkeypatch.setattr(dp, "MAX_INLINE_ATTACHMENT_CHARS", 1200)
    _store(context_attachment_total_chars=900)
    uploads = {"a": _upload(tmp_path, "a.txt", "A" * 1000),
               "b": _upload(tmp_path, "b.txt", "B" * 1000)}
    assert "900-character shared inline" in _content(tmp_path, uploads)


def test_there_is_no_budget_meaning_off(tmp_path):
    """A budget of zero drops every attachment while reading as a configured
    number. The floor is enforced in the resolver, so a hand-edited
    `settings.json` cannot reach it either."""
    from src.context_budget import resolve_context_budget

    _store(context_attachment_total_chars=0, context_text_file_chars=-5)
    assert resolve_context_budget("context_attachment_total_chars", "bob") == 1
    assert resolve_context_budget("context_text_file_chars", "bob") == 1


def test_a_budget_resolves_per_call_with_no_restart(tmp_path):
    from src.context_budget import resolve_context_budget

    assert resolve_context_budget("context_text_file_chars", "bob") == 24000
    _store(context_text_file_chars=7000, context_attachment_total_chars=100000)
    assert resolve_context_budget("context_text_file_chars", "bob") == 7000


def test_the_source_layer_is_reported_so_an_operator_can_see_who_decided(tmp_path):
    from src.context_budget import resolve_context_budget_detail

    assert resolve_context_budget_detail("context_text_file_chars", "bob").source == "default"
    _store(context_text_file_chars=7000, context_attachment_total_chars=100000)
    assert resolve_context_budget_detail("context_text_file_chars", "bob").source == "setting"


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

def _fake_pypdf(monkeypatch, text):
    import pypdf

    class _Page:
        images = []
        def extract_text(self):
            return text

    class _Reader:
        def __init__(self, path):
            self.pages = [_Page()]

    monkeypatch.setattr(pypdf, "PdfReader", _Reader)
