# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency-free `.docx` and `.xlsx` readers, written to give the server the
document the Library's browser converters give — and, since `B1178`/`B1289`,
`.ods`, `.xls`, `.pptx` and `.epub` readers beside them (their sections below).

`B1156` (f-import: on a default install one `.docx` is two documents and one
`.xlsx` a document or a refusal, depending on the door). markitdown is optional
and the default image does not install it, and `python-docx` is not in
`requirements.txt`. Measured with LibreOffice's files
(`tests/helpers/office_fixtures.py`): the Library and *Import from device*
convert in the browser with the vendored mammoth and SheetJS — `# Quarterly
Report`, `## Highlights`, `- Revenue rose…`, a table; and a CSV — while every
server door (`import-office`, the chat's auto-document, a chat chip's *open as
document*, the mailbox's `attachment-as-doc`) read the same `.docx` with the
bare `<w:t>` walk (paragraphs, no headings) and answered the `.xlsx` with
*"requires markitdown"*.

**Why the server reads them, rather than the doors sharing the browser's
path.** Two of the doors have no browser: the chat's auto-document is made, and
the model is given the file's text, inside `build_user_content` on the server,
and the agent opens a mail attachment through the same route. Sharing the
browser path would leave the model reading *"requires markitdown"* for a
spreadsheet. No converter for either format is declared in `requirements.txt`
(`pypdf`, `beautifulsoup4`, `markdown`, `nh3` — none reads OOXML), so the one
already there is the standard library: a `.docx`/`.xlsx` is a zip of XML, and
`B102` read `.odt` and `.doc` the same way. These are rungs of
`markitdown_runtime._NATIVE_EXTRACTORS` (`Law 14`), tried when markitdown is not
installed; with it installed, markitdown answers as before.

**What "the same document" means here, measured rather than intended.** The
`.docx` reader follows mammoth's default style map and the Library's
`htmlToMarkdown` (`static/js/documentLibrary.js`): heading styles 1–4 as `#` to
`####`, paragraphs, bullet and numbered lists (bullet or not read from the
numbering part), tables as pipe rows with a `| --- |` rule after the first, bold
`**`, italic `*`, links `[text](target)`, line breaks, an image's alt text; empty
paragraphs dropped. The `.xlsx` reader is SheetJS's `sheet_to_csv`: one line per
row of the used range, RFC 4180 quoting, each number shown through its cell's
number format — General, the placeholder formats (`0`, `0.00`, `#,##0.00`,
percent, literals and currency tags around them) and dates and times — ported
with SheetJS's own rounding. Driven against SheetJS on 3,013 values in fifteen
formats: identical below 10^11; above, where `v * 10^d` passes a double's 53
bits, the two disagree in the last digit (`test_one_office_file_is_one_
document_at_every_door.py`). A fraction or scientific format falls back to
General.

Bounded, like the other readers in `markitdown_runtime`: each part is read up to
`PART_LIMIT` bytes and a part declaring an XML entity is refused
(`_parse_office_xml`), so an attachment cannot become an out-of-memory.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
import zipfile
from decimal import Decimal, ROUND_HALF_UP

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Decompressed bytes read from any one part. A zip's declared sizes can lie;
# the read stops here whatever the header says.
PART_LIMIT = 64 * 1024 * 1024


def _part(z: zipfile.ZipFile, name: str):
    """Parse one XML part of the package, or None (missing, oversized, refused)."""
    from src.markitdown_runtime import _parse_office_xml

    try:
        with z.open(name) as fh:
            data = fh.read(PART_LIMIT + 1)
    except (KeyError, zipfile.BadZipFile, OSError, RuntimeError):
        return None
    if len(data) > PART_LIMIT:
        return None
    return _parse_office_xml(data)


# ── .docx ──────────────────────────────────────────────────────────────────


def _toggle(el) -> bool:
    """`w:b` / `w:i`: present and not switched off."""
    if el is None:
        return False
    # flag-spelling: not ours. `w:val` is the document's own XML (ECMA-376
    # `ST_OnOff`), and the words that switch a run's bold or italic off are the
    # ones mammoth — the Library's converter — honours: `readBooleanElement`
    # reads anything but "false" and "0" as on. "off" was read as off here too
    # until the release gate asked; now both doors bold the same run.
    return el.get(W + "val") not in ("0", "false")


def docx_markdown(path: str) -> str | None:
    """The `.docx` as markdown, the way the Library's import writes it."""
    try:
        with zipfile.ZipFile(path) as z:
            doc = _part(z, "word/document.xml")
            styles = _part(z, "word/styles.xml")
            numbering = _part(z, "word/numbering.xml")
            rels = _part(z, "word/_rels/document.xml.rels")
    except (zipfile.BadZipFile, OSError):
        return None
    if doc is None:
        return None
    body = doc.find(W + "body")
    if body is None:
        return None

    style_name = {}
    if styles is not None:
        for st in styles.iter(W + "style"):
            n = st.find(W + "name")
            style_name[st.get(W + "styleId")] = (n.get(W + "val") if n is not None else "") or ""
    targets = {}
    if rels is not None:
        for r in rels.iter(PKG + "Relationship"):
            if r.get("TargetMode") == "External":
                targets[r.get("Id")] = r.get("Target") or ""
    num_abstract, abstract_formats = {}, {}
    if numbering is not None:
        for a in numbering.iter(W + "abstractNum"):
            formats = {}
            for lvl in a.iter(W + "lvl"):
                f = lvl.find(W + "numFmt")
                formats[lvl.get(W + "ilvl")] = f.get(W + "val") if f is not None else "decimal"
            abstract_formats[a.get(W + "abstractNumId")] = formats
        for n in numbering.iter(W + "num"):
            a = n.find(W + "abstractNumId")
            if a is not None:
                num_abstract[n.get(W + "numId")] = a.get(W + "val")

    def heading_level(p) -> int:
        ppr = p.find(W + "pPr")
        ps = ppr.find(W + "pStyle") if ppr is not None else None
        sid = ps.get(W + "val") if ps is not None else ""
        name = style_name.get(sid, sid) or ""
        m = (re.fullmatch(r"heading\s*([1-9])", name.strip(), re.I)
             or re.fullmatch(r"Heading([1-9])", sid or ""))
        return int(m.group(1)) if m else 0

    def list_kind(p):
        ppr = p.find(W + "pPr")
        num = ppr.find(W + "numPr") if ppr is not None else None
        if num is None:
            return None
        nid_el, lvl_el = num.find(W + "numId"), num.find(W + "ilvl")
        nid = nid_el.get(W + "val") if nid_el is not None else None
        if not nid or nid == "0":            # numId 0 switches numbering off
            return None
        lvl = lvl_el.get(W + "val") if lvl_el is not None else "0"
        fmt = abstract_formats.get(num_abstract.get(nid), {}).get(lvl, "decimal")
        return "ul" if fmt == "bullet" else "ol"

    def inline(container) -> str:
        """Runs as markdown; neighbours with the same formatting merged, as
        mammoth merges them before `htmlToMarkdown` sees them."""
        pieces = []                          # (text, bold, italic, href)

        def walk(el, href=None):
            for child in el:
                tag = child.tag
                if tag == W + "r":
                    rpr = child.find(W + "rPr")
                    bold = _toggle(rpr.find(W + "b")) if rpr is not None else False
                    ital = _toggle(rpr.find(W + "i")) if rpr is not None else False
                    for part in child:
                        if part.tag == W + "t":
                            pieces.append((part.text or "", bold, ital, href))
                        elif part.tag == W + "tab":
                            pieces.append(("\t", bold, ital, href))
                        elif part.tag in (W + "br", W + "cr"):
                            pieces.append(("\n", False, False, href))
                        elif part.tag == W + "drawing":
                            for dp in part.iter(WP + "docPr"):
                                if dp.get("descr"):
                                    pieces.append((f"*[image: {dp.get('descr')}]*", False, False, None))
                elif tag == W + "hyperlink":
                    rid = child.get(R + "id")
                    target = targets.get(rid) if rid else None
                    if target is None and child.get(W + "anchor"):
                        target = "#" + child.get(W + "anchor")
                    walk(child, target)
                elif tag in (W + "ins", W + "smartTag", W + "sdt", W + "sdtContent", W + "fldSimple"):
                    walk(child, href)

        walk(container)
        merged = []
        for t, b, i, h in pieces:
            if merged and merged[-1][1:] == (b, i, h):
                merged[-1] = (merged[-1][0] + t, b, i, h)
            else:
                merged.append((t, b, i, h))
        out = []
        for t, b, i, h in merged:
            s = f"*{t}*" if i else t
            s = f"**{s}**" if b else s
            out.append(f"[{s}]({h})" if h is not None else s)
        return "".join(out)

    md: list[str] = []
    open_list = None                         # [kind, items so far]

    def blocks(parent) -> None:
        nonlocal open_list
        for el in parent:
            if el.tag == W + "p":
                text = inline(el)
                kind = list_kind(el)
                if kind:
                    if open_list is None or open_list[0] != kind:
                        md.append("\n")
                        open_list = [kind, 0]
                    open_list[1] += 1
                    md.append(("- " if kind == "ul" else f"{open_list[1]}. ") + text + "\n")
                    continue
                open_list = None
                if not text.strip():
                    continue                 # mammoth drops an empty paragraph
                level = heading_level(el)
                md.append("\n" + ("#" * min(level, 4) + " " if level else "") + text + "\n")
            elif el.tag == W + "tbl":
                open_list = None
                rows = [["".join(inline(p) for p in tc.iter(W + "p")).strip()
                         for tc in tr.findall(W + "tc")] for tr in el.findall(W + "tr")]
                if not rows:
                    continue
                md.append("\n")
                for k, cells in enumerate(rows):
                    md.append("| " + " | ".join(cells) + " |\n")
                    if k == 0:
                        md.append("| " + " | ".join("---" for _ in cells) + " |\n")
                md.append("\n")
            elif el.tag in (W + "sdt", W + "sdtContent", W + "customXml"):
                blocks(el)

    blocks(body)
    text = re.sub(r"\n{3,}", "\n\n", "".join(md)).strip()
    return text or None


# ── .xlsx: number formats (the part of SheetJS's SSF a ledger uses) ─────────

# SheetJS's table of built-in format ids (`SSF._table`), the ones a sheet uses.
_BUILTIN_FORMATS = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%",
    11: "0.00E+00", 14: "m/d/yy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy",
    18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "m/d/yy h:mm",
    37: "#,##0 ;(#,##0)", 38: "#,##0 ;(#,##0)", 39: "#,##0.00;(#,##0.00)",
    40: "#,##0.00;(#,##0.00)", 45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0",
    49: "@",
}
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"]
_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_PLACEHOLDERS = r"[0#][0#,]*(?:\.[0#]*)?|\.[0#]+"


