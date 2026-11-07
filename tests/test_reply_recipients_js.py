# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pin the pure reply-all recipient helpers in emailLibrary/replyRecipients.js.

Driven through `node --input-type=module` so we exercise the real JS without a
full Vitest/Jest setup (same approach as test_compare_js.py). Skips when `node`
is not installed rather than failing.

Regression for issue #360: reply-all dropped every Cc recipient when the user's
own address was unknown, because the old filter used `includes("")` (always
true) instead of an exact-email comparison.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_HELPER = _REPO / "static" / "js" / "emailLibrary" / "replyRecipients.js"
_HAS_NODE = shutil.which("node") is not None


def _run(js: str) -> str:
    proc = subprocess.run(
        ["node", "--input-type=module"],
        input=js, capture_output=True, text=True, cwd=str(_REPO), timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_reply_all_keeps_cc_when_self_unknown():
    data = {"to": "Alice <alice@x.com>, bob@x.com", "cc": "Carol <carol@x.com>"}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, '')));
    """
    cc = json.loads(_run(js))
    # Empty self address must NOT wipe everyone (the #360 bug).
    assert cc == "Alice <alice@x.com>, bob@x.com, Carol <carol@x.com>"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_reply_all_excludes_only_self_exactly():
    data = {"to": "Me <me@x.com>, Alice <alice@x.com>", "cc": "bob@x.com"}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, 'me@x.com')));
    """
    cc = json.loads(_run(js))
    # Our own address is dropped; a substring-similar address is kept.
    assert cc == "Alice <alice@x.com>, bob@x.com"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_reply_all_excludes_all_of_my_addresses():
    # Multi-account user: every one of their own addresses must be excluded,
    # not just the active one.
    data = {"to": "Alice <alice@x.com>, me@work.com", "cc": "me@personal.com, bob@x.com"}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, ["me@work.com", "me@personal.com"])));
    """
    cc = json.loads(_run(js))
    assert cc == "Alice <alice@x.com>, bob@x.com"


# ── `B1964`: a display name with a comma in it is one recipient ──────────────
# Exchange writes `"Smith, John" <john@corp.com>`. Split on every comma, a
# reply-all whose To held my own `"Doe, Jane" <me@x.com>` came out as the Cc
# `"Doe, "Smith, John" <john@corp.com>`, which /send then read as three broken
# addresses. Upstream Odysseus #6910.

_INBOX = _REPO / "static" / "js" / "emailInbox.js"


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_reply_all_leaves_no_fragment_of_my_own_name_with_a_comma():
    data = {"to": '"Doe, Jane" <me@x.com>, "Smith, John" <john@corp.com>', "cc": ""}
    js = f"""
    import {{ buildReplyAllCc }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(buildReplyAllCc({json.dumps(data)}, 'me@x.com')));
    """
    assert json.loads(_run(js)) == '"Smith, John" <john@corp.com>'


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
@pytest.mark.parametrize("raw,expected", [
    (' , "Doe, Jane" <jane@x.com>, , bob@x.com, ', ['"Doe, Jane" <jane@x.com>', "bob@x.com"]),
    ('"last,first"@x.com, bob@x.com', ['"last,first"@x.com', "bob@x.com"]),
    (r'"Name\\" <one@x.com>, two@x.com', [r'"Name\\" <one@x.com>', "two@x.com"]),
    (r'"Doe, \"Jane\"" <jane@x.com>, bob@x.com', [r'"Doe, \"Jane\"" <jane@x.com>', "bob@x.com"]),
    (123, []),
])
def test_the_recipient_splitter_keeps_quoted_names_and_angle_addresses_whole(raw, expected):
    js = f"""
    import {{ splitRecipientList }} from '{_HELPER.as_posix()}';
    console.log(JSON.stringify(splitRecipientList({json.dumps(raw)})));
    """
    assert json.loads(_run(js)) == expected


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_a_reply_from_sent_leaves_no_fragment_of_my_own_name_with_a_comma():
    # The inbox's own split, which a reply from Sent builds its To and Cc from,
    # cut out of emailInbox.js as it ships.
    from tests.helpers.js_source import js_definition

    source = _INBOX.read_text(encoding="utf-8")
    cut = "\n".join(
        js_definition(source, source.index(sig))
        for sig in ("function _splitEmailAddresses(", "function _isMyEmailAddress(",
                    "function _withoutMyAddresses(")
    )
    js = f"""
    import * as recipients from '{_HELPER.as_posix()}';
    const {{ splitRecipientList, extractEmail }} = recipients;
    {cut}
    console.log(JSON.stringify(_withoutMyAddresses(
      '"Doe, Jane" <me@x.com>, "Smith, John" <john@corp.com>', ['me@x.com'])));
    """
    assert json.loads(_run(js)) == ['"Smith, John" <john@corp.com>']
