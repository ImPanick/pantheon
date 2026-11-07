# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1822`, `B1823`. A mail body was read twice, not at all, or as raw markup.

Everything that reads a message's text — the reader and its reply and forward
quote, the AI reply, summaries, auto-translate, the CLI and the agent's
`read_email` — goes through one decode (`src/mail_headers.extract_text`, which
`routes/email_helpers._extract_text` and `mcp_servers/email_server._extract_text`
both are now). It had three faults:

* A part whose charset Python has no codec for (`x-unknown`, `unknown-8bit`,
  `windows-874`, ...) raised `LookupError`, so the reader answered "Mail
  operation failed" and the message could not be opened (`B1822`).
* An HTML-first `multipart/alternative` came back twice (`B1822`).
* A single-part `text/html` message came back as its raw markup, stylesheet
  first (`B1823`).

The first eight tests are upstream Odysseus's (682662d3, #6953), unchanged;
they pass only with both fixes. The rest are Pantheon's: the shape upstream's
own change gets wrong (an HTML post with a plain mailing-list footer), nested
alternatives, link targets, HTML a sender crafted to stall the reader, and the
read route itself, including a body it cached before the fix.
"""
import asyncio
import time
from contextlib import contextmanager
from email import message_from_bytes
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from mcp_servers.email_server import _extract_text as mcp_text
from routes.email_helpers import _extract_html, _extract_text as route_text


def alternative(order, plain='Body text', html='<p>Body text</p>'):
    msg = MIMEMultipart('alternative')
    parts = {'plain': MIMEText(plain, 'plain', 'utf-8'), 'html': MIMEText(html, 'html', 'utf-8')}
    for kind in order:
        msg.attach(parts[kind])
    return message_from_bytes(msg.as_bytes())


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
@pytest.mark.parametrize('order', [('html', 'plain'), ('plain', 'html')])
def test_plain_alternative_wins_in_either_order(extract, order):
    assert extract(alternative(order)) == 'Body text'


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
def test_empty_plain_allows_html_fallback(extract):
    assert extract(alternative(('plain', 'html'), plain='', html='Hello<br>world &amp; all')) == 'Hello\nworld & all'


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
def test_text_attachments_are_not_body_alternatives(extract):
    msg = MIMEMultipart('mixed')
    attachment = MIMEText('Attachment text', 'plain')
    attachment.add_header('Content-Disposition', 'attachment', filename='note.txt')
    msg.attach(attachment)
    msg.attach(MIMEText('<p>Body text</p>', 'html'))
    assert extract(msg) == 'Body text'


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
def test_multiple_plain_body_parts_remain_joined(extract):
    msg = MIMEMultipart('mixed')
    msg.attach(MIMEText('Part one', 'plain'))
    msg.attach(MIMEText('Part two', 'plain'))
    assert extract(msg) == 'Part one\nPart two'


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
@pytest.mark.parametrize('kind', ['plain', 'html'])
@pytest.mark.parametrize('multipart', [False, True])
def test_unknown_charset_falls_back_to_utf8(extract, kind, multipart):
    body = 'Hello café' if kind == 'plain' else '<p>Hello café</p>'
    raw = f'Content-Type: text/{kind}; charset=x-unknown\r\nContent-Transfer-Encoding: 8bit\r\n\r\n'.encode()+body.encode()
    part = message_from_bytes(raw)
    if multipart:
        msg = MIMEMultipart('mixed');msg.attach(part)
    else:
        msg = part
    assert extract(msg) == 'Hello café'


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
def test_declared_latin1_is_preserved(extract):
    assert extract(MIMEText('café', 'plain', 'iso-8859-1')) == 'café'


@pytest.mark.parametrize('multipart', [False, True])
def test_raw_html_unknown_charset_is_readable(multipart):
    part = message_from_bytes(b'Content-Type: text/html; charset=x-unknown\r\n\r\n<p>Hello caf\xc3\xa9</p>')
    if multipart:
        msg=MIMEMultipart('mixed');msg.attach(part)
    else:msg=part
    assert _extract_html(msg) == '<p>Hello café</p>'


@pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])
def test_invalid_bytes_are_replaced_in_unknown_charset(extract):
    msg=message_from_bytes(b'Content-Type: text/plain; charset=x-unknown\r\n\r\nHello\xff')
    assert extract(msg) == 'Hello\ufffd'


# ── Pantheon's cases ───────────────────────────────────────────────────────

EXTRACTORS = pytest.mark.parametrize('extract', [route_text, mcp_text], ids=['route', 'mcp'])


def _parsed(msg):
    return message_from_bytes(msg.as_bytes())


def _raw_part(content_type: bytes, body: bytes):
    return message_from_bytes(b'Content-Type: ' + content_type + b'\r\n'
                              b'Content-Transfer-Encoding: 8bit\r\n\r\n' + body)


@EXTRACTORS
def test_an_html_post_keeps_the_plain_footer_a_mailing_list_adds(extract):
    """Upstream's `text_parts or html_parts` keeps only the footer here."""
    msg = MIMEMultipart('mixed')
    msg.attach(MIMEText('<p>The post</p>', 'html', 'utf-8'))
    msg.attach(MIMEText('-- list footer --', 'plain', 'utf-8'))
    assert extract(_parsed(msg)) == 'The post\n-- list footer --'


