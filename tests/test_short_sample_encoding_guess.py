# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B201` — a guess about eleven bytes is not evidence, and is no longer taken.

Measured on the tree as it stood: ``charset_normalizer`` answers **Big5** for
the 11 bytes of ``"сервер порт"`` in cp1251, the Big5 decode carries no
replacement characters and no control characters — so it beats UTF-8 on both of
the comparisons `B101` built — and the file arrives as ``'鼫謼歑 瀁貗'``. The same
text at 21 bytes is identified as ``windows-1251`` and at 33 too, so the
boundary is sample size and not codec.

**The lever is which guesses to trust, not how hard to trust the detector.** A
*single-byte* codec maps one byte to one character: getting it wrong gives the
right words with the wrong accents, which is bounded and recoverable. A
*multi-byte* codec regroups the bytes — the character count changes, and for
Big5, Shift-JIS and the GB family a trail byte may legally be an ASCII byte, so
an ASCII letter after a high byte is swallowed. That is the same kind of
nonsense as the UTF-16/32 guess the function already refuses, and it is refused
the same way: structurally, before the "did it decode cleanly" comparison, since
the whole problem is that it decodes perfectly cleanly.

The floor is measured, not chosen — see ``_MIN_MULTIBYTE_SAMPLE``'s comment in
``src/document_processor.py``. Below it a multi-byte answer was right 22 times
and wrong 59 across eleven real prose samples in ten encodings truncated at
every length from 4 to 48 bytes; at and above it, right 44 and wrong 20.

