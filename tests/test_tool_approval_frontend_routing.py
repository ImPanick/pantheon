# SPDX-License-Identifier: AGPL-3.0-or-later
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

# `B1104`. THE approval-path modules — the one place they are listed. Their
# `?v=` cache-buster moves together or a browser pairs new code with a cached
# copy and the approval click lands on the New-chat branch. `FORBIDDEN.md` said
# "six" and this test checked five; measured on `7a7f9b2` by following one
# approval click through the code, six is true and the one missing was
# `app.js`: it owns the send button's own click handler — the New chat /
# Record voice branch a misrouted approval click lands on — and it imports
# `chat.js`, `chatRenderer.js` and `compare/index.js` by versioned URL, so a
# cached `app.js` loads the PREVIOUS `chat.js` beside the new one (ES module
# identity is the URL with its query, `P3-11`). Its own buster (`index.html`'s
# script tag and modulepreload, `sw.js`'s precache entry) was checked nowhere:
# with it left a wave behind, the lockstep case below still passed. The prose
# points here rather than repeating a count, so there is one number (`Law 7`).
# Path relative to `static/js/`, except `app.js`, which is `static/app.js`.
APPROVAL_PATH_MODULES = {
    "chatRenderer.js": "draws the card; an answer dispatches `pantheon:tool-approval`",
    "chat.js": "hears it, keeps the sealed id and decision, clicks the send button",
    "chatStream.js": "catches that synthetic click and submits the chat form instead",
    "app.js": "owns the send button's own click (New chat / Record voice) and imports "
              "chat.js, chatRenderer.js and compare/index.js",
    "compare/index.js": "a Compare pane's own approval continuation",
    "compare/stream.js": "answers a pane's card through the shared chatRenderer",
}

# A versioned module reference: `"./chat.js?v=…"`, `'/static/app.js?v=…'`,
# `("../chatRenderer.js?v=…")`. Resolved to a file below, so `./stream.js` in
# `compare/index.js` is `compare/stream.js` and `search-chat.js` is not
# `chat.js` — a name match got both of those wrong.
_VERSIONED = re.compile(r"""["'(]([^"'()\s]+?\.js)\?v=([A-Za-z0-9._-]+)""")


def _module_file(name: str) -> Path:
    return (STATIC / name if name == "app.js" else STATIC / "js" / name).resolve()


def _versioned_references():
    """`(file, module file, version)` for every versioned `.js` reference in
    `static/` (bundles under `lib/` excepted), its specifier resolved against
    the file that holds it."""
    for path in sorted(STATIC.rglob("*")):
        if path.suffix not in (".js", ".html") or "/lib/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for spec, version in _VERSIONED.findall(text):
            if spec.startswith("/static/"):
                target = (STATIC / spec[len("/static/"):]).resolve()
            elif spec.startswith(("./", "../")):
                target = (path.parent / spec).resolve()
            else:
                continue
            yield path, target, version


def _wave_version() -> str:
    # The string is READ from the page rather than written here. It was a
    # literal until `P5-08` had to move it, and a literal makes the test a
    # second place the version lives — `Law 6`, and the control this test
    # exists to hold is *lockstep*, not any particular value. `index.html`'s
    # `chat.js` script tag is the canonical execution site, so it is the one
    # that defines what the wave is called; every other site has to agree.
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    return re.search(r"js/chat\.js\?v=([A-Za-z0-9._-]+)", index).group(1)


def test_tool_approval_bypasses_polymorphic_send_button_actions():
    root = Path(__file__).resolve().parents[1]
    chat = (root / "static/js/chat.js").read_text(encoding="utf-8")
    stream = (root / "static/js/chatStream.js").read_text(encoding="utf-8")

    # chat.js still defers the sealed approval through a synthetic button click.
    assert "if (sendButton) sendButton.click();" in chat

    # The capture listener must intercept only that synthetic click and route it
    # through the chat form submit path, before app.js can reinterpret an empty
    # composer as New chat or Record voice.
    assert "if (event.isTrusted) return;" in stream
    assert "event.stopImmediatePropagation();" in stream
    assert "chatForm.requestSubmit()" in stream
    assert "sendButton.dataset.mode = ''" not in stream


def test_ask_user_close_button_uses_one_css_glyph():
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "static/js/chatRenderer.js").read_text(encoding="utf-8")
    styles = (root / "static/style.css").read_text(encoding="utf-8")

    assert "closeBtn.className = 'modal-close ask-user-close';" in renderer
    assert "closeBtn.setAttribute('aria-label', 'Dismiss question');" in renderer
    assert "closeBtn.textContent = '×';" not in renderer
    assert ".modal-close::before" in styles


def test_ask_user_number_shortcuts_reuse_option_click_path():
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "static/js/chatRenderer.js").read_text(encoding="utf-8")
    start = renderer.index("function _handleAskUserShortcut(event)")
    end = renderer.index("document.addEventListener('keydown', _handleAskUserShortcut);", start)
    shortcut = renderer[start:end]

    assert "if (!/^[1-3]$/.test(event.key)) return;" in shortcut
    assert "event.repeat" in shortcut
    assert "event.ctrlKey" in shortcut
    assert "event.altKey" in shortcut
    assert "event.metaKey" in shortcut
    assert "event.shiftKey" in shortcut
    assert "input, textarea, select, [contenteditable=\"true\"]" in shortcut
    assert "card.querySelectorAll('.ask-user-option')[Number(event.key) - 1]" in shortcut
    assert "event.preventDefault();" in shortcut
    assert "option.click();" in shortcut