@EXTRACTORS
def test_an_alternative_whose_html_is_nested_is_read_once(extract):
    related = MIMEMultipart('related')
    related.attach(MIMEText('<p>Nested</p>', 'html', 'utf-8'))
    msg = MIMEMultipart('alternative')
    msg.attach(related)
    msg.attach(MIMEText('Nested', 'plain', 'utf-8'))
    assert extract(_parsed(msg)) == 'Nested'


@EXTRACTORS
def test_an_alternative_inside_mixed_is_read_once_and_keeps_its_footer(extract):
    body = MIMEMultipart('alternative')
    body.attach(MIMEText('<p>Body</p>', 'html', 'utf-8'))
    body.attach(MIMEText('Body', 'plain', 'utf-8'))
    msg = MIMEMultipart('mixed')
    msg.attach(body)
    msg.attach(MIMEText('-- footer --', 'plain', 'utf-8'))
    assert extract(_parsed(msg)) == 'Body\n-- footer --'


@EXTRACTORS
@pytest.mark.parametrize('raw, text', [(b'caf\xe9', 'café'), (b'caf\xc3\xa9', 'café')],
                         ids=['latin-1', 'utf-8'])
def test_a_body_labelled_unknown_8bit_reads_as_it_was_written(extract, raw, text):
    """The bytes are named the way a header's are (`P23-08`)."""
    assert extract(_raw_part(b'text/plain; charset=unknown-8bit', raw)) == text


@EXTRACTORS
def test_a_plain_body_comes_back_byte_for_byte(extract):
    assert extract(_parsed(MIMEText('  indented\nline\n\n\n\nend  \n', 'plain', 'utf-8'))) == (
        '  indented\nline\n\n\n\nend  \n')


@EXTRACTORS
def test_a_single_part_html_message_is_the_text_a_person_sees(extract):
    page = (b'<html><head><title>Invoice</title><style>p { color: red }</style></head>\r\n'
            b'<body><script>track()</script><h1>Invoice 7</h1>\r\n\r\n\r\n\r\n'
            b'<p>Amount due:&nbsp;12&nbsp;&euro;</p>   \r\n<p>Thanks<br>Ann</p></body></html>')
    assert extract(_raw_part(b'text/html; charset=utf-8', page)) == (
        'Invoice 7\n\nAmount due:\xa012\xa0€\n\nThanks\nAnn')


@EXTRACTORS
def test_a_link_keeps_its_web_or_mail_target_and_loses_any_other(extract):
    page = ('<p>Confirm: <a class="b" href="https://x.test/c?t=1&amp;u=2">click here</a>.'
            ' <a href="javascript:alert(1)">Run</a> <a href=\'mailto:ann@x.test\'>Write</a>'
            ' <a href="mailto:bo@x.test">bo@x.test</a> <a href="/relative">Here</a>'
            ' <a data-href="https://wrong.test/" href=https://x.test/b>B</a></p>')
    assert extract(_parsed(MIMEText(page, 'html', 'utf-8'))) == (
        'Confirm: click here <https://x.test/c?t=1&u=2>. Run Write <mailto:ann@x.test>'
        ' bo@x.test Here B <https://x.test/b>')


@EXTRACTORS
def test_html_beside_an_attachment_is_read_without_its_stylesheet(extract):
    msg = MIMEMultipart('mixed')
    msg.attach(MIMEText('<style>p { color: red }</style><p>Invoice attached</p>', 'html', 'utf-8'))
    pdf = MIMEApplication(b'%PDF-1.4', 'pdf')
    pdf.add_header('Content-Disposition', 'attachment', filename='invoice.pdf')
    msg.attach(pdf)
    assert extract(_parsed(msg)) == 'Invoice attached'


# Unclosed anchors and styles, a run of spaces and a run of bare `<`: each is a
# shape that a lazy anchor or style pattern, `[ \t]+\n` or `<[^>]+>` scans to
# the end of the text from every position, which turns a big message into
# minutes on the reader's thread.
CRAFTED = ('<p>Hello</p>' + '<a href="https://example.test/">' * 5_000 + ' ' * 100_000
           + '<style' * 20_000 + '<' * 120_000)