The four doors this decision reaches are all driven here: the probe, the reader,
the composer's banner and the mailbox's refusal.
"""
import contextlib

import pytest

import routes.email_routes as email_routes
import src.document_processor as dp
import src.personal_docs as personal_docs
from src.document_processor import (
    build_user_content,
    decode_text_file,
    looks_like_text,
    sniff_text_encoding,
)
from src.upload_handler import UploadHandler

# Resolved with ``getattr`` rather than imported, which is the pattern
# `tests/test_one_register_across_chat_and_index.py` already uses for the skip
# reasons. `Law 9` wants each test below to fail **on the tree as it stood** for
# its own reason; a module-level ImportError would collapse all of them into one
# collection error, which is weaker evidence and hides which ones were already
# true. The defaults are what the old tree behaves like, so the assertions —
# not the imports — are what report the difference.
ENCODING_UNIDENTIFIED = getattr(
    dp, "ENCODING_UNIDENTIFIED", "the encoding could not be identified from so few bytes")
NOT_TEXT = getattr(dp, "NOT_TEXT", "the bytes do not decode as text")
describe_text_encoding = getattr(
    dp, "describe_text_encoding", lambda head: (sniff_text_encoding(head), ""))
MIN_MULTIBYTE_SAMPLE = getattr(dp, "_MIN_MULTIBYTE_SAMPLE", 24)
SKIP_UNKNOWN_ENCODING = getattr(
    personal_docs, "SKIP_UNKNOWN_ENCODING", "text in an unidentifiable encoding")
SKIP_UNSUPPORTED = getattr(personal_docs, "SKIP_UNSUPPORTED", "unsupported extension")
NOT_LISTED = getattr(personal_docs, "NOT_LISTED", ())

# The row's own sample, byte for byte.
SHORT_RUSSIAN = "сервер порт"
LONGER_RUSSIAN = "сервер порт настройка"

RAW_EMAIL = b"Subject: t\r\nMessage-ID: <m@x>\r\n\r\nbody\r\n"


def _write(tmp_path, name, body: bytes):
    path = tmp_path / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _render(tmp_path, name, body: bytes) -> str:
    """Drive the real ``build_user_content`` over one real file."""
    handler = UploadHandler(str(tmp_path), str(tmp_path / "uploads"))
    path = tmp_path / "uploads" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    out = build_user_content(
        "please read this", ["fid"], str(tmp_path / "uploads"), handler,
        owner="tester",
        resolved_uploads={"fid": {"path": str(path), "name": name, "mime": None}},
    )
    if isinstance(out, str):
        return out
    return "".join(b.get("text", "") for b in out if isinstance(b, dict))


def _drive_mailbox(tmp_path, monkeypatch, name, body: bytes):
    target = tmp_path / "extract"
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_bytes(body)

    @contextlib.contextmanager
    def fake_imap(account_id=None, owner=""):
        yield type("C", (), {"select": lambda self, *a, **k: None})()

    monkeypatch.setattr(email_routes, "_imap", fake_imap)
    monkeypatch.setattr(email_routes, "_imap_uid_fetch",
                        lambda *a, **k: ("OK", [(None, RAW_EMAIL)]))
    monkeypatch.setattr(email_routes, "attachment_extract_dir",
                        lambda folder, uid: target)
    monkeypatch.setattr(email_routes, "_extract_attachment_to_disk",
                        lambda msg, index, d: target / name)
    monkeypatch.setattr("src.auth_helpers.get_current_user", lambda request: "tester")
    router = email_routes.setup_email_routes()
    endpoint = next(
        r.endpoint for r in router.routes
        if r.path == "/api/email/attachment-as-doc/{uid}/{index}"
        and "POST" in getattr(r, "methods", set())
    )
    return endpoint("42", 0, request=None, folder="INBOX",
                    account_id=None, owner="tester")


# ── the row's `Verify`, at the decision ─────────────────────────────────────

def test_a_two_word_cp1251_file_is_never_decoded_as_big5():
    """*"decodes as cp1251 or as nothing, never as Big5"*, at the sniff.

    The detector is left real on purpose. This is the measurement the row was
    filed on and it has to keep being the measurement.
    """
    head = SHORT_RUSSIAN.encode("cp1251")
    assert len(head) == 11

    from charset_normalizer import detect
    proposed = (detect(head) or {}).get("encoding")
    # `B859`. This used to REQUIRE the detector to answer `Big5` before checking
    # anything, which is an assertion about `charset-normalizer` and not about
    # this product. Measured: `Big5` on 3.4.7, `johab` on 3.5.1 — the version
    # `requirements.txt` pins — and the first CI run that ever completed went
    # red on the precondition while the rule underneath it worked perfectly.
    #
    # The rule is `B201`'s floor: eleven bytes is below it, so whatever
    # multi-byte codec the detector proposed is not taken. Which one it proposed
    # is the library's business. What is asserted is that the product never
    # hands back a decoding that is not the text.
    assert proposed is None or len(head) < dp._MIN_MULTIBYTE_SAMPLE

    answer = sniff_text_encoding(head)
    assert answer is None or head.decode(answer, errors="replace") == SHORT_RUSSIAN
    assert answer != "Big5"
    if proposed is not None:
        assert answer is None or dp._canonical_codec(answer) != dp._canonical_codec(proposed), (
            "a sub-floor multi-byte guess was taken after all"
        )


def test_the_refusal_says_which_kind_of_refusal_it_is():
    """`B162`'s skip-with-a-reason contract, extended to the bytes.

    "We cannot name the encoding of this text" and "these bytes are not text"
    are different things to tell the person who attached the file, and every
    caller that shows a reason needs to be able to tell them apart.
    """
    encoding, reason = describe_text_encoding(SHORT_RUSSIAN.encode("cp1251"))
    assert encoding is None
    assert reason == ENCODING_UNIDENTIFIED

    encoding, reason = describe_text_encoding(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert encoding is None
    assert reason == NOT_TEXT

    assert describe_text_encoding(b"plain ascii") == ("utf-8", "")


@pytest.mark.parametrize("text", [LONGER_RUSSIAN, LONGER_RUSSIAN + " подключение"])
def test_the_same_text_with_enough_bytes_is_still_identified(text):
    """`Law 1`, and the row's second clause: *every file that decodes correctly
    today still does*. 21 bytes was already right and stays right."""
    head = text.encode("cp1251")
    assert len(head) >= 21
    answer = sniff_text_encoding(head)
    assert answer is not None
    assert head.decode(answer, errors="replace") == text


def test_a_short_single_byte_guess_is_left_alone(monkeypatch):
    """The guard is about codecs that regroup bytes, not about short files.

    A single-byte guess cannot change how many characters there are or swallow
    an ASCII letter, so refusing it would cost the accents on every tiny latin-1
    or cp1250 file and buy nothing. Stubbed so the assertion is about the rule
    and not about what this version of the detector happens to answer.
    """
    body = "Grüße Büro".encode("latin-1")
    assert len(body) < MIN_MULTIBYTE_SAMPLE
    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "latin-1")
    assert dp.sniff_text_encoding(body) == "latin-1"


def test_the_same_guess_is_taken_once_the_sample_supports_it(monkeypatch):
    """The floor is a floor, not a ban. One codec, two sample sizes.

    Without this, deleting the length test and refusing every multi-byte guess
    outright would pass every other test in this file.
    """
    short = "設定資料".encode("big5")
    assert len(short) < MIN_MULTIBYTE_SAMPLE
    long = "伺服器連接埠設定資料庫網路組態檔案系統管理員".encode("big5")
    assert len(long) >= MIN_MULTIBYTE_SAMPLE

    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "big5")
    assert dp.sniff_text_encoding(short) is None
    assert dp.sniff_text_encoding(long) == "big5"


def test_the_multibyte_guard_is_not_the_wide_guard_wearing_a_hat(monkeypatch):
    """Two rules, two codec families, and neither covers the other.

    `B101`'s rule refuses UTF-16/32 about NUL-free bytes at any length; this one
    refuses Big5/GB/EUC/Shift-JIS about a short sample. Deleting either must not
    be masked by the other, so each is driven with a guess the other ignores.
    """
    short_cyrillic = SHORT_RUSSIAN.encode("cp1251")
    long_cyrillic = (SHORT_RUSSIAN + " настройка подключение").encode("cp1251")

    # Wide codec, long sample: the wide guard is the only thing that can refuse.
    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "utf_16_be")
    assert dp.sniff_text_encoding(long_cyrillic) != "utf_16_be"

    # Multi-byte codec, short sample: the new guard is the only thing that can.
    monkeypatch.setattr(dp, "_detect_encoding", lambda head: "Big5")
    assert dp.sniff_text_encoding(short_cyrillic) != "Big5"


# ── the reader, which had a second opinion ──────────────────────────────────

def test_the_reader_does_not_take_a_guess_the_probe_refused(tmp_path):
    """The second half of the row, and the half a probe fix alone would miss.

    ``decode_text_file`` ended with ``sniff_text_encoding(head) or
    _detect_encoding(head) or "utf-8"`` — so for any *registered* extension the
    very next expression handed back the same answer the sniff had just
    rejected, overriding the control-char guard, the "must beat UTF-8"
    comparison and this row's rule in one line. `.txt` is registered, so this
    file never meets the probe at all: measured before this row it reached the
    model as ``'鼫謼歑 瀁貗'``.
    """
    path = str(_write(tmp_path, "notes.txt", SHORT_RUSSIAN.encode("cp1251")))
    decoded = decode_text_file(path)
    assert "鼫" not in decoded
    assert decoded == SHORT_RUSSIAN or "�" in decoded


def test_a_bom_less_utf16_file_is_still_rescued_by_the_reader(tmp_path):
    """`Law 1` for the narrowing: the reader's extra call kept the case it was for.

    `B101`'s comment says that second detector call exists because a NUL-laden
    prefix under a registered extension is far more likely to be BOM-less UTF-16
    than a container. That case still works; what stopped is the call firing for
    prefixes with no NUL in them at all, which is every case it was not for.
    """
    text = "SENTINELwideBODY\n" * 4
    path = str(_write(tmp_path, "notes.txt", text.encode("utf-16-le")))
    assert not looks_like_text(path), "the probe should still refuse this"
    decoded = decode_text_file(path)
    assert "SENTINELwideBODY" in decoded
    assert "\x00" not in decoded


def test_a_registered_legacy_file_with_enough_bytes_still_reads(tmp_path):
    """`Law 1`, the ordinary case: nothing about long legacy files changed."""
    russian = "Привет, мир! Конфигурация сервера для отдела продаж.\n"
    path = str(_write(tmp_path, "notes.txt", (russian * 8).encode("cp1251")))
    assert russian.strip() in decode_text_file(path)


# ── the three places a person is told ───────────────────────────────────────

def test_the_composer_banner_says_the_encoding_and_not_the_file_type(tmp_path):
    """*"No extractor covers this file type"* is false about this file.

    The extension is unregistered, so the banner is what the person sees — and
    for a nine-character cp1251 `.conf` the format is supported perfectly well
    and what is missing is a name for the encoding. Before this row the same
    file reached the model as CJK ideographs with no banner at all.
    """
    rendered = _render(tmp_path, "server.conf", SHORT_RUSSIAN.encode("cp1251"))
    assert "server.conf" in rendered
    assert "legacy encoding" in rendered
    assert "No extractor covers this file type" not in rendered
    assert "鼫" not in rendered


def test_a_genuinely_binary_attachment_keeps_the_banner_it_has(tmp_path):
    """The other branch of the same banner, so the new one cannot swallow it."""
    rendered = _render(tmp_path, "blob.unknown",
                       b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64))
    assert "No extractor covers this file type" in rendered
    assert "legacy encoding" not in rendered


def test_the_mailbox_refusal_says_the_encoding_and_not_the_file_type(
        tmp_path, monkeypatch):
    """`Law 13`: the third door tells the person the same thing."""
    result = _drive_mailbox(tmp_path, monkeypatch, "server.conf",
                            SHORT_RUSSIAN.encode("cp1251"))
    assert "doc_id" not in result, result
    assert "encoding" in result["error"]
    assert not result["error"].startswith("Unsupported attachment type")


def test_the_mailbox_still_refuses_a_binary_attachment_by_type(
        tmp_path, monkeypatch):
    result = _drive_mailbox(tmp_path, monkeypatch, "photo.png",
                            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64))
    assert result.get("error") == "Unsupported attachment type: .png"


def test_the_index_reports_which_kind_of_skip_it_was(tmp_path):
    """The reason the operator reads, from the real indexer dispatch.

    ``extract_index_text`` reported ``unsupported extension`` for this file —
    a statement about a format that is not the problem. Both reasons keep the
    file out of the index; only the sentence differs, which is the whole point
    of `B162` reporting a reason at all.
    """
    short = str(_write(tmp_path, "server.conf", SHORT_RUSSIAN.encode("cp1251")))
    binary = str(_write(tmp_path, "blob.unknown",
                        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64)))

    assert personal_docs.extract_index_text(short) == (
        "", SKIP_UNKNOWN_ENCODING)
    assert personal_docs.extract_index_text(binary) == (
        "", SKIP_UNSUPPORTED)
    assert SKIP_UNKNOWN_ENCODING in NOT_LISTED


def test_a_skipped_file_is_still_kept_out_of_the_listing(tmp_path):
    """The new reason had to pick a side, and it picked the same side.

    ``load_personal_index`` lists a file whose extractor produced nothing and
    drops one nothing can read. A reason nobody wired in would silently fall
    into the first group and put an unreadable file in the docs listing with
    zero chunks.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "server.conf").write_bytes(SHORT_RUSSIAN.encode("cp1251"))
    (vault / "notes.md").write_text("SENTINELindexedBODY\n")

    skipped: list = []
    files = personal_docs.load_personal_index(str(vault), skipped=skipped)
    assert [f["name"] for f in files] == ["notes.md"]
    assert {e["reason"] for e in skipped} == {SKIP_UNKNOWN_ENCODING}


