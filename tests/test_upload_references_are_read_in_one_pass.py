# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1915`. A chat message full of attachment openers held the server for minutes.

Every chat message saved or replaced, and every document, note and calendar
event written, is read for the uploads it references, so that a reference to
an upload the writer does not own is refused (`reserve_upload_references`,
`reserve_message_upload_references`). Two of the three patterns that read
them, `<!-- pdf_source ... upload_id="<id>" -->` and
`[Attachment: name | id=<id> | ...]`, went back to the end of the text from
every opener that never closed, so the work grew with the square of the
length: `[Attachment:` 20,000 times (240 KB) took about 7 seconds, and a
1 MiB chat message about two minutes. The regex engine holds the GIL, so the
scan stalled every other request even on a worker thread.

Now two scanners read the text forward once (ported from upstream Odysseus
3d91ad82; the cases are upstream's). This scan is what the owner check reads,
so the ids must be the ones the old patterns found: the comparisons below run
the old patterns, copied here, as the reference, and pass on the old code and
the new. The floods fail on the old code and pass on the new.
"""
import random
import re
import time

import pytest

from src.upload_handler import INTERNAL_UPLOAD_URL_RE, extract_internal_upload_ids

# Pantheon's patterns before `B1915`, verbatim.
_PDF_REF = re.compile(
    r"<!--\s*pdf(?:_form)?_source\b[^>]*\bupload_id="
    r"[\"']([0-9a-fA-F]{32}(?:\.[A-Za-z0-9]+)?)[\"'][^>]*-->",
    re.IGNORECASE,
)
_ATTACHMENT_REF = re.compile(
    r"\[Attachment:[^\]\r\n]*\|\s*id="
    r"([0-9a-fA-F]{32}(?:\.[A-Za-z0-9]+)?)"
    r"(?:\s*\||\s*\])",
    re.IGNORECASE,
)

_HEX = "a" * 32
_BUDGET_S = 2.0  # the old patterns took 7 s and more on each flood below


def _old_ids(text):
    return (
        set(INTERNAL_UPLOAD_URL_RE.findall(text))
        | set(_PDF_REF.findall(text))
        | set(_ATTACHMENT_REF.findall(text))
    )


@pytest.mark.parametrize("text", [
    f"<!-- pdf_source upload_id='{_HEX}' -->",
    f"<!--PDF_FORM_SOURCE x upload_id=\"{_HEX}.pdf\" y-->",
    f"<!-- pdf_source upload_id='{_HEX}' upload_id='{'b' * 32}' -->",
    f"<!-- pdf_source upload_id='{_HEX}' ->",
    f"<!-- pdf_sourceupload_id='{_HEX}' -->",
    f"<!--pdf_source <!--pdf_source upload_id='{_HEX}'-->",
    "<!-- pdf_source no id -->",
    f"<!-- pdf_source upload_id='{_HEX}' --> then <!-- pdf_form_source upload_id=\"{'c' * 32}.png\" -->",
    f"<!-- pdf_source upload_id='{_HEX}' > -->",
])
def test_a_pdf_source_comment_names_the_upload_the_old_pattern_named(text):
    assert extract_internal_upload_ids(text) == _old_ids(text)


@pytest.mark.parametrize("text", [
    f"[Attachment: report.pdf | id={_HEX} | 12 KB]",
    f"[attachment: a | b | id={_HEX}.txt]",
    f"[Attachment: a | id={_HEX} | id={'b' * 32}]",
    f"[Attachment: x |\nid={_HEX}]",
    f"[Attachment: [Attachment: n | id={_HEX}]",
    f"[Attachment: n | id={_HEX}x]",
    "[Attachment: no id here]",
    f"[Attachment: photo.png | id={_HEX}.png | mime=image/png]\n[Attachment: b | id={'d' * 32}]",
    f"[Attachment: a ] | id={_HEX}]",
])
def test_an_attachment_line_names_the_upload_the_old_pattern_named(text):
    assert extract_internal_upload_ids(text) == _old_ids(text)


_PDF_PIECES = [
    "<!--", "<!-- ", "pdf_source", "PDF_FORM_SOURCE", "pdf_sourcex", " ", "\n",
    "upload_id=", "xupload_id=", "'", '"', ".pdf", "-", "--", "-->", ">", "x",
]
_ATTACHMENT_PIECES = [
    "[Attachment:", "[attachment:", "[", "]", "|", " | ", "\n", "\r", " ",
    "id=", "xid=", ".txt", "x", "/api/upload/",
]
_IDS = [_HEX, "B" * 32, "0123456789abcdefABCDEF0123456789", "a" * 31, "a" * 33]


@pytest.mark.parametrize("pieces", [_PDF_PIECES, _ATTACHMENT_PIECES, _PDF_PIECES + _ATTACHMENT_PIECES],
                         ids=["pdf_source", "attachment", "both"])
def test_random_text_names_the_uploads_the_old_patterns_named(pieces):
    rng = random.Random(1915)
    for _ in range(3000):
        text = "".join(rng.choice(pieces + _IDS) for _ in range(rng.randint(0, 40)))
        assert extract_internal_upload_ids(text) == _old_ids(text), repr(text)


@pytest.mark.parametrize("flood", [
    "[Attachment:" * 20_000,
    "[attachment: a |" * 15_000,
    "<!--pdf_source upload_id=" * 10_000,
    "<!-- pdf_source upload_id=" * 9_000,
], ids=["attachment-openers", "attachment-pipes", "pdf-source-openers", "pdf-source-spaced"])
def test_a_flood_of_unclosed_openers_is_read_in_one_pass(flood):
    started = time.perf_counter()
    assert extract_internal_upload_ids(flood) == set()
    assert time.perf_counter() - started < _BUDGET_S
