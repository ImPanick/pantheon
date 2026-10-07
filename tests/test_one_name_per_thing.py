# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-05` — one name per thing, on every label a person reads.

The owner's ruling, `D-2026-10-03-01` §3: **Brain** (not Memory), **chat** (not
session or conversation), **MCP & Integrations** (never just "Integrations" for
that room), **Forge** (`P0-29`, held by `tests/test_the_product_noun_is_forge.py`).
Library and Documents were not chosen between and stay as they are.

The audit that asked for it (`Doc2-UIUX-audit.md` § 4.4, `COPY-U-1`) measured
*chat*, *session* and *conversation* in fifteen places on one sitting, *Brain*
and *Memory* for one window, and a door that said "Settings › Integrations" for
a room that had moved to the Workbench.

**Names change where a person reads them; identifiers do not** (`D-2026-09-18-04`,
`FORBIDDEN.md` Part 1): `session` stays in ids, keys, routes, stored values and
the `/session` slash alias; `memory-modal`, `open_memory` and `/memory` stay.
So the rules below are about *phrases*, never tokens:

* a **phrase** is a string literal (or a template literal's text chunk, or an
  HTML text node or `title` / `aria-label` / `placeholder` / `alt`) with a
  space in it — what a person reads. A bare `'session'` is a key; a path like
  `/api/session/` is a route; neither is a phrase.
* the literals are found by the repository's one JavaScript scanner
  (`tests/helpers/js_source.js_spans` over `blank_text`), never a hand-rolled
  quote regex (`B290`, `B876`).
* an argument to `console.*` is for a developer, not a person, and is skipped.
* "tmux session" is tmux's own word for the Forge's serve, not a chat.

