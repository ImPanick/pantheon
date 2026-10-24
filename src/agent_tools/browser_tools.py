# SPDX-License-Identifier: AGPL-3.0-or-later
"""`agent_browser` — the agent browser: the person's own Firefox in their
workstation, driven by the agent and watched (and taken over) by the person in
the app. `P25-05`.

One call is one action — `open` a page, `read` it, `click` or `type` into one
of the elements `read` numbered, `press` keys, `scroll`, go `back`,
`forward` or `reload`, list `tabs`, open, switch to or close one, or take a
`screenshot` of the page. The daemon does the driving (`workstation/browser.py`,
WebDriver BiDi); this module is the model's side of it.

Named `agent_browser`, not `browser`: `disable_tool browser` already means
the built-in Playwright server (`builtin_browser`), and one word meaning two
switches is how an admin turns off the wrong one.

**Where it is offered.** Exactly where `computer` is: when the workstation
would answer this person (`computer_tools.unavailable_reason`, the same
question, so the two cannot disagree about who has a workstation). Without
one the tool is not offered and the window says why.

**What each action is** (`tool_capabilities._ACTION_CAPABILITIES`): reading
a page, a screenshot, the tab list and switching between tabs only look;
opening a page, going back or forward and reloading reach the web; a click,
typing into a page and pressing a key can send something — a form, a
purchase, a message — so they are outward side effects and ask wherever the
person's rung asks for one. Everything a page says is a stranger's words.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

from workstation import protocol as P

logger = logging.getLogger(__name__)

TOOL_NAME = "agent_browser"
SCREENSHOT = "screenshot"
# `P26-03`. The agent reads the person's notes and closes them; making,
# changing and removing a note, and marking notes sent, are the person's.
PERSON_ONLY = ("frame", "note_add", "note_edit", "note_remove", "notes_sent")
ACTIONS: Tuple[str, ...] = tuple(a for a in P.BROWSER_ACTIONS if a not in PERSON_ONLY) + (SCREENSHOT,)
READ_TEXT_MAX = 8_000

BUSY_ADVICE = ("Nothing was done in the browser. Do not keep retrying: ask the person what they "
               "need with `ask_user`, or end your turn and say you are waiting for the browser.")


def parse_args(content: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    if isinstance(content, dict):
        raw: Any = dict(content)
    else:
        text = str(content or "").strip()
        if not text:
            return {}, f"`agent_browser` needs an action: one of {', '.join(ACTIONS)}."
        if text.startswith("{"):
            try:
                raw = json.loads(text)
            except ValueError:
                return {}, ('`agent_browser` arguments are a JSON object, such as '
                            '{"action": "open", "url": "https://example.org"}.')
        else:
            raw = {"action": text.split()[0]}
    if not isinstance(raw, dict):
        return {}, "`agent_browser` arguments are a JSON object."
    a = dict(raw)
    from src.tool_capabilities import _ACTION_ALIASES
    action = str(a.get("action") or "").strip().lower().replace("-", "_").replace(" ", "_")
    action = dict(_ACTION_ALIASES.get(TOOL_NAME, {})).get(action, action)
    if action not in ACTIONS:
        return {}, f"“{a.get('action')}” is not an `agent_browser` action. It is one of {', '.join(ACTIONS)}."
    a["action"] = action
    for key in ("ref", "x", "y", "dx", "dy", "tab"):
        v = a.get(key)
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            a[key] = int(v.strip())
        elif isinstance(v, float) and v == v:
            a[key] = int(round(v))
    if action == "scroll" and "dy" not in a and "dx" not in a:
        direction = str(a.get("direction") or "down").lower()
        amount = a.get("amount", 5) if isinstance(a.get("amount", 5), int) else 5
        a["dy"] = {"down": amount, "up": -amount}.get(direction, 0)
        a["dx"] = {"right": amount, "left": -amount}.get(direction, 0)
    return a, None


def describe(args: Dict[str, Any]) -> str:
    action = args.get("action")
    if action == "open":
        return f"open {args.get('url')}"
    if action == "click":
        return f"click [{args['ref']}]" if args.get("ref") is not None else f"click at ({args.get('x')}, {args.get('y')})"
    if action == "type":
        text = str(args.get("text") or "")
        shown = text if len(text) <= 40 else text[:39] + "…"
        where = f" into [{args['ref']}]" if args.get("ref") is not None else ""
        return f"type “{shown}”{where}{' and Enter' if args.get('submit') else ''}"
    if action == "login":
        return f"sign in with “{args.get('item') or '?'}”"
    if action == "notes":
        return "read the person's notes" + (" on every page" if args.get("all") else "")
    if action == "note_done":
        which = args.get("notes") or args.get("note")
        return f"{'decline' if args.get('declined') else 'close'} note {which}"
    if action == "press":
        return f"press {args.get('keys')}"
    if action == "scroll":
        return f"scroll {'down' if (args.get('dy') or 0) >= 0 else 'up'}"
    if action in ("tab_new", "tab_switch", "tab_close"):
        return f"{action.replace('_', ' ')} {args.get('url') or args.get('tab') or ''}".strip()
    return str(action)


def command_line(content: Any) -> str:
    args, problem = parse_args(content)
    return str(content or "").strip()[:200] if problem else describe(args)


def page_text(answer: Dict[str, Any]) -> str:
    """A `read` answer as the model reads it: the page, then its elements."""
    lines = [f"Page: {answer.get('title') or '(untitled)'} — {answer.get('url') or ''}", ""]
    text = str(answer.get("text") or "").strip()
    if len(text) > READ_TEXT_MAX:
        text = text[:READ_TEXT_MAX] + "\n…"
    lines.append(text or "(The page has no text.)")
    if answer.get("cut"):
        lines.append("(The page is longer; scroll and read again for the rest.)")
    els = answer.get("elements") or []
    if els:
        lines += ["", "Elements you can click or type into, by number:"]
        for e in els:
            kind = e.get("tag") if e.get("tag") != "input" else f"input {e.get('type') or 'text'}"
            label = f" “{e['label']}”" if e.get("label") else ""
            href = f" → {e['href']}" if e.get("href") else ""
            off = " (disabled)" if e.get("disabled") else ""
            lines.append(f"[{e['ref']}] {kind}{label}{href}{off}")
    return "\n".join(lines)


def notes_text(answer: Dict[str, Any], *, closed: bool = False) -> str:
    """`P26-03`. The person's notes as the model reads them: each by its
    number, the element it is pinned to, what the person said, and where the
    element is now. Done and declined notes are left out of a listing."""
    notes = [n for n in (answer.get("notes") or []) if n.get("status") in ("open", "sent")]
    head = "Closed. " if closed else ""
    if not notes:
        return head + "No open notes on this page."
    lines = [f"{head}{len(notes)} open note{'s' if len(notes) != 1 else ''} on {answer.get('url') or 'this page'}:"]
    for n in notes:
        a = n.get("anchor") or {}
        what = f"{a.get('tag') or 'element'}{(' “' + a['text'] + '”') if a.get('text') else ''}"
        where = (" — that element is no longer on the page" if n.get("lost")
                 else (f" — scrolled {n['where']}" if n.get("where") in ("above", "below") else ""))
        drawn = f" ({len(n['shapes'])} drawing{'s' if len(n['shapes']) != 1 else ''})" if n.get("shapes") else ""
        page = "" if n.get("page") == (answer.get("url") or "").split("#", 1)[0] else f" [on {n.get('page')}]"
        lines.append(f"Note {n.get('n')}: on {what}{where}{page}{drawn}: {n.get('text') or '(no words)'}")
    lines.append("When you have done one, or cannot, close it: note_done with its number, and said "
                 "for what you did or why not (declined: true when you did not).")
    return "\n".join(lines)


def _where_now(answer: Dict[str, Any]) -> str:
    tabs = answer.get("tabs") or []
    tab_line = ""
    if len(tabs) > 1:
        tab_line = " Tabs: " + "; ".join(
            f"{n}{' (this one)' if t.get('current') else ''} {t.get('url')}" for n, t in enumerate(tabs, 1))
    return f"Now at {answer.get('title') or '(untitled)'} — {answer.get('url') or ''}.{tab_line}"


class BrowserTool:
    """One action on the person's browser."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        from src.workstation_access import ensure_ready
        from src.workstation_client import WorkstationError

        owner = (ctx or {}).get("owner")
        args, problem = parse_args(content)
        if problem:
            return {"error": problem, "exit_code": 1}
        action = args["action"]
        try:
            ready = await ensure_ready(owner)
        except WorkstationError as e:
            return e.as_result()
        client, account = ready.client, ready.account
        fields = {k: v for k, v in args.items()
                  if k in ("url", "ref", "x", "y", "text", "submit", "keys", "dx", "dy", "tab", "double",
                           "note", "notes", "said", "declined", "all")}
        if action == "login":
            return await _login(client, account, owner, args, session=(ctx or {}).get("session_id"),
                                agent=(ctx or {}).get("agent_id"))
        try:
            if action == SCREENSHOT:
                shot = await client.browser(account, "frame")
                return {"output": f"The page is attached ({shot.get('width')}×{shot.get('height')}). "
                                  + _where_now(shot), "exit_code": 0, "ran_in": "workstation",
                        "images": [{"data": shot["data_b64"], "mimeType": shot.get("mime") or "image/png"}],
                        "screenshot_caption": f"Browser: {shot.get('title') or shot.get('url') or 'page'}"}
            answer = await client.browser(account, action, **fields)
        except WorkstationError as e:
            if e.code == "busy":
                return {"error": f"{e.message} {BUSY_ADVICE}", "exit_code": 1, "workstation_error": e.code}
            return e.as_result()
        answer = answer or {}
        if action == "read":
            return {"output": page_text(answer), "exit_code": 0, "ran_in": "workstation",
                    "url": answer.get("url")}
        if action in ("notes", "note_done"):
            return {"output": notes_text(answer, closed=action == "note_done"), "exit_code": 0,
                    "ran_in": "workstation", "url": answer.get("url")}
        if action == "tabs":
            tabs = answer.get("tabs") or []
            listing = "\n".join(f"{n}. {t.get('url')}{' (this one)' if t.get('current') else ''}"
                                for n, t in enumerate(tabs, 1))
            return {"output": f"{len(tabs)} tab{'s' if len(tabs) != 1 else ''}:\n{listing}",
                    "exit_code": 0, "ran_in": "workstation"}
        return {"output": f"Did: {describe(args)}. {_where_now(answer)} Read the page to see it.",
                "exit_code": 0, "ran_in": "workstation", "url": answer.get("url")}