def _tokens(code: str):
    """A format section as `(kind, text)`: `lit` for literal text, `code` for a
    format character. Quoted text and `\\x` are literals, `_x` a space, `*x`
    nothing; `[$€-407]` is its symbol; other `[...]` tags (colours) vanish."""
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c == '"':
            j = code.find('"', i + 1)
            j = n if j < 0 else j
            out.append(("lit", code[i + 1:j]))
            i = j + 1
        elif c == "\\" and i + 1 < n:
            out.append(("lit", code[i + 1]))
            i += 2
        elif c == "_" and i + 1 < n:
            out.append(("lit", " "))
            i += 2
        elif c == "*" and i + 1 < n:
            i += 2
        elif c == "[":
            j = code.find("]", i)
            j = n if j < 0 else j
            tag = code[i + 1:j]
            if re.fullmatch(r"h+|m+|s+", tag, re.I):
                out.append(("code", tag))
            elif tag.startswith("$"):
                out.append(("lit", tag[1:].split("-")[0]))
            i = j + 1
        else:
            out.append(("code", c))
            i += 1
    return out


def _is_date(tokens) -> bool:
    numeric = any(k == "code" and t in "0#?" for k, t in tokens)
    return any(k == "code" and (t.lower() in "ydhs" or (t.lower() == "m" and not numeric))
               for k, t in tokens)


def _serial_to_datetime(v: float, date1904: bool):
    epoch = _dt.datetime(1904, 1, 1) if date1904 else _dt.datetime(1899, 12, 30)
    if not date1904 and v < 60:
        epoch = _dt.datetime(1899, 12, 31)   # before Excel's 29 February 1900
    return epoch + _dt.timedelta(days=v)


class _NotADay:
    """Excel's day 0 (`1/0/00`) and its 29 February 1900, which never were;
    SheetJS prints both, so this does too."""

    def __init__(self, year, month, day, rest):
        self.year, self.month, self.day = year, month, day
        self.hour, self.minute, self.second = rest.hour, rest.minute, rest.second


