# SPDX-License-Identifier: AGPL-3.0-or-later
# src/report_math.py
"""`B1996`. Keep a research report's TeX for the chat's own math renderer.

A Deep Research report is Markdown the model writes, and for maths, science or
finance it writes formulas in TeX. `src.visual_report._md_to_html` ran that
through Python-Markdown, which has no idea of math: `$a*b*c$` came out as
`$a<em>b</em>c$`, `\\(\\alpha\\)` and `\\[ … \\]` lost their delimiters to
Markdown's backslash escapes, and a heading's `$x_i$` reached the table of
contents as `$xi$`. The report page typeset nothing.

`ReportMathExtension` finds the delimiters `static/js/markdown.js` finds —
`\\[…\\]`, `\\(…\\)`, `$$…$$` and `$…$`, with the same currency rule — before
Markdown can rewrite them, and leaves each formula's source as plain text in a
placeholder span of class `MATH_PENDING_CLASS`. The report page hands those to
`renderMath` in `static/js/markdown/math.js`, the renderer the chat uses, over
the vendored KaTeX.

A display formula carries `MATH_DISPLAY_CLASS` as well. markdown.js marks one
with `data-display`, but the report's HTML goes through the nh3 report
sanitiser (`FORBIDDEN.md` Part 2) and a class passes its allowlist as it
stands; the page sets `data-display` from the class after sanitising.

Left alone: code spans, fenced and indented code, raw `<code>`/`<pre>`, tag
attributes, link destinations, a backslash-escaped `$`, and an unclosed `$$`.

Ported from upstream Odysseus 06c1e71f (#6929), whose placeholder carried
upstream's own class name and marked a display formula with `data-display`.
"""
import re
from html.parser import HTMLParser
from xml.etree import ElementTree

from markdown.blockprocessors import BlockProcessor
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.util import AtomicString

#: The placeholder `renderMath` swaps for typeset math. The same string as
#: `MATH_PENDING_CLASS` in `static/js/markdown/math.js`.
MATH_PENDING_CLASS = "pan-math-pending"
#: Beside it on a formula set on its own line.
MATH_DISPLAY_CLASS = "pan-math-display"

# Keep delimiter and currency rules aligned with mathBlocks in markdown.js.
_ESCAPED_MATH = r"\\\[([\s\S]*?)\\\]|\\\(([^\n]*?)\\\)"
_DOLLAR_MATH = (
    r"\$\$([\s\S]*?)\$\$|"
    r"(?<![\$\d])\$(?!\$)(?=\S)([^\$\n]+?)(?<=\S)\$(?!\$|\d)"
)


def _placeholder(tex, display):
    classes = MATH_PENDING_CLASS + (" " + MATH_DISPLAY_CLASS if display else "")
    node = ElementTree.Element("span", {"class": classes})
    node.text = AtomicString(tex)
    return node


class _HtmlContext(HTMLParser):
    """Inline HTML is still raw when math runs, including tag attributes."""
    def __init__(self):
        super().__init__()
        self.protected = []

    def handle_starttag(self, tag, attrs):
        if tag in {"code", "pre", "script", "style", "textarea"}:
            self.protected.append(tag)

    def handle_endtag(self, tag):
        if tag in self.protected:
            del self.protected[self.protected.index(tag):]


class _InlineMath(InlineProcessor):
    def handleMatch(self, match, data):
        prefix = data[:match.start()]
        if "<" in prefix:
            context = _HtmlContext()
            context.feed(prefix)
            if context.protected or re.match(r"<(?:/?[A-Za-z]|[!?])", context.rawdata.lstrip()):
                return None, None, None
        # Backticks run before this processor. Preserve a backslash-escaped
        # dollar too; math must run before Markdown consumes \( and \[.
        if prefix.endswith("\\") and (len(prefix) - len(prefix.rstrip("\\"))) % 2:
            return None, None, None
        tex = next(group for group in match.groups() if group is not None)
        display = match.group(1) is not None
        return _placeholder(tex, display), match.start(), match.end()


class _DisplayMath(BlockProcessor):
    def test(self, parent, block):
        return re.match(r"^ {0,3}(\$\$|\\\[)", block) is not None

    def run(self, parent, blocks):
        opening = re.match(r"^ {0,3}(\$\$|\\\[)", blocks[0])
        closing = "$$" if opening.group(1) == "$$" else "\\]"
        source = blocks[0][opening.end():]
        consumed = 1
        while closing not in source:
            if consumed == len(blocks):
                return False  # Leave incomplete input to ordinary Markdown.
            source += "\n\n" + blocks[consumed]
            consumed += 1
        tex, _, tail = source.partition(closing)
        del blocks[:consumed]
        if tail.strip():
            blocks.insert(0, tail)
        parent.append(_placeholder(tex, True))


class ReportMathExtension(Extension):
    def extendMarkdown(self, md):
        # Backticks (190) and indented code (80) retain precedence.
        md.inlinePatterns.register(_InlineMath(_ESCAPED_MATH, md), "report_math_escaped", 185)
        # Parse links before dollar math so URL destinations stay literal.
        md.inlinePatterns.register(_InlineMath(_DOLLAR_MATH, md), "report_math_dollar", 155)
        md.parser.blockprocessors.register(_DisplayMath(md.parser), "report_math", 79)