# ── `Law 1`, swept ──────────────────────────────────────────────────────────

CORRECT_TODAY = [
    ("cp1251", "сервер порт настройка подключение база данных сеть конфигурация"),
    ("cp1250", "Zażółć gęślą jaźń — plik konfiguracyjny serwera i bazy danych"),
    ("cp1253", "διακομιστής θύρα ρύθμιση σύνδεση βάση δεδομένων δίκτυο αρχείο"),
    ("latin-1", "Grüße vom Büro über die Straße nach München mit größter Sorgfalt"),
    ("big5", "伺服器連接埠設定資料庫網路組態檔案系統管理員密碼變更通知訊息內容"),
    ("gb2312", "服务器端口设置数据库网络配置文件系统管理员密码更改通知消息内容"),
    ("shift_jis", "サーバーポート設定データベースネットワーク構成ファイル管理者"),
    ("euc_kr", "서버포트설정데이터베이스네트워크구성파일시스템관리자비밀번호"),
    ("utf-8", "a plain ascii configuration file\nkey = value\n"),
]


@pytest.mark.parametrize("encoding,text", CORRECT_TODAY)
def test_a_full_length_file_that_decoded_correctly_still_does(
        tmp_path, encoding, text):
    """The row's second `Verify` clause, swept over eight scripts.

    These were all identified correctly on the tree before this row and all of
    them are longer than the floor, which is the argument for where the floor
    is: the guard can only bite a file that is *entirely* shorter than 24 bytes,
    because the sniff is handed the first 8 KiB of everything else.
    """
    body = text.encode(encoding)
    path = str(_write(tmp_path, "notes.txt", body))
    assert text.split()[0] in decode_text_file(path), encoding