def _format_date(v: float, tokens, date1904: bool) -> str:
    if v < 0 or v > 2958465:
        return ""                            # SheetJS: no such date
    d = _serial_to_datetime(v, date1904)
    secs = round((d - d.replace(microsecond=0)).total_seconds())
    d = d.replace(microsecond=0) + _dt.timedelta(seconds=secs)
    if not date1904 and int(v) == 0:
        d = _NotADay(1900, 1, 0, d)
    elif not date1904 and int(v) == 60:
        d = _NotADay(1900, 2, 29, d)
    text = "".join(t if k == "code" else "\x00" + t + "\x01" for k, t in tokens)
    ampm = re.search(r"AM/PM|A/P", text, re.I)
    parts = re.findall(r"\x00[^\x01]*\x01|AM/PM|A/P|y+|m+|d+|h+|s+|.", text, re.I)
    kinds = [p.lower()[0] if re.fullmatch(r"y+|m+|d+|h+|s+", p, re.I) else "" for p in parts]
    out, prev = [], ""
    for idx, p in enumerate(parts):
        lo, kind = p.lower(), kinds[idx]
        if p.startswith("\x00"):
            out.append(p[1:-1])
        elif lo in ("am/pm", "a/p"):
            pm = d.hour >= 12
            out.append(("PM" if pm else "AM") if lo == "am/pm" else ("P" if pm else "A"))
        elif kind == "y":
            out.append(f"{d.year % 100:02d}" if len(p) <= 2 else f"{d.year:04d}")
        elif kind == "m":
            # `m` is minutes after an hour or before a second, else the month.
            nxt = next((k for k in kinds[idx + 1:] if k), "")
            if len(p) <= 2 and (prev == "h" or nxt == "s"):
                out.append(f"{d.minute:0{len(p)}d}")
            elif len(p) <= 2:
                out.append(f"{d.month:0{len(p)}d}")
            elif len(p) == 3:
                out.append(_MONTHS[d.month - 1][:3])
            elif len(p) == 5:
                out.append(_MONTHS[d.month - 1][0])
            else:
                out.append(_MONTHS[d.month - 1])
        elif kind == "d":
            # The weekday from the serial, as Excel counts it (and SheetJS):
            # its calendar has a 29 February 1900, so day 1 was a Sunday.
            day = _DAYS[(int(v) + (5 if date1904 else 6)) % 7]
            out.append(str(d.day) if len(p) == 1 else f"{d.day:02d}" if len(p) == 2
                       else day[:3] if len(p) == 3 else day)
        elif kind == "h":
            h = (d.hour % 12 or 12) if ampm else d.hour
            out.append(f"{h:0{min(len(p), 2)}d}")
        elif kind == "s":
            out.append(f"{d.second:0{min(len(p), 2)}d}")
        else:
            out.append(p)
        if kind:
            prev = kind
    return "".join(out)


def _js_round(x: float) -> int:
    """JavaScript's `Math.round`: a half rounds toward +infinity."""
    return math.floor(x + 0.5)


def _js_str(x: float) -> str:
    """`String(x)` for a double in the range a cell shows."""
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    return repr(x)


def _format_number(v: float, tokens, sign: str) -> str | None:
    """SheetJS's `write_num` for the placeholder formats — `0`, `0.00`,
    `#,##0`, `#,##0.00`, a percent of one, literals around it — rounded as it
    rounds: a plain format rounds the signed value (`Math.round(v * 10^d) /
    10^d`, so 9.0855 to three places is 9.086 and -755808.415 to two is
    -755808.41); a grouped one rounds the fraction alone and carries. A
    fraction or scientific format answers None: the caller shows General."""
    code = "".join(t for k, t in tokens if k == "code")
    if "E" in code.upper() or "?" in code or "/" in code:
        return None
    pct = code.count("%")
    if pct:
        v = v * (100 ** pct)
    m = re.search(_PLACEHOLDERS, "".join(t if k == "code" else " " for k, t in tokens))
    if not m:
        return None
    int_spec, _, dec_spec = m.group(0).partition(".")
    places = len(dec_spec)
    must = len(dec_spec.rstrip("#"))
    min_int = len(int_spec.replace(",", "").replace("#", ""))
    if "," in int_spec:
        a = abs(v)
        whole = math.floor(a)
        frac = _js_round((a - whole) * 10 ** places) if places else 0
        if places and len(str(frac)) > places:
            whole, frac = whole + 1, 0
        elif not places:
            whole = _js_round(a)
        ip = f"{whole:,}"
        dp = str(frac).rjust(places, "0") if places else ""
    else:
        r = _js_round(v * 10 ** places) / 10 ** places if places else float(_js_round(v))
        s = _js_str(r)
        sign = "-" if s.startswith("-") else ""     # `-0` prints as `0`
        ip, _, dp = s.lstrip("-").partition(".")
        dp = dp.ljust(places, "0")[:places] if places else ""
    while len(dp) > must and dp.endswith("0"):
        dp = dp[:-1]
    if ip == "0" and min_int == 0:
        ip = ""
    body = ip.rjust(min_int, "0") + ("." + dp if dp else "")
    flat, used = [], False
    marked = "".join(t if k == "code" else "\x00" + t + "\x01" for k, t in tokens)
    for piece in re.findall(r"\x00[^\x01]*\x01|" + _PLACEHOLDERS + "|.", marked):
        if piece.startswith("\x00"):
            flat.append(piece[1:-1])
        elif re.fullmatch(_PLACEHOLDERS, piece):
            if not used:
                flat.append(body)
                used = True
        elif piece != ",":
            flat.append(piece)
    return sign + "".join(flat)