def test_digit_shortcuts_never_answer_a_tool_approval_card():
    """A stray digit must not grant a scope the user did not deliberately pick."""

    root = Path(__file__).resolve().parents[1]
    renderer = (root / "static/js/chatRenderer.js").read_text(encoding="utf-8")
    start = renderer.index("function _handleAskUserShortcut(event)")
    end = renderer.index("document.addEventListener('keydown', _handleAskUserShortcut);", start)
    shortcut = renderer[start:end]

    assert "if (card.dataset.askUserKind === 'tool_approval') return;" in shortcut
    # The renderer has to label the card for that guard to ever fire.
    assert (
        "card.dataset.askUserKind = isToolApproval ? 'tool_approval' : 'question';"
        in renderer
    )


def test_ask_user_renderer_accepts_scoped_root_and_submit_callback():
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "static/js/chatRenderer.js").read_text(encoding="utf-8")

    assert "const chatBox = renderOptions.root || document.getElementById('chat-history');" in renderer
    assert "const onSubmit = typeof renderOptions.onSubmit === 'function'" in renderer
    assert "kind: 'answer'" in renderer
    assert "kind: 'tool_approval'" in renderer
    assert "if (accepted !== false) card.remove();" in renderer
    assert "document.dispatchEvent(new CustomEvent('pantheon:tool-approval', { detail }))" in renderer


def test_every_changed_approval_module_is_cache_busted_together():
    """A stale module here silently reinterprets the approval click.

    chat.js leaves the composer empty and clicks the polymorphic send button,
    so a browser that pairs the new chat.js with a cached chatStream.js has no
    interceptor and lands on the New chat branch instead. The same holds for
    the compare pane modules, which chatRenderer now shares a keydown listener
    with, and for `app.js`, which owns that branch and imports the rest
    (`B1104`, `APPROVAL_PATH_MODULES` above).
    """
    version = _wave_version()

    # Every versioned reference to any approval-path module, across the whole
    # of `static/` — a stale one pairs new code with a cached interceptor and
    # the approval click lands on the New-chat branch.
    modules = {_module_file(name): name for name in APPROVAL_PATH_MODULES}
    stale = {}
    for path, target, found in _versioned_references():
        if target in modules and found != version:
            stale.setdefault(str(path.relative_to(ROOT)), set()).add(f"{modules[target]}={found}")
    assert not stale, f"approval-path modules out of lockstep with {version}: {stale}"

    # And the sites the original form of this test named one by one, kept so a
    # scan that quietly stopped finding anything cannot pass by being empty.
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    chat = (STATIC / "js/chat.js").read_text(encoding="utf-8")
    compare_index = (STATIC / "js/compare/index.js").read_text(encoding="utf-8")
    compare_stream = (STATIC / "js/compare/stream.js").read_text(encoding="utf-8")
    assert f"chatStream.js?v={version}" in index
    assert f"chatStream.js?v={version}" in chat
    assert f"compare/index.js?v={version}" in app
    assert f"stream.js?v={version}" in compare_index
    # One chatRenderer instance, so the ask_user keydown listener binds once.
    assert f"chatRenderer.js?v={version}" in compare_stream
    # `B1104`. `app.js`'s own buster — the one the list of five never read.
    assert f"/static/app.js?v={version}" in index


def test_every_approval_path_module_is_found_by_the_scan():
    """`B1104`. Each listed module is reached by at least one versioned
    reference the scan resolves — otherwise its lockstep is checked nowhere
    and the case above passes by finding nothing, as `app.js`'s did."""
    reached = {target for _path, target, _version in _versioned_references()}
    missing = [name for name in APPROVAL_PATH_MODULES if _module_file(name) not in reached]
    assert not missing, f"no versioned reference resolves to: {missing}"
    for name in APPROVAL_PATH_MODULES:
        assert _module_file(name).is_file(), name


# Listens for the approval event and is still not on the path: its listener
# repaints the trust ladder's list of grants after an answer, and nothing
# about where the click lands. It is imported with no buster at all
# (`chatRenderer.js`: `from './trustLadder.js'`), so it has no string to move.
_HEARS_THE_EVENT_OFF_THE_PATH = {"trustLadder.js": "repaints the grants list"}

# The approval event's two shapes in code (`Law 20`: the call, not the word —
# comments name the event in prose).
_EVENT_CODE = re.compile(
    r"""(?:addEventListener|dispatchEvent\(\s*new\s+CustomEvent)\(\s*['"]pantheon:tool-approval['"]""")


def test_every_module_that_sends_or_hears_the_approval_event_is_listed():
    """`B1104`, the list's completeness from the far end: a module that sends
    or hears `pantheon:tool-approval` is on the approval path, or is named
    here with the reason it is not. A new listener cannot join the click's
    route without joining the lockstep."""
    found = set()
    for path in sorted((STATIC / "js").rglob("*.js")):
        if "/lib/" in path.as_posix():
            continue
        if _EVENT_CODE.search(path.read_text(encoding="utf-8")):
            found.add(path.relative_to(STATIC / "js").as_posix())
    assert found, "the scan found no module using the approval event"
    unlisted = found - set(APPROVAL_PATH_MODULES) - set(_HEARS_THE_EVENT_OFF_THE_PATH)
    assert not unlisted, f"on the approval event's route but not in APPROVAL_PATH_MODULES: {unlisted}"
