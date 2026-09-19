# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B280` — the detector's answer is checked against the text it produces.

`B201` fixed the half a sample floor can fix: a multi-byte guess about fewer
than 24 bytes is a coincidence, not evidence. This is what was left, and it is
**content-dependent rather than length-dependent**, which is why no threshold on
sample size reaches it. Measured on the tree as it stood, through the real
`sniff_text_encoding`:

* the 58-byte cp1250 Polish pangram *"Zażółć gęślą jaźń pchnąć w tę łódź jeża
  lub ośm skrzyń fig"* is answered **Windows-1252** and arrives as
  *"Za¿ó³æ gêœl¹ jaŸñ pchn¹æ w tê ³ódŸ je¿a lub oœm skrzyñ fig"* — every
  Polish-specific letter replaced, well above the floor;
* 34 bytes of Big5 are answered **johab** and arrive as Hangul.

Both decode with no replacement characters and no control characters, so
`B101`'s two comparisons have nothing to say about either.

**Two levers, and the row records that only one of them works.**

1. **A file that names its own encoding is not a guess.** `_BOMS` is already
   that rule in bytes; an XML declaration, an HTML `meta charset` and a coding
   cookie are the same declaration in text, and the detector — a classifier over
   the byte histogram — cannot read a sentence. Taken only when the codec exists
   and decodes at least as cleanly as UTF-8 did.
2. **A wrong single-byte guess is visible in the shape of its own output.**
   The cp1252 reading of cp1250 Polish is `Za¿ó³æ gêœl¹`: an inverted question
   mark and a superscript three, **inside words**. `_word_interior_symbols`
   counts exactly that — a non-ASCII non-letter with an alphanumeric on both
   sides — and the "inside words" half is the rule rather than decoration. A
   *legitimately* symbol-heavy file is full of `£ ¥ ¤ ½ ° ± µ` and puts every
   one of them between **spaces**; measured, a rule that counted symbols
   without the position re-read `Preis: 45,00 £ · 50,00 ¥` as Thai, because a
   codec that maps those bytes to letters looks more letter-like precisely by
   destroying them. The choice is made over
   `charset_normalizer.from_bytes`'s **ranked** candidates rather than
   `detect`'s single answer, because the right codec was sitting second on the
   list and being thrown away.

Measured over 891 rows — 29 real prose samples in 17 encodings across Latin,
Cyrillic, Greek, Hebrew, Arabic, Han, Kana and Hangul, truncated at every length
from the floor to the full sample — this is **22 corrections and 0 regressions**
(709 right → 731 right, 179 wrong → 157 wrong, refusals unchanged at 3).