async def _login(client, account: str, owner: Optional[str], args: Dict[str, Any], *,
                 session: Optional[str] = None, agent: Optional[str] = None) -> Dict[str, Any]:
    """`P27-06`. Sign in on the open page with a login from the person's
    vault, by its name. The values go from the vault to the daemon in one
    request and from there into the page's fields; what comes back to the
    model is which fields were filled and where the page went — never a value."""
    from core.database import SessionLocal
    from src import vault as V
    from src.workstation_client import WorkstationError

    item = str(args.get("item") or args.get("login") or "").strip()
    if not item:
        return {"error": "`login` needs “item”: the name of a login in the person's vault.", "exit_code": 1}
    db = SessionLocal()
    try:
        got = await V.resolve(db, owner, item, by="agent_browser", session=session, agent=agent)
    except V.VaultRefused as r:
        return {"error": r.sentence, "exit_code": 1}
    finally:
        db.close()
    if got["kind"] != "login":
        return {"error": f"“{got['label']}” is a {got['kind']}, not a login; it cannot fill a sign-in form.",
                "exit_code": 1}
    values = [got["username"], got["secret"], got["otp"]]
    try:
        answer = await client.browser(account, "login", origins=got["origins"], label=got["label"],
                                      username=got["username"], secret=got["secret"], otp=got["otp"]) or {}
    except WorkstationError as e:
        if e.code == "busy":
            return {"error": f"{e.message} {BUSY_ADVICE}", "exit_code": 1, "workstation_error": e.code}
        res = e.as_result()
        if isinstance(res.get("error"), str):
            res["error"] = V.scrub(res["error"], values)
        return res
    filled = ", ".join(answer.get("filled") or []) or "nothing"
    tail = (" The page still shows a password field, so the sign-in may have been refused: read the page."
            if answer.get("still_asking") else " Read the page to see where it went.")
    return {"output": V.scrub(f"Signed in with “{got['label']}”: filled the {filled} and sent the form. "
                              f"{_where_now(answer)}{tail}", values),
            "exit_code": 0, "ran_in": "workstation", "url": answer.get("url")}