**The register below is a hand-off, not a permission** (the `P0-29` pattern):
each entry is a string inside another lane's file or range this wave, with the
lane that owns it. `test_the_register_holds_nothing_already_done` fails the day
an entry is clean, so the entry comes out with the fix and the merged tree says
exactly what is left.
"""

import ast
import bisect
import functools
import json
import pathlib
import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

from tests.helpers.js_source import js_binding, js_code, js_spans
from tests.helpers.source_text import blank_text

_REPO = pathlib.Path(__file__).resolve().parents[1]
_HAS_NODE = shutil.which("node") is not None

# The retired chat words, as a word. A hyphen, slash, dot, `#` or `$` beside it
# makes it an id, a route, a hash anchor or a template variable.
CHAT_WORD = re.compile(
    r"(?<![A-Za-z0-9_\-/.#$])(?:session|sessions|conversation|conversations)(?![A-Za-z0-9_\-])",
    re.I)

# A door that names the room by its bare old name: "Settings › Integrations",
# "in Integrations", "Open Integrations", "-> Integrations". `MCP & ` before it is
# the room's name; "No Integrations are switched on" is the items, not a door.
BARE_ROOM = re.compile(
    r"(?<!MCP & )(?<!MCP &amp; )(?:(?:›|&rsaquo;|→|->|>|\bin|\bOpen|\bto)\s+)Integrations\b")

_TEXT_ATTRS = ("title", "aria-label", "placeholder", "alt")


# ── what a person reads, found the one way ────────────────────────────────────


def _js_phrases(source: str):
    """(line, text) for every literal a person could read in a JS source."""
    blanked = blank_text(source, "js")
    code = js_code(source)
    # Where each statement of real code may begin: after a `;` or a brace. Not
    # a brace balancer — only "the last boundary before here" is asked.
    bounds = [m.start() for m in re.finditer(r"[;{}]", code)]
    for start, end in js_spans(blanked):
        lit = blanked[start:end]
        if not lit or lit[0] == "/" or not lit.strip():
            continue                      # a regex literal, or a comment's blanks
        body = lit.strip("'\"`")
        # The statement this literal sits in: back to the last boundary of
        # real code. `console.warn(` anywhere in it makes it a log line.
        at = bisect.bisect_left(bounds, start)
        head = bounds[at - 1] if at else -1
        if "console." in code[head + 1:start]:
            continue
        line = blanked.count("\n", 0, start) + 1
        if "<" in body and ">" in body:
            # Markup built in a literal: what a person reads is its text and its
            # text attributes, not `<option value="session">`.
            parser = _HtmlPhrases()
            parser.feed(body)
            for at, text in parser.out:
                yield line + at - 1, text
            continue
        yield line, body


class _HtmlPhrases(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._in = None

    def handle_starttag(self, tag, attrs):
        self._in = tag
        for name, value in attrs:
            if name in _TEXT_ATTRS and value:
                self.out.append((self.getpos()[0], value))

    def handle_endtag(self, tag):
        self._in = None

    def handle_data(self, data):
        line = self.getpos()[0]
        if self._in == "script":
            for at, text in _js_phrases(data):
                self.out.append((line + at - 1, text))
        elif self._in != "style" and data.strip():
            self.out.append((line, data))


def _html_phrases(source: str):
    parser = _HtmlPhrases()
    parser.feed(blank_text(source, "html", embedded=False))
    return parser.out


def _served_files():
    tracked = subprocess.run(["git", "ls-files", "static"], cwd=_REPO,
                             capture_output=True, text=True, check=True).stdout.split()
    for rel in tracked:
        if rel.startswith("static/lib/"):
            continue
        if rel.endswith((".js", ".mjs")) or rel == "static/index.html":
            yield rel


def _phrases(rel: str):
    text = (_REPO / rel).read_text(encoding="utf-8", errors="replace")
    return _html_phrases(text) if rel.endswith(".html") else list(_js_phrases(text))


def _is_phrase(text: str) -> bool:
    return " " in text.strip()


@functools.lru_cache(maxsize=None)
def _chat_word_hits():
    out = {}
    for rel in _served_files():
        for line, text in _phrases(rel):
            if _is_phrase(text) and CHAT_WORD.search(text) and "tmux" not in text.lower():
                out.setdefault(rel, []).append((line, text.strip()[:90]))
    return out


@functools.lru_cache(maxsize=None)
def _bare_room_hits():
    out = {}
    for rel in _served_files():
        for line, text in _phrases(rel):
            if BARE_ROOM.search(text) or text.strip() == "Integrations":
                out.setdefault(rel, []).append((line, text.strip()[:90]))
    for rel in subprocess.run(["git", "ls-files", "src", "routes", "services"], cwd=_REPO,
                              capture_output=True, text=True, check=True).stdout.split():
        if not rel.endswith(".py"):
            continue
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) and body:
                if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docs.add(id(body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs and BARE_ROOM.search(node.value)):
                out.setdefault(rel, []).append((node.lineno, node.value.strip()[:90]))
    return out


# ── the hand-off: strings other lanes hold this wave, with who holds them ────

CHAT_RESIDUE = {
    "static/app.js": (1, "fx-chat (`P23-04`): the Tool Builder explainer bubble, "
                         "`app.js:2024-2052`, which CHAT-U-14 deletes."),
    "static/index.html": (5, "fx-brain `index.html:405-740` (`:543`, dropped by "
                             "COPY-U-19), fx-chat `:1340-1400` (three welcome tips "
                             "the § 5 composer row drops), fx-tools `:1990-3720` "
                             "(`:2011`, dropped by COPY-U-34)."),
    "static/js/chat.js": (2, "fx-chat (`P23-04`): the no-model bubble, "
                             "*No model yet.* + Add a model."),
    "static/js/chatRenderer.js": (1, "the compact marker matched by text, "
                                     "`Conversation compacted`: it is stored in "
                                     "every compacted chat's history "
                                     "(`routes/history/history_routes.py`), so the "
                                     "reader must match both words before the "
                                     "writer changes — filed, not done here."),
    "static/js/cookbookRunning.js": (1, "the Forge's failed-kill toast, pinned by "
                                        "`tests/test_a_failed_kill_says_how_to_find_"
                                        "the_session.py`; it is a tmux session, and "
                                        "the toast is not this row's to reword."),
    "static/js/document.js": (1, "fx-docs (`P23-08`): a thrown error on the "
                                 "editor's create-a-chat path."),
    "static/js/emailInbox.js": (1, "fx-docs (`P23-08`): Compose's create-a-chat "
                                   "path, which DOCS-M-1 rewrites."),
    "static/js/research/panel.js": (1, "fx-brain (`P23-02`): a thrown error in "
                                       "the research start path."),
    "static/js/sessions.js": (4, "fx-chat (`P23-04`) `sessions.js:946, 979-991`: "
                                 "*Delete this chat?* and the archive handler "
                                 "CHAT-M-6 rewrites."),
    "static/js/settings.js": (1, "Bitwarden's word: unlocking the vault saves a vault "
                                 "*session* — not a chat. fx-tools' file."),
    "static/js/trustLadder.js": (5, "fx-tools (`P23-03`) rewrote the ladder "
                                    "(COPY-U-37, `:123-194`); its *outside the "
                                    "conversation* lines are that rewrite's to word. "
                                    "The approval label it quotes moved here with "
                                    "the card's (*Allow for this chat*)."),
}

ROOM_RESIDUE = {
    "static/index.html": (1, "fx-back (`P23-01`): the Settings stub panel's heading "
                             "(`:2971`), which NAV-U-6 deletes."),
    "static/js/settings/mcpPresets.js": (1, "Todoist's own menu path, "
                                            "*Settings > Integrations > Developer*."),
    "src/integrations.py": (1, "Discord's own menu path, *Server Settings -> "
                               "Integrations -> Webhooks*."),
}


# ── the rules, checked before anything is concluded from them ────────────────


def test_the_phrase_rule_separates_a_label_from_a_key():
    src = ("const a = 'Delete session';\n"
           "const b = 'session';\n"
           "fetch(`/api/session/${sid}`);\n"
           "const c = `Chat: ${ctx.esc(session?.name || 'x')} kept`;\n"
           "console.warn(\n  `upload refused: belongs to session ${k}`);\n"
           "const r = /session from (\\w+)/;\n")
    hits = [t for _, t in _js_phrases(src) if _is_phrase(t) and CHAT_WORD.search(t)]
    assert hits == ["Delete session"], hits


def test_the_room_rule_separates_a_door_from_the_items():
    assert BARE_ROOM.search("Setup: Settings &rsaquo; Integrations")
    assert BARE_ROOM.search("Add, edit and test accounts in Integrations.")
    assert BARE_ROOM.search("Open Integrations")
    assert not BARE_ROOM.search("Open MCP & Integrations")
    assert not BARE_ROOM.search("accounts in MCP &amp; Integrations.")
    assert not BARE_ROOM.search("No Integrations are switched on.")


def test_the_scan_reads_what_it_claims_to_read():
    files = set(_served_files())
    for expected in ("static/index.html", "static/app.js", "static/js/sessions.js",
                     "static/js/slashCommands.js", "static/js/workbench/workflowRoom.js"):
        assert expected in files, expected
    # and finds the text inside them, not nothing
    index = dict(_html_phrases((_REPO / "static/index.html").read_text(encoding="utf-8")))
    assert any(v == "Rename chat" for v in index.values())


# ── the row's Verify: a sweep of the served strings for the retired names ────


def test_no_phrase_a_person_reads_says_session_or_conversation():
    unexpected = {rel: hits for rel, hits in _chat_word_hits().items()
                  if rel not in CHAT_RESIDUE}
    assert not unexpected, (
        "A chat is a chat (`D-2026-10-03-01` §3). These read *session* or "
        "*conversation*:\n  " + "\n  ".join(
            f"{rel}:{ln}  {t}" for rel, hits in sorted(unexpected.items()) for ln, t in hits))


def test_no_door_names_the_room_by_its_old_name():
    unexpected = {rel: hits for rel, hits in _bare_room_hits().items()
                  if rel not in ROOM_RESIDUE}
    assert not unexpected, (
        "The room is *MCP & Integrations*, in the Workbench (`D-2026-10-03-01` §3, "
        "`P22-21`):\n  " + "\n  ".join(
            f"{rel}:{ln}  {t}" for rel, hits in sorted(unexpected.items()) for ln, t in hits))


def test_the_register_holds_nothing_already_done():
    live_chat, live_room = _chat_word_hits(), _bare_room_hits()
    settled = sorted(set(CHAT_RESIDUE) - set(live_chat)) + sorted(
        set(ROOM_RESIDUE) - set(live_room))
    assert not settled, (
        "These no longer carry a retired name, so their register entry is an "
        "excuse for nothing — take it out: " + ", ".join(settled))


def test_the_hand_off_is_exact_about_what_is_left():
    assert {r: len(h) for r, h in _chat_word_hits().items()} == {
        r: n for r, (n, _) in CHAT_RESIDUE.items()}
    assert {r: len(h) for r, h in _bare_room_hits().items()} == {
        r: n for r, (n, _) in ROOM_RESIDUE.items()}


# ── the tables a window's name is read from ───────────────────────────────────


def _node_eval(declaration: str, expr: str):
    out = subprocess.run(["node", "-e", f"{declaration}\nconsole.log(JSON.stringify({expr}));"],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    return json.loads(out)


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_the_shortcuts_panel_names_each_window_as_the_sidebar_does():
    src = (_REPO / "static/js/keyboard-shortcuts.js").read_text(encoding="utf-8")
    decl = js_binding(src, "KEYBIND_LABELS").replace("export const", "const", 1)
    labels = _node_eval(decl, "KEYBIND_LABELS")
    assert labels["open_memory"] == "Open Brain"
    assert labels["open_cookbook"] == "Open Forge"
    assert labels["new_session"] == "New chat"
    assert labels["incognito"] == "Toggle Nobody"
    retired = re.compile(r"\b(session|conversation|memory|cookbook|incognito)\b", re.I)
    assert not [v for v in labels.values() if retired.search(v)], labels


@pytest.mark.skipif(not _HAS_NODE, reason="node binary not on PATH")
def test_a_bookmark_is_called_what_the_sidebar_calls_it():
    """The route title map is an inline script in `index.html`; it is evaluated,
    not read, and each title must be a sidebar label."""
    html = (_REPO / "static/index.html").read_text(encoding="utf-8")
    m = re.search(r"var titles = \{.*?\};", html, re.S)
    assert m, "the route title map moved"
    titles = _node_eval(m.group(0), "titles")
    assert titles["/memory"] == "Brain — Pantheon"
    assert titles["/cookbook"] == "Forge — Pantheon"
    sidebar = set(re.findall(r'<span class="grow">([^<]+)</span>', html))
    # Email is a sidebar section, not a tool row: its title is the section's.
    email = re.search(r'id="email-section-title"[^>]*>.*?</svg>\s*(?:<span>)?([^<]+?)\s*<', html, re.S)
    assert email, "the Email section title moved"
    sidebar.add(email.group(1))
    for route, title in titles.items():
        name = title.split(" — ")[0]
        assert name in sidebar, f"{route} bookmarks as {name!r}, which no sidebar row says"


def test_every_window_close_button_is_called_close():
    """`NAV-U-11`: ten spellings of × — *Close memory modal*, *Close cookbook*,
    a bare ✖. The dialog carries the window's name; the button is *Close*."""
    html = (_REPO / "static/index.html").read_text(encoding="utf-8")
    buttons = re.findall(r'<button[^>]*class="close-btn"[^>]*>', html)
    assert buttons
    assert all('aria-label="Close"' in b for b in buttons), buttons
    unnamed = []
    for rel in _served_files():
        if not rel.endswith(".js"):
            continue
        for line, text in _js_phrases((_REPO / rel).read_text(encoding="utf-8")):
            for tag in re.findall(r'<button[^>]*class="close-btn"[^>]*>', text):
                if 'aria-label="Close"' not in tag and 'title="Close"' not in tag:
                    unnamed.append(f"{rel}:{line} {tag}")
    assert not unnamed, unnamed


def test_the_task_categories_use_the_names():
    from src.builtin_actions import ACTION_CATEGORY_ORDER, build_action_palette
    cats = {n["category"] for n in build_action_palette(include_admin_only=True)}
    assert "Brain" in ACTION_CATEGORY_ORDER and "Chats" in ACTION_CATEGORY_ORDER
    assert not cats & {"Memory", "Sessions", "Cookbook"}, cats
