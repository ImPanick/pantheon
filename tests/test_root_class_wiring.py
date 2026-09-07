# SPDX-License-Identifier: AGPL-3.0-or-later
"""B26 — the sidebar anti-flash guard was renamed on one side only.

`static/js/sidebar-layout.js` and the boot script in `static/index.html` put
`pan-sidebar-off`, `pan-sidebar-mini` and `pan-mobile-startup-sidebar-hidden`
on `<html>`. Every CSS rule that acted on them still selected `html.ody-…`:
sixteen selectors across `static/style.css` and `index.html`'s inline `<style>`,
none of which any code could match. The whole point of those rules is to run
*before* `sidebar-layout.js` does — they are the pre-paint layer, and
`.sidebar.hidden` is what hides the sidebar once JS has run — so nothing looked
broken in a screenshot. It just flashed the sidebar on every load for anyone
whose sidebar is off or mini, which is the exact thing the block exists to stop.

The class name is derived fresh from `localStorage['pantheon-sidebar-mode']` on
every load and is never itself persisted, so this needed a rename, not a
migration: there is no stored value carrying the old spelling.

This test is the guard, and it checks the join in both directions, because the
defect is visible from either end: CSS read a root class nothing wrote, and JS
wrote a root class nothing read. One assertion in one direction would have
passed on the broken tree if the sweep had gone the other way.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# A root class that CSS reads and no code writes. Each entry needs a reason,
# because "add it to the allowlist" is how a real hole gets closed on paper.
UNWRITTEN_BY_DESIGN = {
    "light": (
        "Pre-existing at the fork point `fff72ec`, where the same seven "
        "`:root.light` rules sat with no writer either. It is upstream's, it "
        "predates Pantheon, and Law 1 says we do not subtract. Named here so "
        "the next person finds the answer instead of the question."
    ),
}

# A root class that code writes and no CSS reads. Empty, and it should stay
# that way — an unread write is a dead line, not a feature.
UNREAD_BY_DESIGN: dict[str, str] = {}


def _strip_css_comments(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _strip_js_comments(text):
    # Block comments, then line comments. Good enough for the call sites this
    # walks; it errs towards deleting, which can only cost a finding, never
    # invent one.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", text)


def _blocks(html, tag):
    return re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.S | re.I)


def _css_sources():
    """(label, css) for every stylesheet this app actually ships, inline ones
    included. `static/lib/` is vendored and not ours to reason about."""
    out = []
    for name in ("static/style.css",):
        out.append((name, (ROOT / name).read_text(encoding="utf-8")))
    for page in ("static/index.html", "static/login.html"):
        text = (ROOT / page).read_text(encoding="utf-8")
        for i, block in enumerate(_blocks(text, "style")):
            out.append((f"{page} <style> #{i + 1}", block))
    return out


def _js_sources():
    out = []
    for path in sorted((ROOT / "static" / "js").rglob("*.js")):
        out.append((str(path.relative_to(ROOT)), path.read_text(encoding="utf-8")))
    for page in ("static/index.html", "static/login.html"):
        text = (ROOT / page).read_text(encoding="utf-8")
        for i, block in enumerate(_blocks(text, "script")):
            out.append((f"{page} <script> #{i + 1}", block))
    return out


_ROOT_SELECTOR = re.compile(r"(?:^|[\s,>+~(])(?:html|:root)((?:\.[A-Za-z0-9_-]+)+)")


def css_root_classes():
    """{class name: [where it is read]} for `html.x` / `:root.x` selectors."""
    found = {}
    for label, css in _css_sources():
        for chain in _ROOT_SELECTOR.findall(_strip_css_comments(css)):
            for name in chain.split(".")[1:]:
                found.setdefault(name, []).append(label)
    return found


# `document.documentElement.classList.add(` and `.toggle(`, plus the same call
# through a `const x = document.documentElement` alias. A bare identifier only:
# `_els.root.classList.toggle(...)` is a panel, not the document element, and
# matching it would put panel classes in a root-class check.
_ALIAS = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.documentElement\s*;")


def _call_sites(js):
    names = ["document\\.documentElement"]
    names += [re.escape(a) for a in _ALIAS.findall(js)]
    pattern = re.compile(
        r"(?<![\w$.])(?:" + "|".join(names) + r")\.classList\.(add|toggle)\s*\("
    )
    for m in pattern.finditer(js):
        depth, i = 1, m.end()
        while i < len(js) and depth:
            if js[i] == "(":
                depth += 1
            elif js[i] == ")":
                depth -= 1
            i += 1
        yield m.group(1), js[m.end():i - 1]


def _class_arguments(kind, args):
    """The arguments that are class names.

    `classList.add(a, b, c)` names three classes. `classList.toggle(a, force)`
    names one — the second argument is a boolean. Reading it as a class name is
    how `mode === 'mini'` turned into a root class called `mini`."""
    parts, depth, current = [], 0, ""
    for ch in args:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += ch
    parts.append(current)
    return parts[:1] if kind == "toggle" else parts


_LITERAL = re.compile(r"""(['"])([A-Za-z0-9_-]+)\1""")
_PREFIXED = re.compile(r"""(['"])([A-Za-z0-9_-]*-)\1\s*\+""")


def js_root_classes():
    """({class: [where written]}, {prefix: [where written]}).

    The second half exists because two of the four writers build the name:
    `'density-' + t.density` and `'ui-scale-' + _us`. A checker that only sees
    string literals would call every `density-*` rule unwritten and be wrong
    four times over."""
    literals, prefixes = {}, {}
    for label, js in _js_sources():
        body = _strip_js_comments(js)
        for kind, args in _call_sites(body):
            for arg in _class_arguments(kind, args):
                for m in _PREFIXED.finditer(arg):
                    prefixes.setdefault(m.group(2), []).append(label)
                for m in _LITERAL.finditer(_PREFIXED.sub(" ", arg)):
                    literals.setdefault(m.group(2), []).append(label)
    return literals, prefixes


def test_the_extractor_finds_the_sites_this_test_is_about():
    """Guards the test, not the app. Every assertion below is vacuous if the
    two extractors return nothing, and a regex that silently stops matching is
    the quietest way for a wiring check to go green forever."""
    css = css_root_classes()
    literals, prefixes = js_root_classes()
    assert "pan-sidebar-off" in css, css
    assert "static/style.css" in css["pan-sidebar-off"]
    assert any("index.html" in w for w in css["pan-sidebar-off"]), css["pan-sidebar-off"]
    assert "pan-sidebar-off" in literals, literals
    assert any("sidebar-layout.js" in w for w in literals["pan-sidebar-off"])
    assert "density-" in prefixes and "ui-scale-" in prefixes, prefixes


def test_every_root_class_the_css_reads_is_written_by_something():
    css = css_root_classes()
    literals, prefixes = js_root_classes()
    orphans = {
        name: sorted(set(where))
        for name, where in css.items()
        if name not in literals
        and name not in UNWRITTEN_BY_DESIGN
        and not any(name.startswith(p) for p in prefixes)
    }
    assert not orphans, (
        "CSS selects root classes that nothing puts on <html>. Either the "
        "writer was renamed and the reader was not (that was B26), or the "
        "rules are dead: " + repr(orphans)
    )


def test_every_root_class_the_code_writes_is_read_by_something():
    css = css_root_classes()
    literals, prefixes = js_root_classes()
    unread = {
        name: sorted(set(where))
        for name, where in literals.items()
        if name not in css and name not in UNREAD_BY_DESIGN
    }
    assert not unread, (
        "code puts root classes on <html> that no stylesheet acts on: "
        + repr(unread)
    )
    dead_prefixes = {
        prefix: sorted(set(where))
        for prefix, where in prefixes.items()
        if not any(name.startswith(prefix) for name in css)
    }
    assert not dead_prefixes, (
        "code builds root class names from a prefix no rule matches: "
        + repr(dead_prefixes)
    )


def test_the_old_spelling_is_gone_from_the_sidebar_guard():
    """The narrow form of the same fact. The two tests above would pass on a
    tree where *both* sides said `ody-`; this one says which spelling won."""
    for label, css in _css_sources():
        assert "ody-sidebar" not in css, label
        assert "ody-mobile-startup" not in css, label


@pytest.mark.parametrize("name", sorted(UNWRITTEN_BY_DESIGN))
def test_each_allowlisted_class_still_earns_its_place(name):
    """An allowlist entry for a class the CSS no longer reads is a stale excuse.
    Delete the entry when the last rule goes."""
    assert name in css_root_classes(), (
        f"{name!r} is allowlisted as read-but-unwritten and no rule reads it "
        "any more — remove the entry"
    )
    assert UNWRITTEN_BY_DESIGN[name].strip(), f"{name} needs a reason, not a blank"