@EXTRACTORS
@pytest.mark.parametrize('multipart', [False, True], ids=['single', 'multipart'])
def test_html_a_sender_crafted_does_not_stall_the_reader(extract, multipart):
    part = MIMEText(CRAFTED, 'html', 'utf-8')
    if multipart:
        msg = MIMEMultipart('mixed')
        msg.attach(part)
        part = msg
    msg = _parsed(part)
    started = time.monotonic()
    text = extract(msg)
    elapsed = time.monotonic() - started
    assert elapsed < 3.0, f'{elapsed:.1f} s'
    assert text.startswith('Hello')


# ── The read route ─────────────────────────────────────────────────────────

def _route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if route.path == path and method in getattr(route, 'methods', set()):
            return route.endpoint
    raise AssertionError(f'route not found: {method} {path}')


def _message(content_type: bytes, body: bytes) -> bytes:
    return (b'From: Sender <sender@example.test>\r\n'
            b'To: Alice <alice@example.test>\r\n'
            b'Subject: A message\r\n'
            b'Message-ID: <body-decoding@example.test>\r\n'
            b'Date: Tue, 04 Aug 2026 12:00:00 +0000\r\n'
            b'Content-Type: ' + content_type + b'\r\n'
            b'Content-Transfer-Encoding: 8bit\r\n\r\n' + body)


class _OneMessage:
    """An IMAP connection holding one message, as the reader fetches it."""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.fetches = 0

    def select(self, mailbox, readonly=False):
        return 'OK', [b'1']

    def uid(self, command, uid, *args):
        assert command == 'FETCH', command
        self.fetches += 1
        header, body = self.raw.split(b'\r\n\r\n', 1)
        return 'OK', [(b'1 (UID 42 BODY[HEADER])', header + b'\r\n\r\n'),
                      (b'1 (UID 42 BODY[TEXT]<0>)', body)]


def _read(monkeypatch, tmp_path, raw: bytes, *, persisted=None):
    import routes.email_helpers as email_helpers
    import routes.email_routes as email_routes

    monkeypatch.setattr(email_helpers, 'SCHEDULED_DB', tmp_path / 'email.db')
    monkeypatch.setattr(email_routes, 'SCHEDULED_DB', tmp_path / 'email.db')
    email_helpers._init_scheduled_db()
    conn = _OneMessage(raw)

    @contextmanager
    def fake_imap(account_id=None, owner=''):
        yield conn

    monkeypatch.setattr(email_routes, '_start_poller', lambda: None)
    monkeypatch.setattr(email_routes, '_imap', fake_imap)
    monkeypatch.setattr(email_routes, '_email_preview_cache_get', lambda *_a, **_k: persisted)
    monkeypatch.setattr(email_routes, '_email_preview_cache_put', lambda *_a, **_k: None)
    monkeypatch.setattr(email_routes, '_email_attachment_meta_cache_get', lambda *_a, **_k: None)
    monkeypatch.setattr(email_routes, '_email_attachment_meta_cache_put', lambda *_a, **_k: None)
    read_email = _route_endpoint(email_routes.setup_email_routes(), '/api/email/read/{uid}', 'GET')
    result = asyncio.run(read_email('42', folder='INBOX', account_id='acct-a', mark_seen=False,
                                    full=False, owner='alice'))
    return result, conn


def test_the_reader_opens_a_message_whose_charset_python_does_not_know(monkeypatch, tmp_path):
    result, _ = _read(monkeypatch, tmp_path,
                      _message(b'text/plain; charset=x-unknown', b'Hello caf\xc3\xa9'))
    assert 'error' not in result, result
    assert result['body'].strip() == 'Hello café'


def test_the_reader_gives_a_single_part_html_message_as_text(monkeypatch, tmp_path):
    page = (b'<html><head><style>p { color: red }</style></head>'
            b'<body><p>Hello <b>Ann</b></p></body></html>')
    result, _ = _read(monkeypatch, tmp_path, _message(b'text/html; charset=utf-8', page))
    assert result['body'] == 'Hello Ann'
    assert result['body_html'].strip() == page.decode()  # the reader still renders the markup


def test_a_body_cached_before_this_fix_is_read_again(monkeypatch, tmp_path):
    """The preview cache never expires; only its version retires an entry."""
    raw = _message(b'multipart/alternative; boundary="b"',
                   b'--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Body text</p>\r\n'
                   b'--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nBody text\r\n--b--\r\n')
    stale = {'uid': '42', 'folder': 'INBOX', 'message_id': '<body-decoding@example.test>',
             'body': 'Body text\nBody text', 'body_html': '<p>Body text</p>',
             'attachments': [], 'attachment_version': 2}
    result, conn = _read(monkeypatch, tmp_path, raw, persisted=stale)
    assert conn.fetches == 1
    assert result['body'] == 'Body text'
