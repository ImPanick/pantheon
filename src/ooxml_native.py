# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dependency-free `.docx` and `.xlsx` readers, written to give the server the
document the Library's browser converters give.

`B-NEW` (f-import: on a default install one `.docx` is two documents and one
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
    return el.get(W + "val") not in ("0", "false", "off")


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
        date1904 = pr is not None and (pr.get("date1904") or "").lower() in ("1", "true")
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
    from src.markitdown_runtime import ExtractedText

    sheets = xlsx_sheets(path)
    filled = [(n, csv) for n, csv in (sheets or []) if csv.strip()]
    if not filled:
        return None
    if len(filled) == 1:
        return ExtractedText(filled[0][1], language="csv")
    return ExtractedText("\n\n".join(f"# Sheet: {n}\n\n{csv}" for n, csv in filled),
                         language="markdown")
