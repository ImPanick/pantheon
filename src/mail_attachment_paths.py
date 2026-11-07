# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where one message's attachments are extracted to disk: one definition.

`B2034`. The routes (`routes/email_helpers.attachment_extract_dir`) and the
agent's mail server (`mcp_servers/email_server._download_attachment`) both
extract attachments under `MAIL_ATTACHMENTS_DIR`, and both named the folder
`<folder>_<uid>` and nothing else. An IMAP UID is a small counter of one
mailbox, so every person's and every account's message 42 in INBOX shared one
folder, and each extraction rewrote the file of the same name that someone
else had just been handed. The agent's door also joined `folder` as given, so
a folder of `../../x` or an absolute name wrote outside the area. The MCP
server runs in its own process and imports `src/`, as it does for
`src/mail_auth.py` and `src/mail_headers.py`, so the rule is here for both.

The folder is `<root>/<scope>/<leaf>`. `scope` is 32 hex characters of a
SHA-256 over the owner and the account, so no two of them share a folder and
no value names its way into another's; `leaf` is the old `<folder>_<uid>`
flattened to `[A-Za-z0-9._-]`, so the place `B1600` calls "where it always
went" still reads as the folder and the UID. Containment is checked after the
path is resolved, so a symlink planted at either level cannot send it
elsewhere. From upstream Odysseus 3d91ad82, which hashes all four values into
one segment.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def attachment_scope_dir(root, folder, uid, *, owner, account_id) -> Path:
    """The folder message `uid` of `folder` is extracted into, for `owner`'s
    `account_id`, resolved. Raises `ValueError` unless it sits exactly two
    levels under `root`."""
    scope = json.dumps([str(owner or ""), str(account_id or "")])
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]
    leaf = re.sub(r"[^A-Za-z0-9._-]", "_", f"{folder}_{uid}")
    base = Path(root).resolve()
    target = (base / digest / leaf).resolve()
    if target.parent.parent != base:
        raise ValueError("attachment folder escapes the extraction root")
    return target