def _js_fixed(v: float, places: int) -> str:
    """`Number.prototype.toFixed`: the exact binary value, half up."""
    q = Decimal(abs(v)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return ("-" if v < 0 and q != 0 else "") + f"{q:f}"


def _js_digits(v: float, p: int):
    """`(digits, exponent)`: |v| to `p` significant digits, half up."""
    d = Decimal(abs(v))
    e = d.adjusted()
    n = d.scaleb(p - 1 - e).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if n >= Decimal(10) ** p:
        e += 1
        n = d.scaleb(p - 1 - e).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return str(int(n)).rjust(p, "0"), e


def _js_exponential(v: float, f: int) -> str:
    """`Number.prototype.toExponential`."""
    if v == 0:
        return "0" + ("." + "0" * f if f else "") + "e+0"
    digits, e = _js_digits(v, f + 1)
    return (("-" if v < 0 else "") + digits[0] + ("." + digits[1:] if f else "")
            + "e" + ("+" if e >= 0 else "-") + str(abs(e)))


def _js_precision(v: float, p: int) -> str:
    """`Number.prototype.toPrecision`."""
    if v == 0:
        return "0" + ("." + "0" * (p - 1) if p > 1 else "")
    digits, e = _js_digits(v, p)
    sign = "-" if v < 0 else ""
    if e < -6 or e >= p:
        return (sign + digits[0] + ("." + digits[1:] if p > 1 else "")
                + "e" + ("+" if e >= 0 else "-") + str(abs(e)))
    if e >= 0:
        return sign + digits[:e + 1] + ("." + digits[e + 1:] if digits[e + 1:] else "")
    return sign + "0." + "0" * (-e - 1) + digits


def _strip_decimal(o: str) -> str:
    return o if "." not in o else re.sub(r"(?:\.0*|(\.\d*[1-9])0+)$", r"\1", o)


def _normalize_exp(o: str) -> str:
    if "E" not in o:
        return o
    o = re.sub(r"(?:\.0*|(\.\d*[1-9])0+)[Ee]", r"\1E", o)
    return re.sub(r"(E[+-])(\d)$", r"\g<1>0\2", o)


def general(v: float) -> str:
    """SheetJS's General format (`SSF_general` / `SSF_general_num`), ported."""
    if v == int(v) and -2 ** 31 <= v < 2 ** 31:
        return str(int(v))
    exp = math.floor(math.log10(abs(v)))
    if -4 <= exp <= -1:
        o = _js_precision(v, 10 + exp)
    elif abs(exp) <= 9:
        width = 12 if v < 0 else 11
        o = _strip_decimal(_js_fixed(v, 12))
        if len(o) > width:
            o = _js_precision(v, 10)
            if len(o) > width:
                o = _js_exponential(v, 5)
    elif exp == 10:
        o = _js_fixed(v, 10)[:12]
    else:
        o = _strip_decimal(_js_fixed(v, 11))
        if len(o) > (12 if v < 0 else 11) or o in ("0", "-0"):
            o = _js_precision(v, 6)
    return _strip_decimal(_normalize_exp(o.upper()))


def format_cell(v: float, code: str, date1904: bool = False) -> str:
    """The text SheetJS shows for number *v* in format *code*."""
    if not code or code.lower() == "general" or code == "@":
        return general(v)
    sections = code.split(";")
    if v < 0 and len(sections) >= 2 and sections[1]:
        section, value, sign = sections[1], -v, ""
    elif v == 0 and len(sections) >= 3 and sections[2]:
        section, value, sign = sections[2], v, ""
    else:
        section, value, sign = sections[0], v, "-" if v < 0 else ""
    tokens = _tokens(section)
    if section.lower() == "general":
        return general(value)
    if _is_date(tokens):
        try:
            return _format_date(v, tokens, date1904)
        except (OverflowError, ValueError):
            return general(v)
    out = _format_number(value, tokens, sign)
    return general(v) if out is None else out


# ── .xlsx: the sheets ──────────────────────────────────────────────────────


def _cell_position(ref):
    m = re.match(r"([A-Z]+)(\d+)$", ref or "")
    if not m:
        return None
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return col - 1, int(m.group(2)) - 1


def _csv_field(s: str) -> str:
    if any(c in s for c in ',"\n\r'):
        return '"' + s.replace('"', '""') + '"'
    return s


def xlsx_sheets(path: str):
    """`[(sheet name, CSV)]` in workbook order — SheetJS's `sheet_to_csv` of
    each — or None when the file is not a workbook this can read."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return None
    with z:
        names = set(z.namelist())
        wb = _part(z, "xl/workbook.xml")
        if wb is None:
            return None
        pr = wb.find(S + "workbookPr")
        # flag-spelling: not ours. `date1904` is the workbook's own XML
        # attribute, and SheetJS (the Library's reader) judges it with its
        # `parsexmlbool`: exactly "1" or "true" is yes, case and all. Lowering
        # the case first would date a `TRUE` workbook four years from SheetJS.
        date1904 = pr is not None and pr.get("date1904") in ("1", "true")
        shared = []
        sst = _part(z, "xl/sharedStrings.xml") if "xl/sharedStrings.xml" in names else None
        if sst is not None:
            for si in sst.findall(S + "si"):
                t = si.find(S + "t")
                shared.append(t.text or "" if t is not None
                              else "".join(r.findtext(S + "t") or "" for r in si.findall(S + "r")))
        style_formats = []
        styles = _part(z, "xl/styles.xml") if "xl/styles.xml" in names else None
        if styles is not None:
            custom = {}
            for nf in styles.iter(S + "numFmt"):
                try:
                    custom[int(nf.get("numFmtId"))] = nf.get("formatCode") or "General"
                except (TypeError, ValueError):
                    # A format with no usable id cannot be referred to by a
                    # cell; leaving it out is what SheetJS does with it too.
                    pass
            xfs = styles.find(S + "cellXfs")
            for xf in (xfs if xfs is not None else []):
                try:
                    fid = int(xf.get("numFmtId") or 0)
                except ValueError:
                    fid = 0
                style_formats.append(custom.get(fid, _BUILTIN_FORMATS.get(fid, "General")))
        targets = {}
        rels = _part(z, "xl/_rels/workbook.xml.rels")
        if rels is not None:
            for r in rels.iter(PKG + "Relationship"):
                targets[r.get("Id")] = r.get("Target") or ""
        out = []
        sheets = wb.find(S + "sheets")
        for sh in (sheets if sheets is not None else []):
            target = targets.get(sh.get(R + "id"), "")
            name = target.lstrip("/") if target.startswith("/") else "xl/" + target
            ws = _part(z, name) if name in names else None
            if ws is None:
                continue
            cells = {}
            for c in ws.iter(S + "c"):
                pos = _cell_position(c.get("r"))
                if pos is None:
                    continue
                kind = c.get("t") or "n"
                v = c.findtext(S + "v")
                if kind == "s":
                    try:
                        cells[pos] = shared[int(v)]
                    except (TypeError, ValueError, IndexError):
                        # A shared-string index that points nowhere is a cell
                        # with no text: left empty, as SheetJS leaves it.
                        pass
                elif kind == "inlineStr":
                    is_ = c.find(S + "is")
                    cells[pos] = "".join(x.text or "" for x in is_.iter(S + "t")) if is_ is not None else ""
                elif kind == "b":
                    cells[pos] = "TRUE" if v == "1" else "FALSE"
                elif kind in ("str", "e"):
                    cells[pos] = v or ""
                elif v is not None:
                    try:
                        index = int(c.get("s") or 0)
                    except ValueError:
                        index = 0
                    code = style_formats[index] if 0 <= index < len(style_formats) else "General"
                    try:
                        cells[pos] = format_cell(float(v), code, date1904)
                    except (ValueError, OverflowError):
                        cells[pos] = v
            if not cells:
                out.append((sh.get("name") or "", ""))
                continue
            cols = [col for col, _ in cells]
            rows = [row for _, row in cells]
            lines = [",".join(_csv_field(cells.get((col, row), ""))
                              for col in range(min(cols), max(cols) + 1))
                     for row in range(min(rows), max(rows) + 1)]
            out.append((sh.get("name") or "", "\n".join(lines)))
        return out


def xlsx_text(path: str):
    """The workbook as one document's text, carrying the language its document
    is (`markitdown_runtime.ExtractedText`). One sheet with anything in it is
    its CSV, language `csv` — the document the Library makes of it; several are
    each under `# Sheet: <name>`, joined by a blank line, as markdown — the
    one-document form the Library's reader (`readFileContent`) writes for a
    workbook. Empty sheets are left out, as the Library leaves them out; none
    with anything → None."""
    # `B1178`: the rule is `sheets_text` now, shared with `.ods` and `.xls`.
    return sheets_text(xlsx_sheets(path))


def sheets_text(sheets):
    """`[(name, CSV)]` as one document's text — `xlsx_text`'s rule, shared by
    every workbook reader here (`B1178`): one sheet with anything in it is its
    CSV (`csv`), several are each under `# Sheet: <name>` (markdown), empty
    sheets are left out, none with anything → None."""
    from src.markitdown_runtime import ExtractedText

    filled = [(n, csv) for n, csv in (sheets or []) if csv.strip()]
    if not filled:
        return None
    if len(filled) == 1:
        return ExtractedText(filled[0][1], language="csv")
    return ExtractedText("\n\n".join(f"# Sheet: {n}\n\n{csv}" for n, csv in filled),
                         language="markdown")


def _csv_of(cells: dict) -> str:
    """SheetJS's `sheet_to_csv` over `{(col, row): text}`: the used range of
    the cells holding something, one line per row, RFC 4180 quoting."""
    cells = {k: v for k, v in cells.items() if v != ""}
    if not cells:
        return ""
    cols = [col for col, _ in cells]
    rows = [row for _, row in cells]
    return "\n".join(",".join(_csv_field(cells.get((col, row), ""))
                              for col in range(min(cols), max(cols) + 1))
                     for row in range(min(rows), max(rows) + 1))


# ── .ods ───────────────────────────────────────────────────────────────────
#
# `B1178`. An OpenDocument spreadsheet is the `.odt` container `B102` already
# reads, with `<table:table>` in its body instead of paragraphs. Every cell
# LibreOffice writes carries its displayed text in `<text:p>` — `1,200.00`,
# `25%`, `2026-10-02` — and that text is what SheetJS (the Library's reader)
# puts in the CSV, so it is read rather than re-formatted here. A cell with a
# value and no paragraph (another writer's) falls back to the value itself.

ODF_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
ODF_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
ODF_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
# A repeat count is the file's word for how many identical rows or columns
# follow; LibreOffice pads a sheet with `number-columns-repeated="1019"` empties
# and a hostile file can say a billion. Empties are skipped arithmetically; a
# cell WITH content repeated past these is not expanded further.
_ODS_MAX_COLS = 16384
_ODS_MAX_ROWS = 1048576
_ODS_MAX_CELLS = 2_000_000


def _ods_repeat(el, attr: str) -> int:
    try:
        return max(1, int(el.get(ODF_TABLE + attr) or 1))
    except ValueError:
        return 1


def _odf_paragraph_text(p) -> str:
    out = [p.text or ""]
    for child in p:
        tag = child.tag
        if tag == ODF_TEXT + "s":
            try:
                out.append(" " * max(1, int(child.get(ODF_TEXT + "c") or 1)))
            except ValueError:
                out.append(" ")
        elif tag == ODF_TEXT + "tab":
            out.append("\t")
        elif tag == ODF_TEXT + "line-break":
            out.append("\n")
        else:
            out.append(_odf_paragraph_text(child))
        out.append(child.tail or "")
    return "".join(out)


def _ods_cell_text(cell) -> str:
    paras = cell.findall(ODF_TEXT + "p")
    if paras:
        return "\n".join(_odf_paragraph_text(p) for p in paras)
    kind = cell.get(ODF_OFFICE + "value-type") or ""
    if kind in ("float", "percentage", "currency"):
        return cell.get(ODF_OFFICE + "value") or ""
    if kind == "boolean":
        return "TRUE" if (cell.get(ODF_OFFICE + "boolean-value") or "") == "true" else "FALSE"
    if kind == "date":
        return cell.get(ODF_OFFICE + "date-value") or ""
    if kind == "time":
        return cell.get(ODF_OFFICE + "time-value") or ""
    return ""


def ods_sheets(path: str):
    """`[(sheet name, CSV)]` in workbook order, or None when the file is not
    an OpenDocument spreadsheet this can read."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return None
    with z:
        content = _part(z, "content.xml")
    if content is None:
        return None
    sheet_el = content.find(f"{ODF_OFFICE}body/{ODF_OFFICE}spreadsheet")
    if sheet_el is None:
        return None
    out = []
    for table in sheet_el.iter(ODF_TABLE + "table"):
        cells, budget, row = {}, _ODS_MAX_CELLS, 0
        for tr in table.iter(ODF_TABLE + "table-row"):
            rows_here = _ods_repeat(tr, "number-rows-repeated")
            col, texts = 0, []
            for cell in tr:
                if cell.tag not in (ODF_TABLE + "table-cell", ODF_TABLE + "covered-table-cell"):
                    continue
                n = _ods_repeat(cell, "number-columns-repeated")
                text = _ods_cell_text(cell) if cell.tag == ODF_TABLE + "table-cell" else ""
                if text:
                    for i in range(min(n, _ODS_MAX_COLS - col)):
                        texts.append((col + i, text))
                col += n
                if col >= _ODS_MAX_COLS:
                    break
            if texts:
                for r in range(min(rows_here, _ODS_MAX_ROWS - row)):
                    if budget <= 0:
                        break
                    for c, text in texts[:budget]:
                        cells[(c, row + r)] = text
                    budget -= min(len(texts), budget)
            row += rows_here
            if row >= _ODS_MAX_ROWS or budget <= 0:
                break
        out.append((table.get(ODF_TABLE + "name") or "", _csv_of(cells)))
    return out


def ods_text(path: str):
    """The OpenDocument spreadsheet as one document's text (`sheets_text`)."""
    return sheets_text(ods_sheets(path))


# ── .pptx ──────────────────────────────────────────────────────────────────
#
# `B1289`. A deck is a zip of slide XML, the `.docx` container one namespace
# over, and it needed markitdown — which the default image does not install —
# so on a default install a `.pptx` was unread at every door. The shape follows
# markitdown's own converter, so one deck is one document whether or not the
# optional dependency is present: `<!-- Slide number: N -->`, the title
# placeholder as `# `, every other text frame's paragraphs, a table as pipe
# rows, and the speaker notes under `### Notes:`. Slides in the presentation's
# order (`sldIdLst`), not the zip's.

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_PPTX_MAX_SLIDES = 2000


def _rels_of(z: zipfile.ZipFile, part: str) -> dict:
    """`{rId: target part}` for *part*, targets resolved against its folder."""
    import posixpath

    folder, name = posixpath.split(part)
    rels = _part(z, posixpath.join(folder, "_rels", name + ".rels"))
    out = {}
    if rels is None:
        return out
    for r in rels.iter(PKG + "Relationship"):
        if r.get("TargetMode") == "External":
            continue
        target = r.get("Target") or ""
        resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
            posixpath.join(folder, target))
        out[r.get("Id")] = (resolved, r.get("Type") or "")
    return out


