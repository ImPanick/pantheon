# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1902`. A mail of unclosed `<` held the server for as long as it took.

Mail text went through the flat tag strip `re.sub(r"<[^>]+>", "", text)` and
header values through `re.findall(r"<([^>]+)>", value)`. Both rescan to the
end of the text from every `<` that has no `>` after it, so their time grows
with the square of the input. Measured on `62c93ba2`: 80,000 `<` took 8.5 s to
strip and 57 s to `findall`. Listing the inbox reads the newest messages'
bodies (`_extract_text`, an HTML part with no plain part beside it), so anyone
who can send the person mail could stall the server; a `to_thread` does not
help, the regex holds the GIL.

Now each of them goes through `src.tool_parsing.strip_angle_tags` or
`iter_angle_tags`, the forward-only scan the tool parser already reads its
delimited patterns with (`Law 14`): it stops as soon as no `>` is left.

  * the `In-Reply-To`/`References` chain (`routes/email_routes._message_id_chain`);
  * the `List-Unsubscribe` header, in both of those modules;
  * an integration's HTML answer (`src/integrations._strip_html_tags`).

The body of a message, read by the app and by the email MCP server, is
`src.mail_headers.extract_text` on this branch (`B1822`, `B1823`), whose tag
strip is already linear and tested with its own cases; it is still timed here.

Two halves: the scan finds and strips exactly what the old patterns did, and
200,000 `<` go through every one of those places within a 4 s budget, timed
in a fresh interpreter so the old code is killed rather than waited for.
`strip_angle_tags` is upstream Odysseus da3800b6's; the call sites are
Pantheon's.
"""

import itertools
import random
import re

import src.agent_tools  # noqa: F401  (break agent_tools<->tool_parsing import cycle)
# The module, not its helpers: on the tree before `B1902` they are not there,
# and the flood below must still run there, and fail.
import src.tool_parsing as tool_parsing
from tests.helpers.timed_process import seconds_in_a_fresh_process

_BUDGET_S = 4.0

_CASES = ["before<b>bold</b>after", "<>", "<<>>", "a<x\ny>b", "<broken", "<a><b>one</b></a>",
          "a > b", "<x title='>'>tail", "<mailto:a@example.com>, <https://example.com/u?t=1>",
          "<1@example.com> <2@example.com>\r\n\t<1@example.com>"]
_CASES += ["".join(parts) for n in range(7) for parts in itertools.product("a<>\n", repeat=n)]
_rng = random.Random(1902)
_CASES += ["".join(_rng.choices(["<", ">", "<>", "a", " ", "\n", "<b>", "@"], k=_rng.randint(0, 20)))
           for _ in range(5000)]


def test_every_strip_and_scan_finds_what_the_old_patterns_found():
    import mcp_servers.email_server as server
    from routes.email_routes import _message_id_chain, _parse_list_unsubscribe_header
    from src.integrations import _strip_html_tags

    for allow_empty, replacement in itertools.product((False, True), ("", " ")):
        pattern = re.compile(r"<[^>]*>" if allow_empty else r"<[^>]+>")
        for text in _CASES:
            assert tool_parsing.strip_angle_tags(text, replacement, allow_empty=allow_empty) == (
                pattern.sub(replacement, text)), repr(text)
    for text in _CASES:
        old = [(m.start(), m.start(1), m.end(1), m.end()) for m in re.finditer(r"<([^>]+)>", text)]
        assert list(tool_parsing.iter_angle_tags(text)) == old, repr(text)

    # And through the places that call them.
    for body in ("<p>Hello <b>you</b>,<br>the <a href='x'>report</a> &amp; notes.</p>",
                 "<div>2 < 3 and 5 > 4</div><br/>tail <unclosed", "plain", "<<>>&lt;b&gt;"):
        assert _strip_html_tags(body) == re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip()
    header = "<a@example.com> <b@example.com>\r\n <a@example.com> stray < and <c@example.com"
    assert _message_id_chain(header, "<d@example.com>") == [
        "<a@example.com>", "<b@example.com>", "<d@example.com>"]
    unsubscribe = "<mailto:list@example.com?subject=unsubscribe>, <https://example.com/u/t>"
    for parse in (_parse_list_unsubscribe_header, server._parse_list_unsubscribe_header):
        assert [(m["kind"], m["target"]) for m in parse(unsubscribe)] == [
            ("mailto", "list@example.com"), ("url", "https://example.com/u/t")]


def test_a_mail_of_unclosed_angle_brackets_is_read_within_the_budget():
    seconds = seconds_in_a_fresh_process(
        "import src.agent_tools\n"
        "from email.mime.multipart import MIMEMultipart\n"
        "from email.mime.text import MIMEText\n"
        "import mcp_servers.email_server as server\n"
        "from routes.email_helpers import _extract_text\n"
        "from routes.email_routes import _message_id_chain, _parse_list_unsubscribe_header\n"
        "from src.integrations import _strip_html_tags\n"
        "flood = '<' * 200_000\n"
        "mail = MIMEMultipart('alternative')\n"
        "mail.attach(MIMEText(flood, 'html', 'utf-8'))",
        # Each place prints as it finishes, so a run killed at the deadline
        # says which one it was still in.
        "for name, read in (('the app reads the body', lambda: _extract_text(mail)),\n"
        "                   ('the MCP server reads the body', lambda: server._extract_text(mail)),\n"
        "                   ('the reply chain', lambda: _message_id_chain(flood, flood)),\n"
        "                   ('List-Unsubscribe', lambda: _parse_list_unsubscribe_header(flood)),\n"
        "                   ('the MCP List-Unsubscribe', lambda: server._parse_list_unsubscribe_header(flood)),\n"
        "                   ('an integration answer', lambda: _strip_html_tags(flood))):\n"
        "    read()\n"
        "    print(name, 'done', flush=True)",
    )
    assert seconds < _BUDGET_S, f"{seconds:.1f} s"
