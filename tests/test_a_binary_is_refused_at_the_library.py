# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B401` — a binary the browser has no type for is refused at the Library,
with the server's reason, instead of becoming a document of replacement
characters.

`B233` routed the containers the server extracts to `import-office`, and
`B400` refused what the browser itself types `image/`, `audio/` or `video/`;
what was left reached `readFileContent`'s `FileReader.readAsText`. Measured on
`03f50081` with this file's drive: a WordPerfect file (`Annual report.wpd`), a
renamed zip (`backup.dat`) and an untyped binary each became a stored document
of U+FFFD, and the Library said "Imported 1 file". `B232` answered the same
question on the composer path because there is an upload there to probe; a
Library import has none.

Now `importFileAsDocuments` posts the first 8 KiB of a file the register is
silent on to `POST /api/upload/kind`, which writes them to a scratch file under
their name and asks the one probe every door asks (`ingest_kind`); nothing is
stored, and the browser holds no copy of `looks_like_text`. `binary` is refused
with `unread_reason`, the phrase the chat's attachment note uses.

Driven (`Law 20`): the real route through the real router; and the Library's
real reader, per-file import and `libraryImportFiles`, cut out with
`js_source` and run under node against the real routers on a loopback socket
(`test_a_file_imported_from_device_opens_readable.py`'s `live` harness).
"""
import json

import pytest

from tests.test_a_file_imported_from_device_opens_readable import (  # noqa: F401
    _device, _docs, _file, _node, live,
)
from tests.test_an_uploaded_document_keeps_its_name import env  # noqa: F401

# A WordPerfect 6 header and a binary body: what a `.wpd` starts with.
WPD = b"\xffWPC\x10\x00\x00\x00\x01\x0a\x02\x01\x00\x00\x00\x02" + bytes(range(256)) * 8
# A zip renamed to something the register does not know.
ZIP = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + bytes((i * 37) % 256 for i in range(4096))


def _probe(env, name, body):  # noqa: F811
    r = env.client.post("/api/upload/kind", files={"file": (name, body, "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_route_answers_what_the_server_would_make_of_a_file(env):  # noqa: F811
    assert _probe(env, "Annual report.wpd", WPD) == {
        "kind": "binary", "reason": "there is no reader for .wpd files"}
    assert _probe(env, "backup.dat", ZIP)["kind"] == "binary"
    assert _probe(env, "Main.kt", b"fun main() { println(1) }\n") == {"kind": "text", "reason": ""}
    assert _probe(env, "README", b"no suffix at all\n")["kind"] == "text"
    assert _probe(env, "memo.doc", b"\xd0\xcf\x11\xe0")["kind"] == "document"
    # A probe keeps nothing: no upload, no document.
    assert env.handler._load_upload_index() == {}
    assert _docs(env) == []


def test_a_short_legacy_encoded_file_is_not_called_a_format_nothing_reads(env):  # noqa: F811
    """`B201`'s distinction, at this door too: the bytes are text, the name of
    the encoding is what is missing."""
    got = _probe(env, "notes.conf", "Привет".encode("cp1251"))
    if got["kind"] == "binary":
        assert got["reason"] == "its text is in an encoding that could not be identified", got


def _library(env, name, body, mime=""):  # noqa: F811
    """The Library's Import button, one file: what the person was told."""
    path = _file(env, name, body)
    return _node(env.tmp, env.base, f"""
        await libraryImportFiles([fileOf({json.dumps(path)}, {json.dumps(name)}, {json.dumps(mime)})]);
        console.log(JSON.stringify(shown));
    """)


@pytest.mark.parametrize("name,body", [("Annual report.wpd", WPD), ("backup.dat", ZIP),
                                       ("untitled", WPD)],
                         ids=["wpd", "renamed-zip", "no-extension"])
def test_a_binary_dropped_on_the_library_is_refused_with_a_reason(live, name, body):  # noqa: F811
    """`Verify:` a `.wpd` dropped on the library is refused with a reason; it
    does not become a document of replacement characters."""
    shown = _library(live, name, body)
    assert _docs(live) == [], "a binary was stored as a document"
    (said,) = shown["errors"]
    assert said.startswith("Imported 0 files, 1 failed — there is no reader for "), said
    assert live.handler._load_upload_index() == {}, "the probe stored the file"


def test_the_wpd_reason_names_its_format(live):  # noqa: F811
    shown = _library(live, "Annual report.wpd", WPD)
    assert shown["errors"] == ["Imported 0 files, 1 failed — there is no reader for .wpd files"]


def test_text_the_register_does_not_name_still_imports(live):  # noqa: F811
    """The probe is the server's open-ended one: a `.kt` or a file with no
    extension whose bytes are text imports as before."""
    shown = _library(live, "Main.kt", b"fun main() { println(\"KTSENTINEL\") }\n")
    shown2 = _library(live, "NOTES", b"plain words NOSUFFIXSENTINEL\n")
    assert shown["errors"] == [] and shown2["errors"] == [], (shown, shown2)
    contents = [d["content"] for d in _docs(live)]
    assert any("KTSENTINEL" in c for c in contents) and any("NOSUFFIXSENTINEL" in c for c in contents)


def test_import_from_device_refuses_it_the_same_way(live):  # noqa: F811
    """The Documents panel's door imports through the same per-file function
    (`B400`), so it says the same thing."""
    shown = _device(live, "Annual report.wpd", WPD)
    assert shown["errors"] == ["Couldn't import Annual report.wpd — there is no reader for "
                               ".wpd files"], shown
    assert _docs(live) == []