def _drawing_paragraphs(tx_body) -> list[str]:
    lines = []
    for p in tx_body.findall(A + "p"):
        parts = []
        for el in p:
            if el.tag in (A + "r", A + "fld"):
                parts.append(el.findtext(A + "t") or "")
            elif el.tag == A + "br":
                parts.append("\n")
        lines.append("".join(parts))
    return lines


def _slide_blocks(tree) -> list[str]:
    """Each shape's text in document order, descending into groups."""
    blocks = []
    for el in tree:
        tag = el.tag
        if tag == P + "grpSp":
            blocks.extend(_slide_blocks(el))
        elif tag == P + "sp":
            body = el.find(P + "txBody")
            if body is None:
                continue
            text = "\n".join(_drawing_paragraphs(body)).strip()
            if not text:
                continue
            ph = el.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
            if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                blocks.append("# " + text.lstrip())
            else:
                blocks.append(text)
        elif tag == P + "graphicFrame":
            tbl = el.find(f".//{A}tbl")
            if tbl is None:
                continue
            rows = []
            for tr in tbl.findall(A + "tr"):
                cells = []
                for tc in tr.findall(A + "tc"):
                    body = tc.find(A + "txBody")
                    text = " ".join(_drawing_paragraphs(body)).strip() if body is not None else ""
                    cells.append(text.replace("|", "\\|").replace("\n", " "))
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                width = rows[0].count(" | ") + 1
                rows.insert(1, "| " + " | ".join(["---"] * width) + " |")
                blocks.append("\n".join(rows))
    return blocks


