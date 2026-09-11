# SPDX-License-Identifier: AGPL-3.0-or-later
"""The operator's own list, checked here before a command leaves for the host.

`P17-11`. The owner asked for *"a settings page that is editable"* alongside the
*"definitive non-bypassable blacklist"*, and those are two different objects
doing two different jobs. Conflating them would produce one list that is neither.

**WHICH LIST IS THE BOUNDARY, STATED SO THE SETTINGS PAGE CAN SAY IT TOO.**

  * `netagent/guard.py` — **the boundary.** Compiled into the agent, on the host,
    with no flag, setting or launch argument that widens it. Pantheon cannot
    reach it, which is the entire point: Pantheon is the gated party, and a gate
    the gated party can edit is not a gate.
  * **this module** — the operator's preference, editable in Settings, checked
    **here** before the request is sent. It narrows what Pantheon will ask for.
    It is not a boundary and the UI says so, because a page that implies it is
    one would be the comfortable lie this project keeps a file about.

The honest value of the second list is real and worth having: it is how an
operator says *"never touch `git push`"* or *"only ever `docker` and `ipconfig`"*
without rebuilding the agent. It stops the agent reaching for things. It does not
stop a Pantheon that has stopped behaving.

**The allowlist, when set, wins.** An empty allowlist means "no opinion, use the
denylist"; a non-empty one means only these binaries, and the denylist still
applies inside it. That ordering is stated because the alternative — denylist
first — makes a non-empty allowlist do nothing in the case a person most expects
it to matter.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Sequence

# Settings keys. Both ship empty: no opinion, and the agent's own list is the
# only thing in force until a person writes one.
DENYLIST_KEY = "host_exec_denylist"
ALLOWLIST_KEY = "host_exec_allowlist"

# A pattern is matched as a plain substring against the normalised command, not
# as a regex. Deliberate: `src/tool_allow_rules.py` made the same call and wrote
# down why — a regex in a security-shaped setting is a way for a typo to widen
# the match silently, and `.*` is a very easy typo.
MAX_PATTERNS = 200
MAX_PATTERN_LENGTH = 200

_WS = re.compile(r"\s+")


class Decision(NamedTuple):
    allowed: bool
    reason: str = ""
    matched: str = ""
    source: str = ""


def _normalise(command: str) -> str:
    """The same shape `netagent.guard.normalise` produces.

    Imported rather than reimplemented where possible — but this module must work
    when `netagent` is not importable (Pantheon in a container that does not ship
    the agent), so there is a fallback and a test that the two agree.
    """
    try:
        from netagent.guard import normalise
        return normalise(command)
    except Exception:  # noqa: BLE001
        text = str(command or "").translate(str.maketrans("", "", "\"'`"))
        return _WS.sub(" ", text).strip().casefold()


def _leading(command: str) -> str:
    try:
        from netagent.execute import leading_binary
        return leading_binary(command)
    except Exception:  # noqa: BLE001
        import os
        import shlex
        try:
            parts = shlex.split(str(command or ""))
        except ValueError:
            parts = str(command or "").split()
        if not parts:
            return ""
        name = os.path.basename(parts[0].replace("\\", "/")).casefold()
        for suffix in (".exe", ".cmd", ".bat", ".com", ".ps1"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name


def _patterns(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for raw in value:
        text = str(raw or "").strip().casefold()
        if text and len(text) <= MAX_PATTERN_LENGTH and text not in out:
            out.append(text)
        if len(out) >= MAX_PATTERNS:
            break
    return out


def validate(value: Any, *, key: str) -> List[str]:
    """Problems with a proposed list, as sentences. Empty means fine.

    `P17-09`'s lesson applied before it can happen again: a list stored and then
    silently ignored is worse than a refusal, because the operator believes they
    set a rule.
    """
    problems: List[str] = []
    if value in (None, ""):
        return problems
    if not isinstance(value, (list, tuple)):
        return [f"{key} must be a list of text patterns."]
    if len(value) > MAX_PATTERNS:
        problems.append(f"{key} has {len(value)} entries; the limit is {MAX_PATTERNS}.")
    seen = set()
    for i, raw in enumerate(value):
        if not isinstance(raw, str):
            problems.append(f"{key} entry {i + 1} is a {type(raw).__name__}, not text.")
            continue
        text = raw.strip()
        if not text:
            problems.append(f"{key} entry {i + 1} is empty; remove it.")
            continue
        if len(text) > MAX_PATTERN_LENGTH:
            problems.append(f"{key} entry {i + 1} is longer than {MAX_PATTERN_LENGTH} characters.")
        if text.casefold() in seen:
            problems.append(f"{key} lists {text!r} twice.")
        seen.add(text.casefold())
    return problems


def check(command: str, *, denylist: Sequence[str] = (),
          allowlist: Sequence[str] = ()) -> Decision:
    """May Pantheon send this command to the host agent?

    Says nothing about whether the **agent** will run it — the agent decides that
    for itself and cannot be talked out of it. This is the operator's preference,
    applied first so a command they did not want is never sent at all.
    """
    normalised = _normalise(command)
    if not normalised:
        return Decision(False, "an empty command is not a command", source="empty")

    allowed_binaries = _patterns(allowlist)
    if allowed_binaries:
        binary = _leading(command)
        if binary not in allowed_binaries:
            return Decision(
                False,
                f"{binary!r} is not in your host-command allowlist "
                f"({', '.join(allowed_binaries)}). Edit it in Settings → Networks.",
                matched=binary, source="allowlist")

    for pattern in _patterns(denylist):
        if pattern in normalised:
            return Decision(
                False,
                f"your host-command denylist refuses this: it contains {pattern!r}. "
                f"Edit it in Settings → Networks.",
                matched=pattern, source="denylist")
    return Decision(True)


def from_settings() -> Dict[str, List[str]]:
    try:
        from src.settings import get_setting
        return {"denylist": _patterns(get_setting(DENYLIST_KEY, [])),
                "allowlist": _patterns(get_setting(ALLOWLIST_KEY, []))}
    except Exception:  # noqa: BLE001
        # Unreadable settings means "no operator opinion", never "allow
        # everything past the agent" — the agent's own list is untouched either
        # way, so this fails to the safe side by construction rather than by
        # care here.
        return {"denylist": [], "allowlist": []}


def check_from_settings(command: str) -> Decision:
    lists = from_settings()
    return check(command, denylist=lists["denylist"], allowlist=lists["allowlist"])