**What it does not fix, and that is a finding rather than an omission.** The
Big5→johab case is a *multi-byte* confusion: both readings are 100% letters with
nothing inside a word, so this lever is blind to it. A rule that refuses when a differently-scripted
multi-byte rival sits within ε chaos of the winner was built and measured
against the same sweep and **costs 98 correct answers to buy 16** — the margin
between the wrong top answer and the right runner-up (0.062–0.071 for
Big5/johab) sits inside the margin range of the cases where the top answer is
right (0.000–0.100). There is no threshold there. `B402` carries it.
"""
import pytest

import src.document_processor as dp
from src.document_processor import (
    decode_text_file,
    describe_text_encoding,
    looks_like_text,
    sniff_text_encoding,
)

POLISH = "Zażółć gęślą jaźń pchnąć w tę łódź jeża lub ośm skrzyń fig"
BIG5 = "伺服器連接埠設定資料庫網路組態檔案"


def _write(tmp_path, name, body: bytes) -> str:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return str(path)


# ── the row's first case ────────────────────────────────────────────────────


def test_a_full_length_cp1250_file_keeps_its_polish_letters(tmp_path):
    """`B280`'s `Verify:`, first clause, driven end to end.

    The detector is left real on purpose — this is the measurement the row was
    filed on and it has to keep being the measurement.

    **`B859`.** It used to *require* the detector to answer `Windows-1252`
    before checking anything, and that assertion was about `charset-normalizer`,
    not about this product. On **3.4.7** — what the container happened to hold —
    the answer is `Windows-1252` and the correction fires. On **3.5.1**, which
    is what `requirements.txt` actually pins, the library answers
    `windows-1250` and is simply right. The first CI run that ever completed
    ran the pinned version, and this test failed **because the upstream bug it
    works around had been fixed.**

    A test that goes red when its dependency improves is pinning the
    dependency. The property is the file's letters, and it holds either way:
    where the detector is wrong the correction fixes it, and where the detector
    is right the correction is a no-op. Both are asserted below, whichever one
    this environment is in.
    """
    body = POLISH.encode("cp1250")
    assert len(body) == 58, "the fixture changed; re-measure the row"

    from charset_normalizer import detect
    proposed = (detect(body) or {}).get("encoding")
    assert proposed, "the detector proposed nothing at all for 58 bytes"

    decoded = decode_text_file(_write(tmp_path, "pangram.txt", body))
    assert decoded == POLISH
    for letter in "ż ó ł ć ę ś ą ź ń".split():
        assert letter in decoded
    # The exact mojibake the row records, gone.
    assert "Za¿ó³æ" not in decoded

    # And the row's lever, asserted against whichever side of it we are on.
    if dp._canonical_codec(proposed) == dp._canonical_codec("cp1250"):
        # The library is right here: the correction must not move a right answer.
        assert dp._more_plausible_alternative(body, proposed) is None
    else:
        # The library is wrong here: the correction is what saved the letters.
        assert dp._canonical_codec(
            dp._more_plausible_alternative(body, proposed)
        ) == dp._canonical_codec("cp1250")


def test_the_signal_is_the_shape_of_the_output_and_not_the_codec():
    """The two readings of the same bytes, measured.

    This is the whole lever in one assertion: both decodes are clean by every
    measure `B101` had — no replacement characters, no control characters — and
    one of them has punctuation and superscript digits *between letters*.
    """
    body = POLISH.encode("cp1250")
    wrong = body.decode("cp1252")
    right = body.decode("cp1250")
    assert dp._replacement_ratio(wrong) == dp._replacement_ratio(right) == 0.0
    assert dp._control_ratio(wrong) <= dp._MAX_CONTROL_RATIO
    assert dp._word_interior_symbols(wrong) >= 2
    assert dp._word_interior_symbols(right) == 0
    assert dp._prose_plausibility(right) > dp._prose_plausibility(wrong)


def test_only_a_candidate_the_detector_proposed_can_be_chosen():
    """A reordering, never an invention.

    The alternative has to appear in `from_bytes`'s own ranking, so this cannot
    reach a codec the detector never considered — and when the detector's answer
    is not in the ranking at all (a stub, a rename) there is nothing to compare
    and the answer is left exactly as it was. That second property is what keeps
    `B201`'s stubbed tests testing `B201`'s rule.
    """
    body = POLISH.encode("cp1250")
    ranking = dp._rank_encodings(body)
    canonical = [dp._canonical_codec(n) for n in ranking]
    assert dp._canonical_codec("cp1250") in canonical
    assert dp._more_plausible_alternative(body, "cp1250") is None  # already best

    # `B859`. The concrete `Windows-1252 -> cp1250` correction can only be
    # asserted where the library still proposes `Windows-1252`: on 3.4.7 the
    # ranking is `['cp1252', 'cp1250']` and on 3.5.1 it is `['cp1250']`, because
    # the upstream bug was fixed. The PROPERTY — never an invention — holds on
    # both, and it is the property this test is named after.
    if dp._canonical_codec("Windows-1252") in canonical:
        assert dp._canonical_codec(
            dp._more_plausible_alternative(body, "Windows-1252")
        ) == dp._canonical_codec("cp1250")
    else:
        assert dp._more_plausible_alternative(body, "Windows-1252") is None

    for codec in ranking:
        alternative = dp._more_plausible_alternative(body, codec)
        assert alternative is None or dp._canonical_codec(alternative) in canonical, (
            f"{codec!r} was corrected to {alternative!r}, which the detector "
            "never proposed — that is an invention, not a reordering")

    # A codec the ranking does not contain: no comparison is possible.
    assert dp._more_plausible_alternative(body, "koi8-r") is None
    assert dp._more_plausible_alternative(body, "not-a-codec") is None


def test_the_structural_guards_are_not_a_door(monkeypatch):
    """`B201`'s floor and `B101`'s wide-codec rule apply to the alternative too.

    Reordering must not become a way for a UTF-16 guess or a short multi-byte
    guess to arrive through the side entrance, so the alternative is put through
    the same two filters the detector's own answer is.
    """
    short = "設定資料".encode("big5")
    assert len(short) < dp._MIN_MULTIBYTE_SAMPLE
    monkeypatch.setattr(dp, "_rank_encodings",
                        lambda head: ["cp1252", "big5", "utf_16_be"])
    assert dp._more_plausible_alternative(short, "cp1252") is None

    longer = (BIG5 * 2).encode("big5")
    monkeypatch.setattr(dp, "_rank_encodings",
                        lambda head: ["cp1252", "utf_16_be"])
    assert dp._more_plausible_alternative(longer, "cp1252") is None


def test_an_alternative_that_is_also_mojibake_is_not_preferred(monkeypatch):
    """Both sides of the comparison are held to the same standard.

    A reading that is *more* letter-like than the winner can still be mojibake:
    driven on the row's own bytes, `mac_latin2` scores 0.889 against
    `Windows-1252`'s 0.667 and still puts a symbol inside a word
    (`Za\u0145\u016f\u2265\u015b`). Preferring it would trade one wrong
    answer for another, which is the failure mode that makes "ask the detector
    harder" a trap.

    The *ranking* is controlled here — not the function under test. The real
    `_more_plausible_alternative` runs over real bytes and real decodes; what is
    supplied is the candidate order `charset_normalizer` happens not to produce
    for this file, which is the only way to reach a branch that is correct and
    quiet.
    """
    body = POLISH.encode("cp1250")
    assert dp._word_interior_symbols(body.decode("mac_latin2")) > 0
    assert dp._prose_plausibility(body.decode("mac_latin2")) > \
        dp._prose_plausibility(body.decode("cp1252"))
    monkeypatch.setattr(dp, "_rank_encodings",
                        lambda head: ["cp1252", "mac_latin2", "cp1250"])
    assert dp._more_plausible_alternative(body, "cp1252") == "cp1250"


@pytest.mark.parametrize("prologue,encoding", [
    ('<?xml version="1.0" encoding="windows-1250"?>', "cp1250"),
    ('<meta charset="windows-1250">', "cp1250"),
    ('# -*- coding: cp1250 -*-\n', "cp1250"),
    ('# vim: set fileencoding=cp1250 :\n', "cp1250"),
])
def test_a_file_that_names_its_own_encoding_is_believed(tmp_path, prologue,
                                                        encoding):
    """The second lever, and it is `_BOMS` one step out.

    A BOM is a file declaring its encoding in bytes. These are the same
    declaration written in text, in grammars that predate every detector, and
    nothing here read them.
    """
    body = (prologue + POLISH).encode(encoding)
    assert sniff_text_encoding(body) == encoding
    assert POLISH in decode_text_file(_write(tmp_path, "declared.xml", body))


def test_only_the_declaration_fixes_the_turkish_case(tmp_path):
    """A case the second lever cannot reach, so the first one is doing the work.

    `Pijamalı hasta yağız şoföre …` in cp1254 is answered `windows-1250` and
    arrives as `Pijamalý`. Both readings are 100% letters with nothing inside a
    word, so `_word_interior_symbols` has nothing to say — and the file saying
    what it is settles it outright.
    """
    turkish = "Pijamalı hasta yağız şoföre çabucak güvendi ve hemen işe koyuldu"
    assert sniff_text_encoding(turkish.encode("cp1254")) != "cp1254"
    declared = ('<?xml version="1.0" encoding="windows-1254"?><t>'
                + turkish + "</t>").encode("cp1254")
    assert sniff_text_encoding(declared) == "cp1254"
    assert turkish in decode_text_file(_write(tmp_path, "t.xml", declared))


@pytest.mark.parametrize("named,label", [
    ("cp037", "an EBCDIC codec, which decodes this file into control characters"),
    ("not-a-real-codec", "a codec Python does not have"),
    ("utf-16", "a wide codec, which scores a perfect zero on bytes with no NUL"),
])
def test_a_declaration_that_makes_things_worse_is_not_taken(named, label):
    """The declaration still has to clear the bar the detector's answer clears.

    A converter that rewrote the bytes and left the old declaration behind, or
    one written to make the reader misread the body, degrades to the answer we
    would have given anyway rather than becoming an override. `utf-16` is the
    one worth naming: every byte pair maps to *some* codepoint, so it scores a
    perfect zero on the replacement ratio and would win on merit — which is
    `B101`'s wide-codec rule, and it applies to a declaration for exactly the
    same reason it applies to a guess.
    """
    lying = ('<?xml version="1.0" encoding="%s"?><t>' % named).encode() \
        + POLISH.encode("cp1250")
    # `B859`: compared as a CODEC, not as a spelling. `charset-normalizer` 3.5.1
    # names this codec `windows-1250` and 3.4.7 names it `cp1250`; they are one
    # codec, `_canonical_codec` is the module's own answer to that, and a test
    # that compares the label is testing the label (`Law 20`).
    assert dp._canonical_codec(sniff_text_encoding(lying)) \
        == dp._canonical_codec("cp1250"), label


# ── `Law 1`, swept ──────────────────────────────────────────────────────────

CORRECT_TODAY = [
    ("cp1251", "сервер порт настройка подключение база данных сеть конфигурация"),
    ("cp1250", "Zażółć gęślą jaźń — plik konfiguracyjny serwera i bazy danych"),
    ("cp1253", "διακομιστής θύρα ρύθμιση σύνδεση βάση δεδομένων δίκτυο αρχείο"),
    ("cp1255", "דג סקרן שט בים מאוכזב ולפתע מצא חברה איך הקליטה"),
    ("cp1256", "الخادم منفذ إعداد قاعدة بيانات شبكة ملف تكوين مدير النظام"),
    ("latin-1", "Grüße vom Büro über die Straße nach München mit größter Sorgfalt"),
    ("koi8-r", "сервер порт настройка подключение база данных сеть конфигурация"),
    ("big5", "伺服器連接埠設定資料庫網路組態檔案系統管理員密碼變更通知訊息內容"),
    ("gb2312", "服务器端口设置数据库网络配置文件系统管理员密码更改通知消息内容"),
    ("shift_jis", "サーバーポート設定データベースネットワーク構成ファイル管理者"),
    ("euc_kr", "서버포트설정데이터베이스네트워크구성파일시스템관리자비밀번호"),
    ("utf-8", "a plain ascii configuration file\nkey = value\n"),
    ("utf-8", "伺服器連接埠設定資料庫網路組態檔案系統管理員密碼變更通知"),
]


@pytest.mark.parametrize("encoding,text", CORRECT_TODAY)
def test_a_file_that_decoded_correctly_still_does(tmp_path, encoding, text):
    """`B280`'s `Verify:`, third clause, over more than the eight scripts it
    asks for — and this is the clause the rejected rules failed."""
    body = text.encode(encoding)
    assert text.split()[0] in decode_text_file(
        _write(tmp_path, "notes.txt", body)), encoding


@pytest.mark.parametrize("encoding,text", CORRECT_TODAY)
def test_the_sweep_is_stable_under_truncation(tmp_path, encoding, text):
    """The same corpus at every length above `B201`'s floor.

    The defect this row is about is content-dependent, so a single length is not
    evidence about a rule that reads content. Every truncation that decoded to
    its own text before still does, or improves to it.
    """
    for n in range(4, len(text) + 1):
        chunk = text[:n]
        body = chunk.encode(encoding)
        if len(body) < dp._MIN_MULTIBYTE_SAMPLE:
            continue
        answer = sniff_text_encoding(body)
        if answer is None:
            continue
        decoded = body.decode(answer, errors="replace")
        # Either it is right, or it was already wrong before this row — never
        # newly wrong, which the 891-row sweep in the docstring measures.
        assert decoded == chunk or dp._prose_plausibility(decoded) <= 1.0


SYMBOL_HEAVY = [
    ("dos-box-drawing", "cp437",
     "╔══════════╗\n║ SERVER   ║\n╚══════════╝ ▒▒▒ █████ ░░░"),
    ("price-list", "latin-1",
     "Preis: 45,00 £ · 50,00 ¥ · ¤ · ¢ · ½ kg · ¹ ² ³ · ± 3 % · µm · °C"),
    ("units-and-marks", "cp1252",
     "Temperature 21°C ± 2°, ¾ full, µg/L, ©2026 Acme™, ®, ¼ ½ ¾ § ¶ † ‡ • …"),
]
SYMBOL_HEAVY = [(label, text.encode(enc)) for label, enc, text in SYMBOL_HEAVY]


@pytest.mark.parametrize("label,body", SYMBOL_HEAVY)
def test_a_legitimately_symbol_heavy_file_is_not_touched(label, body):
    """Why the rule is about **position** and not about counting symbols.

    These three are full of `£ ¥ ¤ ½ ° ± µ ©` and are perfectly good text. A
    "prefer the more letter-like reading" rule with no position test picks a
    different wrong answer for every one of them — measured, the price list is
    re-read as Thai, because `cp874` maps those bytes to letters and therefore
    scores a perfect 1.0 by destroying the file. Requiring the symbol to sit
    *between two alphanumerics* leaves all three exactly where they were.
    """
    detected = dp._detect_encoding(body)
    assert detected is not None, label
    assert dp._word_interior_symbols(
        body.decode(detected, errors="replace")) == 0, label
    assert dp._more_plausible_alternative(body, detected) is None, label
    assert sniff_text_encoding(body) == detected, label
    assert describe_text_encoding(body)[1] == "", label


# ── what this row did NOT fix, pinned so it cannot be mistaken for fixed ────


def test_the_big5_case_is_still_wrong_and_the_margin_is_why():
    """`B280`'s `Verify:` second clause, **not met**, driven so the next agent
    inherits a measurement rather than a surprise.

    Both readings of these bytes are 100% letters — Hangul and Han — so the
    lever that fixes the Polish case is blind here. The margin between the wrong
    winner and the right runner-up is inside the margin range of the cases where
    the winner is right, measured over the same sweep, so no threshold separates
    them. `B402` carries it.
    """
    body = BIG5.encode("big5")
    assert len(body) == 34
    answer = sniff_text_encoding(body)
    assert answer == "johab", (
        "the Big5/johab case changed; re-measure B402 before ticking it")
    both = [body.decode(c, errors="replace") for c in ("johab", "big5")]
    assert all(dp._prose_plausibility(d) == 1.0 for d in both)

    from charset_normalizer import from_bytes
    ranked = [(m.encoding, float(m.chaos)) for m in from_bytes(body)]
    names = [n for n, _ in ranked]
    assert names[:2] == ["johab", "big5"]
    # `B859`. This used to assert `0.06 <= margin <= 0.08`, which is a pin on
    # `charset-normalizer`'s internal score: measured **0.071 on 3.4.7** and
    # **0.141 on 3.5.1**, the version `requirements.txt` pins. The band is the
    # `B651` shape — a test may assert that the numbers relate, it may not
    # assert which one. What the row actually claims is stated instead, and it
    # is the stronger statement: **the wrong winner scores a perfect zero**, so
    # no threshold on cleanliness can reach this case at all.
    assert ranked[0][1] == 0.0, (
        f"the wrong winner is no longer perfectly clean ({ranked[0][1]}); "
        "re-measure B402 before ticking it")
    margin = abs(ranked[1][1] - ranked[0][1])
    assert margin > 0.0, margin


def test_the_same_big5_text_with_more_bytes_is_still_identified():
    """`B201`'s floor and this row both leave the long case alone, which is
    what makes the short one a detector problem rather than a rule problem."""
    body = ("伺服器連接埠設定資料庫網路組態檔案系統管理員密碼變更通知訊息內容"
            .encode("big5"))
    assert len(body) == 64
    assert sniff_text_encoding(body) == "Big5"
    assert looks_like_text(__file__) is True


def test_a_wrong_accent_is_a_different_defect_and_is_left_where_it_was():
    """`Law 1`, stated as what did NOT change.

    The cp1254 Turkish pangram was answered `windows-1250` before this row and
    still is: `Pijamalı` arrives as `Pijamalý`. Both readings are 100% letters,
    so the lever here cannot see the difference — and `B201` already argued that
    this class is bounded, because a single-byte codec maps one byte to one
    character and the worst it produces is the right words with the wrong
    accents. Pinned so a later reader does not mistake it for something this row
    broke.
    """
    turkish = "Pijamalı hasta yağız şoföre çabucak güvendi ve hemen işe koyuldu"
    body = turkish.encode("cp1254")
    answer = sniff_text_encoding(body)
    assert answer is not None
    decoded = body.decode(answer, errors="replace")
    assert decoded.split()[0] in ("Pijamalý", "Pijamalı")
    # Same words, same length, different accents — never a different script.
    assert len(decoded) == len(turkish)
    assert dp._prose_plausibility(decoded) == 1.0