def pptx_text(path: str) -> str | None:
    """The deck as markdown, slide by slide (see the section note above)."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return None
    with z:
        pres = _part(z, "ppt/presentation.xml")
        if pres is None:
            return None
        rels = _rels_of(z, "ppt/presentation.xml")
        ids = pres.find(P + "sldIdLst")
        out = []
        for n, sld in enumerate(ids if ids is not None else [], start=1):
            if n > _PPTX_MAX_SLIDES:
                break
            target = rels.get(sld.get(R + "id"))
            if not target:
                continue
            slide = _part(z, target[0])
            if slide is None:
                continue
            tree = slide.find(f"{P}cSld/{P}spTree")
            blocks = _slide_blocks(tree) if tree is not None else []
            text = f"<!-- Slide number: {n} -->\n" + "\n".join(blocks)
            notes_part = next((t for t, kind in _rels_of(z, target[0]).values()
                               if kind.endswith("/notesSlide")), None)
            if notes_part:
                notes = _part(z, notes_part)
                said = []
                for sp in (notes.iter(P + "sp") if notes is not None else []):
                    # The notes are the body placeholder; a writer that drew
                    # them as a plain text box (LibreOffice, from a page with
                    # no layout) gives a shape with no placeholder. The slide
                    # image, number, header, footer and date are not notes.
                    ph = sp.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                    body = sp.find(P + "txBody")
                    if body is not None and (ph is None or ph.get("type") in (None, "body", "obj")):
                        said.append("\n".join(_drawing_paragraphs(body)).strip())
                said = "\n".join(s for s in said if s)
                if said:
                    text += "\n\n### Notes:\n" + said
            out.append(text.strip())
    return "\n\n".join(out) if any(len(t.splitlines()) > 1 for t in out) else None


# ── .epub ──────────────────────────────────────────────────────────────────
#
# `B1289`. An EPUB is XHTML in a zip: `META-INF/container.xml` names the
# package document, whose spine is the reading order. Each chapter is turned
# into markdown with the standard library's HTML parser — headings, paragraphs,
# lists, emphasis, links, line breaks — and the chapters are joined in spine
# order. The navigation document (`properties="nav"`) is the table of contents
# and is left out, as a reader would.

OPF = "{http://www.idpf.org/2007/opf}"
OCF = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_EPUB_MAX_CHAPTERS = 2000
_EPUB_MAX_CHARS = 20_000_000


def xhtml_markdown(markup: str) -> str:
    """XHTML to markdown, standard library only (`html.parser`)."""
    from html.parser import HTMLParser

    class _MD(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.blocks, self.line, self.skip = [], [], 0
            self.lists, self.href = [], None
            self.prefix = ""

        def _flush(self):
            text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.line))
            text = "\n".join(s.strip() for s in text.split("\n")).strip()
            if text:
                self.blocks.append(self.prefix + text)
            self.line, self.prefix = [], ""

        def handle_starttag(self, tag, attrs):
            if tag in ("head", "script", "style", "nav"):
                self.skip += 1
            elif self.skip:
                return
            elif tag in ("p", "div", "blockquote", "section", "article", "tr", "table"):
                self._flush()
            elif re.fullmatch(r"h[1-6]", tag):
                self._flush()
                self.prefix = "#" * int(tag[1]) + " "
            elif tag in ("ul", "ol"):
                self._flush()
                self.lists.append([tag, 0])
            elif tag == "li":
                self._flush()
                if self.lists:
                    self.lists[-1][1] += 1
                    kind, count = self.lists[-1]
                    indent = "  " * (len(self.lists) - 1)
                    self.prefix = indent + (f"{count}. " if kind == "ol" else "- ")
                else:
                    self.prefix = "- "
            elif tag == "br":
                self.line.append("\n")
            elif tag in ("strong", "b"):
                self.line.append("**")
            elif tag in ("em", "i"):
                self.line.append("*")
            elif tag == "a":
                href = dict(attrs).get("href") or ""
                self.href = href if re.match(r"https?://", href) else None
                if self.href:
                    self.line.append("[")
            elif tag in ("td", "th"):
                self.line.append(" ")

        def handle_endtag(self, tag):
            if tag in ("head", "script", "style", "nav"):
                self.skip = max(0, self.skip - 1)
            elif self.skip:
                return
            elif tag in ("p", "div", "blockquote", "li", "section", "article", "tr", "table") \
                    or re.fullmatch(r"h[1-6]", tag):
                self._flush()
            elif tag in ("ul", "ol"):
                self._flush()
                if self.lists:
                    self.lists.pop()
            elif tag in ("strong", "b"):
                self.line.append("**")
            elif tag in ("em", "i"):
                self.line.append("*")
            elif tag == "a" and self.href:
                self.line.append(f"]({self.href})")
                self.href = None

        def handle_data(self, data):
            if not self.skip:
                self.line.append(data)

    parser = _MD()
    parser.feed(markup)
    parser.close()
    parser._flush()
    # An emphasis marker around nothing (`****`) is noise from empty runs.
    blocks = [re.sub(r"\*\*\s*\*\*|(?<!\*)\*\s*\*(?!\*)", "", b).strip() for b in parser.blocks]
    return "\n\n".join(b for b in blocks if b)


def epub_text(path: str) -> str | None:
    """The book as markdown, chapter by chapter in spine order."""
    import posixpath

    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return None
    with z:
        container = _part(z, "META-INF/container.xml")
        if container is None:
            return None
        root = container.find(f".//{OCF}rootfile")
        opf_path = (root.get("full-path") or "") if root is not None else ""
        opf = _part(z, opf_path) if opf_path else None
        if opf is None:
            return None
        folder = posixpath.dirname(opf_path)
        manifest = {}
        for item in opf.iter(OPF + "item"):
            manifest[item.get("id")] = (item.get("href") or "", item.get("media-type") or "",
                                        item.get("properties") or "")
        chapters, total = [], 0
        spine = opf.find(OPF + "spine")
        for n, ref in enumerate(spine if spine is not None else []):
            if n >= _EPUB_MAX_CHAPTERS or total >= _EPUB_MAX_CHARS:
                break
            href, media, props = manifest.get(ref.get("idref"), ("", "", ""))
            if not href or "nav" in props.split() or "html" not in media:
                continue
            name = posixpath.normpath(posixpath.join(folder, href.split("#", 1)[0]))
            try:
                with z.open(name) as fh:
                    data = fh.read(PART_LIMIT + 1)
            except (KeyError, zipfile.BadZipFile, OSError, RuntimeError):
                continue
            if len(data) > PART_LIMIT or b"<!ENTITY" in data or b"<!entity" in data:
                continue
            text = xhtml_markdown(data.decode("utf-8", errors="replace"))
            if text:
                chapters.append(text)
                total += len(text)
    return "\n\n".join(chapters) or None


# ── .xls (BIFF8) ───────────────────────────────────────────────────────────
#
# `B1178`. Excel 97–2003's format is not a zip: it is the OLE2/CFB container
# `B102` already reads for `.doc` (`markitdown_runtime._cfb_streams`), holding a
# `Workbook` stream of BIFF8 records. On a default install markitdown — the only
# server reader of it — is absent, so a `.xls` was a document at the Library
# (SheetJS, in the browser) and a refusal at every server door. This reads the
# records SheetJS's `sheet_to_csv` needs: the shared-string table (with its
# CONTINUE splits), the sheet directory, the number formats and cell styles,
# the 1904 flag, and the value records — LABELSST, LABEL, RSTRING, NUMBER, RK,
# MULRK, BOOLERR and FORMULA (with the STRING that follows a text result).
# Numbers are shown through their cell's format by `format_cell`, the same
# SheetJS port the `.xlsx` reader uses. Bounded: one stream, a record count,
# and the cell ceiling the `.ods` reader has.

_XLS_MAX_RECORDS = 4_000_000
_XLS_ERRORS = {0x00: "#NULL!", 0x07: "#DIV/0!", 0x0F: "#VALUE!", 0x17: "#REF!",
               0x1D: "#NAME?", 0x24: "#NUM!", 0x2A: "#N/A"}


def _xls_records(stream: bytes):
    import struct

    off, n = 0, 0
    while off + 4 <= len(stream) and n < _XLS_MAX_RECORDS:
        rid, size = struct.unpack_from("<HH", stream, off)
        yield off, rid, stream[off + 4:off + 4 + size]
        off += 4 + size
        n += 1


def _xls_unicode(data: bytes, pos: int, count: int, high: bool):
    """`count` characters from `pos`, compressed (latin-1) or UTF-16LE."""
    if high:
        end = pos + 2 * count
        return data[pos:end].decode("utf-16-le", "replace"), end
    end = pos + count
    return data[pos:end].decode("latin-1"), end


def _xls_string(data: bytes, pos: int, len_bytes: int = 2):
    """An `XLUnicodeString` (or the short form) that does not cross a record."""
    import struct

    if pos + len_bytes + 1 > len(data):
        return "", len(data)
    count = data[pos] if len_bytes == 1 else struct.unpack_from("<H", data, pos)[0]
    pos += len_bytes
    flags = data[pos]
    pos += 1
    runs = ext = 0
    if flags & 0x08:
        runs = struct.unpack_from("<H", data, pos)[0]
        pos += 2
    if flags & 0x04:
        ext = struct.unpack_from("<I", data, pos)[0]
        pos += 4
    text, pos = _xls_unicode(data, pos, count, bool(flags & 0x01))
    return text, pos + 4 * runs + ext


def _xls_sst(pieces: list) -> list:
    """The shared-string table from the SST record and its CONTINUEs.

    A string's characters may break across a CONTINUE, and the continuation
    restates whether its characters are one byte or two in a fresh flag byte —
    the part of BIFF8 every hand reader gets wrong once.
    """
    import struct

    strings = []
    if not pieces or len(pieces[0]) < 8:
        return strings
    total = struct.unpack_from("<I", pieces[0], 4)[0]
    idx, pos = 0, 8
    data = pieces[0]

    def need(k):
        nonlocal idx, pos, data
        while pos + k > len(data) and idx + 1 < len(pieces):
            idx += 1
            data, pos = pieces[idx], 0
        return pos + k <= len(data)

    while len(strings) < total:
        if not need(3):
            break
        count = struct.unpack_from("<H", data, pos)[0]
        flags = data[pos + 2]
        pos += 3
        runs = ext = 0
        if flags & 0x08:
            if not need(2):
                break
            runs = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        if flags & 0x04:
            if not need(4):
                break
            ext = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        high = bool(flags & 0x01)
        chars, left = [], count
        while left > 0:
            width = 2 if high else 1
            avail = (len(data) - pos) // width
            if avail <= 0:
                if idx + 1 >= len(pieces):
                    left = 0
                    break
                idx += 1
                data = pieces[idx]
                high = bool(data[0] & 0x01) if data else high
                pos = 1
                continue
            take = min(avail, left)
            text, pos = _xls_unicode(data, pos, take, high)
            chars.append(text)
            left -= take
        strings.append("".join(chars))
        skip = 4 * runs + ext
        while skip > 0:
            here = min(skip, len(data) - pos)
            pos += here
            skip -= here
            if skip > 0:
                if idx + 1 >= len(pieces):
                    break
                idx += 1
                data, pos = pieces[idx], 0
    return strings


def _rk_value(rk: int) -> float:
    import struct

    if rk & 0x02:
        v = float(rk >> 2 if rk < 0x80000000 else (rk >> 2) - (1 << 30))
    else:
        v = struct.unpack("<d", struct.pack("<Q", (rk & 0xFFFFFFFC) << 32))[0]
    return v / 100 if rk & 0x01 else v


def xls_sheets(path: str):
    """`[(sheet name, CSV)]` in workbook order, or None when the file is not a
    BIFF8 workbook this can read."""
    import struct

    from src.markitdown_runtime import _cfb_streams

    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    streams = _cfb_streams(data, {"Workbook", "Book"})
    stream = streams.get("Workbook") or streams.get("Book")
    if not stream:
        return None
    sheets, formats, xfs, sst_pieces = [], {}, [], []
    date1904, in_sst = False, False
    for off, rid, body in _xls_records(stream):
        if rid == 0x003C and in_sst:
            sst_pieces.append(body)
            continue
        in_sst = False
        if rid == 0x0085 and len(body) >= 8:              # BOUNDSHEET
            pos, _vis, kind = struct.unpack_from("<IBB", body, 0)
            name, _ = _xls_string(body, 6, len_bytes=1)
            if kind == 0:                                  # a worksheet
                sheets.append((name, pos))
        elif rid == 0x00FC:                                # SST
            sst_pieces, in_sst = [body], True
        elif rid == 0x041E and len(body) >= 5:             # FORMAT
            ifmt = struct.unpack_from("<H", body, 0)[0]
            formats[ifmt], _ = _xls_string(body, 2)
        elif rid == 0x00E0 and len(body) >= 4:             # XF
            xfs.append(struct.unpack_from("<H", body, 2)[0])
        elif rid == 0x0022 and len(body) >= 2:             # DATEMODE
            date1904 = struct.unpack_from("<H", body, 0)[0] == 1
        elif rid == 0x000A:                                # EOF of the globals
            break
    if not sheets and not xfs:
        return None
    shared = _xls_sst(sst_pieces)

    def number(v: float, ixfe: int) -> str:
        ifmt = xfs[ixfe] if 0 <= ixfe < len(xfs) else 0
        code = formats.get(ifmt) or _BUILTIN_FORMATS.get(ifmt, "General")
        try:
            return format_cell(v, code, date1904)
        except (ValueError, OverflowError):
            return general(v)

    out = []
    for name, start in sheets:
        cells, budget, pending = {}, _ODS_MAX_CELLS, None
        for off, rid, body in _xls_records(stream[start:]):
            if budget <= 0:
                break
            if rid == 0x000A:                              # EOF of this sheet
                break
            if rid == 0x0207 and pending is not None:      # STRING after FORMULA
                cells[pending], _ = _xls_string(body, 0)
                pending = None
                continue
            pending = None
            if len(body) < 6:
                continue
            row, col, ixfe = struct.unpack_from("<HHH", body, 0)
            if rid == 0x00FD and len(body) >= 10:          # LABELSST
                i = struct.unpack_from("<I", body, 6)[0]
                if i < len(shared):
                    cells[(col, row)] = shared[i]
            elif rid in (0x0204, 0x00D6):                  # LABEL, RSTRING
                cells[(col, row)], _ = _xls_string(body, 6)
            elif rid == 0x0203 and len(body) >= 14:        # NUMBER
                cells[(col, row)] = number(struct.unpack_from("<d", body, 6)[0], ixfe)
            elif rid == 0x027E and len(body) >= 10:        # RK
                cells[(col, row)] = number(_rk_value(struct.unpack_from("<I", body, 6)[0]), ixfe)
            elif rid == 0x00BD and len(body) >= 6:         # MULRK
                last = struct.unpack_from("<H", body, len(body) - 2)[0]
                pos = 4
                for c in range(col, last + 1):
                    if pos + 6 > len(body) - 2:
                        break
                    xf, rk = struct.unpack_from("<HI", body, pos)
                    cells[(c, row)] = number(_rk_value(rk), xf)
                    pos += 6
            elif rid == 0x0205 and len(body) >= 8:         # BOOLERR
                value, is_err = body[6], body[7]
                cells[(col, row)] = (_XLS_ERRORS.get(value, "#N/A") if is_err
                                     else ("TRUE" if value else "FALSE"))
            elif rid == 0x0006 and len(body) >= 14:        # FORMULA
                result = body[6:14]
                if result[6:8] == b"\xff\xff":
                    kind = result[0]
                    if kind == 0:
                        pending = (col, row)               # text: a STRING follows
                    elif kind == 1:
                        cells[(col, row)] = "TRUE" if result[2] else "FALSE"
                    elif kind == 2:
                        cells[(col, row)] = _XLS_ERRORS.get(result[2], "#N/A")
                else:
                    cells[(col, row)] = number(struct.unpack("<d", result)[0], ixfe)
            budget = _ODS_MAX_CELLS - len(cells)
        out.append((name, _csv_of(cells)))
    return out


def xls_text(path: str):
    """The Excel 97–2003 workbook as one document's text (`sheets_text`)."""
    return sheets_text(xls_sheets(path))
