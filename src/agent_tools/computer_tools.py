# SPDX-License-Identifier: AGPL-3.0-or-later
"""`computer` — the agent sees the workstation's screen and works its mouse and
keyboard. `P20-04`, `D-2026-09-30-03`.

The owner asked for *"full computer use mode"*. This is the tool: one call is one
action on the person's own display inside the workstation — a screenshot, or one
of `workstation/protocol.py`'s `INPUT_ACTIONS` — and every action that is not a
screenshot comes back with a screenshot taken after it (`screenshot_after`), so
the model always sees what its click did rather than guessing.

**COORDINATES ARE THE SCREENSHOT'S OWN PIXELS.** The screen is a fixed
`SCREEN_WIDTH` × `SCREEN_HEIGHT` (the protocol states it once, `Law 7`), so
there is no scaling for either side to get wrong: a point read off the picture
is the point clicked. Bounds are checked by the daemon, which is the one
validator — a click off the screen comes back as the daemon's sentence, not as
a second rule restated here.

**WHERE IT IS OFFERED.** Only when `workstation_for(owner)` would succeed — the
workstation is on, has an address, and this person may use it
(`src/workstation_access.py`, three conditions, a sentence for each). The agent
loop hides the tool otherwise (`unavailable_reason`), and the handler asks the
same question again at call time, because an admin can switch the workstation
off between the turn starting and the call landing, and a tool that then ran
somewhere else would be the one outcome `P20` exists to prevent.

**WHAT IT HANDS BACK.** The picture travels in `images`, the envelope key
`FORBIDDEN.md` protects and `mcp_manager` already fills for a browser
screenshot, so it reaches the model and the tool card through the one path
every tool image takes (`src/tool_result_images.py`) — not a second one for this
tool (`Law 14`). `screenshot_caption` says what the picture is, for the card's
summary line and for the words beside the image in the model's context.

**`busy` IS A SENTENCE THE MODEL CAN ACT ON.** While a person holds the screen
(`P20-05`'s take-over, the protocol's `control`) the daemon refuses the agent's
input. The refusal says so, says nothing was done, and says what to do instead
— ask, or stop and wait — because a model told only "409" retries the click
in a loop.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from workstation import protocol as P

logger = logging.getLogger(__name__)

TOOL_NAME = "computer"
SCREENSHOT = "screenshot"
# Every action the tool takes, in the order the schema lists them: the
# screenshot, then the protocol's input actions exactly as the protocol names
# them (`Law 7` — a new input action reaches the model by being added there).
#: `B1756`. The phone's own controls — what a person presses in its window
#: (the side and navigation keys, rotate, fold, an address, the device list) —
#: so the agent works the phone exactly as a person does, through the same
#: route and the same holder, not a side channel. Each one is on the phone.
PHONE_CONTROLS: Tuple[str, ...] = ("press", "rotate", "fold", "unfold", "open_url", "use_device")
ACTIONS: Tuple[str, ...] = (SCREENSHOT,) + tuple(P.INPUT_ACTIONS) + PHONE_CONTROLS

# Spellings a model trained on another computer-use tool reaches for. Accepted
# rather than refused because a refusal of a synonym is a wasted round that the
# person watches happen; the schema still names only the canonical ones.
_ACTION_ALIASES = {
    "left_click": "click",
    "mouse_move": "move",
    "left_click_drag": "drag",
    "left_mouse_down": "mouse_down",
    "left_mouse_up": "mouse_up",
    "take_screenshot": SCREENSHOT,
}
# The fields an input action may carry, as the protocol's `input` route names
# them. Anything else in the arguments is not sent.
_INPUT_FIELDS = ("x", "y", "to_x", "to_y", "dx", "dy", "text", "keys", "ms")
_INT_FIELDS = ("x", "y", "to_x", "to_y", "dx", "dy", "ms", "mark", "to_mark")
#: `G4` (`D-2026-11-01-04`). The actions a mark stands in for a point in: the
#: mark's middle is the point. `type` with a mark clicks it first, so "type
#: into field 4" is one call.
MARK_ACTIONS = ("click", "double_click", "triple_click", "right_click", "middle_click", "move",
                "drag", "scroll", "mouse_down", "mouse_up", "type")
SURFACE = "desktop"
#: `B1751`. The screens the tool works: the desktop, and the person's phone —
#: a real Android device on a screen of its own (`workstation/phone.py`), where
#: a click is a tap, a drag a swipe and the wheel a fling. Each keeps its own
#: marks (`screen_marks`' surface), since a number means a place on one screen.
SCREENS = ("desktop", "phone")
PHONE_SURFACE = "phone"
_NUMBER_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*$")
_SCROLL_DIRECTIONS = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}

BUSY_ADVICE = (
    "Nothing was done on the screen. Do not keep retrying: ask the person what they "
    "need with `ask_user`, or end your turn and say you are waiting for the screen."
)


def _as_int(value: Any) -> Any:
    """A whole number where the model sent one in another spelling (`640.0`,
    `"640"`); anything else unchanged, so the daemon refuses it in its own
    words rather than this module guessing."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value == value:  # not NaN
        return int(round(value))
    if isinstance(value, str) and _NUMBER_RE.match(value):
        return int(round(float(value)))
    return value


def parse_args(content: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """`(arguments, problem)`. The arguments are normalised — the action
    lower-cased and de-aliased, `coordinate: [x, y]` spread into `x`/`y`, a
    scroll direction turned into `dx`/`dy`, numbers made whole. `problem` is a
    sentence for the model when there is nothing to do."""
    if isinstance(content, dict):
        raw: Any = dict(content)
    else:
        text = str(content or "").strip()
        if not text:
            return {}, (f"`{TOOL_NAME}` needs an action: one of {', '.join(ACTIONS)}.")
        if text.startswith("{"):
            try:
                raw = json.loads(text)
            except ValueError:
                return {}, (f"`{TOOL_NAME}` arguments are a JSON object, such as "
                            '{"action": "click", "x": 640, "y": 400}.')
        else:
            # A bare word is the one-argument form: "screenshot".
            raw = {"action": text.split()[0]}
    if not isinstance(raw, dict):
        return {}, f"`{TOOL_NAME}` arguments are a JSON object."
    args: Dict[str, Any] = dict(raw)
    action = str(args.get("action") or "").strip().lower().replace("-", "_").replace(" ", "_")
    action = _ACTION_ALIASES.get(action, action)
    if action not in ACTIONS:
        return {}, (f"“{args.get('action')}” is not an action `{TOOL_NAME}` knows. It is one "
                    f"of {', '.join(ACTIONS)}.")
    args["action"] = action
    if action in PHONE_CONTROLS:
        args["screen"] = "phone"   # `B1756`: the phone's own controls
    screen = str(args.get("screen") or "desktop").strip().lower()
    if screen in ("android", "mobile", "device"):
        screen = "phone"
    if screen not in SCREENS:
        return {}, f"“screen” is one of {', '.join(SCREENS)}."
    args["screen"] = screen
    for pair, (kx, ky) in (("coordinate", ("x", "y")), ("to_coordinate", ("to_x", "to_y"))):
        point = args.get(pair)
        if isinstance(point, (list, tuple)) and len(point) == 2:
            args.setdefault(kx, point[0])
            args.setdefault(ky, point[1])
    direction = str(args.get("scroll_direction") or args.get("direction") or "").lower()
    if action == "scroll" and direction in _SCROLL_DIRECTIONS and "dx" not in args and "dy" not in args:
        amount = _as_int(args.get("scroll_amount", args.get("amount", 3)))
        amount = amount if isinstance(amount, int) and not isinstance(amount, bool) else 3
        ux, uy = _SCROLL_DIRECTIONS[direction]
        args["dx"], args["dy"] = ux * amount, uy * amount
    for key in _INT_FIELDS:
        if key in args:
            args[key] = _as_int(args[key])
    for key in ("mark", "to_mark"):
        # `G4`: "[7]", "#7", "mark 7" are seven.
        v = args.get(key)
        if isinstance(v, str):
            digits = re.sub(r"[^0-9]", "", v)
            args[key] = int(digits) if digits else v
        elif v is None:
            args.pop(key, None)
    return args, None


def _point(args: Dict[str, Any], kx: str = "x", ky: str = "y") -> str:
    return f"({args.get(kx)}, {args.get(ky)})"


def describe_action(args: Dict[str, Any]) -> str:
    """One line a person reads: *click at (640, 400)*, *type “hello”*. The tool
    card's command line and the screenshot's summary are both this, so the card
    says what was done without the raw arguments (they stay one click away)."""
    action = args.get("action")
    if action in PHONE_CONTROLS:  # `B1756`
        return "phone: " + {
            "press": f"press {str(args.get('button') or '').replace('_', ' ')}",
            "rotate": "rotate", "fold": "fold", "unfold": "unfold",
            "open_url": f"open {args.get('url')}",
            "use_device": f"use the {_device_name(args.get('device'))}",
        }[action]
    if args.get("screen") == "phone":  # `B1751`
        return "phone: " + describe_action({k: v for k, v in args.items() if k != "screen"})
    if action == SCREENSHOT:
        return "screenshot"
    if args.get("mark") is not None:
        named = f" “{args['mark_name']}”" if args.get("mark_name") else ""
        at = f" at {_point(args)}" if args.get("x") is not None else ""
        if action == "type":
            text = str(args.get("text") or "")
            shown = text if len(text) <= 40 else text[:39] + "…"
            return f"type “{shown}” into mark {args['mark']}{named}"
        return f"{action.replace('_', ' ')} mark {args['mark']}{named}{at}"
    if action in ("click", "double_click", "triple_click", "right_click", "middle_click"):
        return f"{action.replace('_', ' ')} at {_point(args)}"
    if action == "move":
        return f"move to {_point(args)}"
    if action == "drag":
        return f"drag from {_point(args)} to {_point(args, 'to_x', 'to_y')}"
    if action in ("mouse_down", "mouse_up"):
        where = f" at {_point(args)}" if args.get("x") is not None else ""
        return action.replace("_", " ") + where
    if action == "scroll":
        parts = []
        dy, dx = args.get("dy") or 0, args.get("dx") or 0
        if isinstance(dy, int) and dy:
            parts.append(f"{'down' if dy > 0 else 'up'} {abs(dy)}")
        if isinstance(dx, int) and dx:
            parts.append(f"{'right' if dx > 0 else 'left'} {abs(dx)}")
        return f"scroll {' '.join(parts) or '0'} at {_point(args)}"
    if action == "type":
        text = str(args.get("text") or "")
        shown = text if len(text) <= 40 else text[:39] + "…"
        return f"type “{shown}”"
    if action == "key":
        return f"key {args.get('keys')}"
    if action == "wait":
        return f"wait {args.get('ms', 1000)} ms"
    return str(action or TOOL_NAME)


def _device_name(device: Any) -> str:
    d = P.PHONE_DEVICES.get(str(device or ""))
    return d["name"] if d else str(device or "device")


def _control_request(args: Dict[str, Any]) -> Tuple[Optional[Tuple[str, Dict[str, Any]]], Optional[str]]:
    """`B1756`. A phone control as the phone route's action and fields — the
    window's own requests — or a sentence saying what is missing."""
    action = args["action"]
    if action == "press":
        button = str(args.get("button") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if button not in P.PHONE_BUTTONS:
            return None, f"`press` needs “button”: one of {', '.join(P.PHONE_BUTTONS)}."
        return ("button", {"button": button}), None
    if action == "rotate":
        return ("rotate", {}), None
    if action in ("fold", "unfold"):
        return ("posture", {"posture": "closed" if action == "fold" else "open"}), None
    if action == "open_url":
        url = str(args.get("url") or "").strip()
        if not url:
            return None, "`open_url` needs “url”, such as https://example.org."
        return ("open_url", {"url": url}), None
    device = str(args.get("device") or "").strip().lower()
    if device not in P.PHONE_DEVICES:
        return None, ("`use_device` needs “device”: one of "
                      + ", ".join(f"{k} ({v['name']})" for k, v in P.PHONE_DEVICES.items()) + ".")
    return ("install", {"device": device}), None


def _installing_line(state: Dict[str, Any]) -> str:
    inst = state.get("install") if isinstance(state.get("install"), dict) else {}
    step = inst.get("step_label") or "Installing"
    pct = inst.get("percent")
    return f"{step}{f' ({pct}%)' if isinstance(pct, int) else ''}"


def command_line(content: Any) -> str:
    """The card's command line for a `computer` call: the described action, or
    the raw arguments when they do not parse (the card must still show what
    the model sent)."""
    args, problem = parse_args(content)
    if problem:
        return str(content or "").strip()
    return describe_action(args)


def unavailable_reason(owner: Optional[str], *, delegated_credential: bool = False) -> Optional[str]:
    """Why this turn is not offered the tool, or None when it is.

    `workstation_for` is the question, asked exactly as the handler asks it.
    A run driven by a bearer API token is not offered it either: `B70` caps a
    token at the non-admin policy whoever minted it, a non-admin's
    `can_use_workstation` is off until an admin grants it, and a token cannot
    hold a grant of its own — the same reason it cannot reach `bash`.
    """
    if delegated_credential:
        return "An API token cannot drive the workstation's screen."
    from src.workstation_access import workstation_for
    from src.workstation_client import WorkstationError

    try:
        workstation_for(owner)
    except WorkstationError as e:
        return e.message
    except Exception as e:  # noqa: BLE001 — an unanswerable question is a no
        logger.warning("could not decide whether %r may use the workstation: %s", owner, e)
        return "Pantheon could not read the workstation's settings."
    return None


def _shot_line(shot: Dict[str, Any], screen: str = "desktop") -> str:
    width = shot.get("width") or P.SCREEN_WIDTH
    height = shot.get("height") or P.SCREEN_HEIGHT
    if screen == "phone" and shot.get("mode") == "mobile_view":  # `B1753`
        return (f"The phone's screen is attached: {width}×{height} pixels, and the coordinates "
                "you send are in those pixels. It is a mobile view, not Android: a "
                "phone-shaped browser (this workstation has no KVM), so web pages only; the "
                "wheel scrolls, and the phone action's Back and Home buttons work.")
    if screen == "phone":
        return (f"The phone's screen is attached: {width}×{height} pixels, and the coordinates "
                "you send are in those pixels. A click is a tap, a drag a swipe; right_click "
                "is Back and middle_click is Home.")
    return (f"The screen is attached: {width}×{height} pixels, and the coordinates you send are "
            f"in those pixels.")


def _place_marks(args: Dict[str, Any], owner: Optional[str]) -> Optional[str]:
    """`G4`. A `mark` (and a drag's `to_mark`) turned into the point it stands
    for, from the last screenshot this person's agent was shown; a sentence
    when it cannot be. A point sent beside a mark wins: the model said both,
    and the pixels are the more exact."""
    from src import screen_marks
    if args.get("mark") is None and args.get("to_mark") is None:
        return None
    if not screen_marks.ENABLED:
        return "Marks are off: use x and y read from the screenshot."
    if args["action"] not in MARK_ACTIONS:
        return f"“mark” goes with a click, move, drag, scroll or type, not {args['action']}."
    surface = PHONE_SURFACE if args.get("screen") == "phone" else SURFACE
    for key, (kx, ky) in (("mark", ("x", "y")), ("to_mark", ("to_x", "to_y"))):
        if args.get(key) is None or args.get(kx) is not None:
            continue
        mark, problem = screen_marks.resolve(owner, surface, args[key])
        if problem:
            return problem
        args[kx], args[ky] = screen_marks.center(mark)
        if key == "mark":
            args["mark_name"] = mark.get("name") or ""
    return None


async def _marked(client, account: str, shot: Dict[str, Any], owner: Optional[str],
                  screen: str = "desktop") -> Tuple[Dict[str, Any], str]:
    """`G1`–`G4`. The screenshot with its marks drawn on and the list in
    words, and the marks kept for `mark`: the desktop's accessibility tree
    first (`ROUTES["marks"]`), then what the picture shows that the tree left
    out. Any part that fails leaves the rest: no marks at all is the plain
    screenshot, as before."""
    import asyncio
    from src import screen_marks
    from src.workstation_client import WorkstationError

    png = screen_marks.picture(shot)
    if not png:
        return shot, ""
    width = shot.get("width") or P.SCREEN_WIDTH
    height = shot.get("height") or P.SCREEN_HEIGHT
    described: list = []
    windows: list = []
    surface = PHONE_SURFACE if screen == "phone" else SURFACE
    try:
        # `B1751`: the phone's marks are its own UI tree's.
        got = await (client.phone(account, "marks") if screen == "phone" else client.marks(account))
        described = screen_marks.normalise(got.get("marks") or [], width, height, "a11y")
        windows = got.get("windows") or []
    except WorkstationError as e:
        # An older daemon (`not_found`) or a screen with no tree: the picture alone.
        logger.debug("no accessibility marks for %s: %s", account, e.message)
    except Exception as e:  # noqa: BLE001 — marks are help, never the action's failure
        logger.info("accessibility marks not read for %s: %s", account, e)
    try:
        seen = await asyncio.to_thread(screen_marks.seen, png)
    except Exception as e:  # noqa: BLE001
        logger.info("screen not read for marks: %s", e)
        seen = []
    marks = screen_marks.merge(described, seen, windows)
    screen_marks.remember(owner, surface, marks)
    if not marks:
        return shot, ""
    data, mime = await asyncio.to_thread(screen_marks.draw, png, marks)
    import base64
    return dict(shot, data_b64=base64.b64encode(data).decode(), mime=mime), screen_marks.listing(marks)


async def _phone_on(client, account: str, *, observe_boot: bool = False) -> Optional[Dict[str, Any]]:
    """`B1751`. None when the phone is on and the action can go ahead; else
    what the model is told — the phone turned on and booting (so it waits and
    looks again), or why there is no phone here."""
    from src.workstation_client import WorkstationError
    try:
        state = await client.phone(account, "status")
        if state.get("state") == "off":
            state = await client.phone(account, "start")
    except WorkstationError as e:
        return e.as_result()
    if state.get("state") == "on" or (observe_boot and state.get("state") == "starting"
                                     and state.get("stream_ready") is True):
        return None
    if state.get("state") == "installing":  # `B1756`
        name = next((d.get("name") for d in state.get("devices") or []
                     if d.get("id") == state.get("device")), state.get("device"))
        return {"output": (f"The phone ({name}) is being installed in the workstation: "
                           f"{_installing_line(state)}. The first device downloads Android "
                           "(a few GB) and takes minutes. Wait (`wait` with ms, on the phone) "
                           "and look again."), "exit_code": 0}
    if state.get("state") == "starting":
        name = next((d.get("name") for d in state.get("devices") or []
                     if d.get("id") == state.get("device")), state.get("device"))
        if state.get("mode") == "mobile_view":  # `B1753`
                return {"output": (f"An explicitly selected browser preview ({name}) is opening: "
                                   "it runs web pages only, not Android apps. It is a browser shaped "
                                   "and identified as that device. Wait a few seconds (`wait` with "
                               "ms) and take a screenshot of the phone."), "exit_code": 0}
        return {"output": (f"The phone ({name}) is booting; Android takes a minute or two the "
                           "first time. Wait (`wait` with ms) and take a screenshot of the "
                           "phone again."), "exit_code": 0}
    return {"error": state.get("why") or "There is no phone on this workstation.",
            "exit_code": 1, "workstation_error": "unavailable"}


class ComputerTool:
    """One action on the person's workstation display."""

    async def _control(self, client, account: str, args: Dict[str, Any], owner: Optional[str],
                       what: str) -> Dict[str, Any]:
        """`B1756`. One of the phone's own controls, sent as the person's window
        sends it (`ROUTES["phone"]`), then the phone looked at."""
        from src.workstation_client import WorkstationError
        req, problem = _control_request(args)
        if problem:
            return {"error": problem, "exit_code": 1}
        verb, fields = req
        if verb != "install":
            started = await _phone_on(client, account)
            if started:
                return started
        try:
            state = await client.phone(account, verb, **fields)
        except WorkstationError as e:
            if e.code == "busy":
                return {"error": f"{e.message} {BUSY_ADVICE}", "exit_code": 1,
                        "workstation_error": e.code}
            return e.as_result()
        if verb == "install" and isinstance(state, dict) and state.get("state") != "on":
            waiting = await _phone_on(client, account)
            if waiting:
                waiting = dict(waiting)
                if "output" in waiting:
                    waiting["output"] = f"Did: {what}. " + waiting["output"]
                return waiting
        import asyncio
        await asyncio.sleep(0.6)
        try:
            shot = await client.phone(account, "screenshot")
        except WorkstationError:
            shot = None
        if not isinstance(shot, dict) or not shot.get("data_b64"):
            return {"output": f"Did: {what}. No screenshot came back after it — take one "
                              "before the next action.", "exit_code": 0}
        from src import screen_marks
        listed = ""
        if screen_marks.ENABLED:
            shot, listed = await _marked(client, account, shot, owner, "phone")
        output = f"Did: {what}. {_shot_line(shot, 'phone')}" + (f"\n{listed}" if listed else "")
        return {"output": output, "exit_code": 0,
                "images": [{"data": shot["data_b64"], "mimeType": shot.get("mime") or "image/png"}],
                "screenshot_caption": f"Phone after {what}"}

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        from src.workstation_access import ensure_ready
        from src.workstation_client import WorkstationError

        owner = (ctx or {}).get("owner")
        args, problem = parse_args(content)
        if problem:
            return {"error": problem, "exit_code": 1}
        action = args["action"]
        problem = _place_marks(args, owner)
        if problem:
            return {"error": problem, "exit_code": 1}
        try:
            # The admin's `sudo` in force and the person's display started
            # before the first action needs it (`P20-02`'s `ensure_ready`).
            ready = await ensure_ready(owner)
        except WorkstationError as e:
            return e.as_result()
        client, account = ready.client, ready.account

        what = describe_action(args)
        on_phone = args.get("screen") == "phone"
        if action in PHONE_CONTROLS:
            return await self._control(client, account, args, owner, what)
        if on_phone:
            if action == "wait":
                # Waiting is what a booting phone needs, so it is done here,
                # and the phone looked at after it.
                import asyncio
                ms = args.get("ms", 1000)
                ms = ms if isinstance(ms, int) and not isinstance(ms, bool) else 1000
                await asyncio.sleep(max(0, min(ms, P.MAX_WAIT_MS)) / 1000)
                action = args["action"] = SCREENSHOT
            started = await _phone_on(client, account, observe_boot=action == SCREENSHOT)
            if started:
                return started
        # `B1754`: the agent's hand, for the screen window to draw.
        from src import desktop_activity
        drawn = None if on_phone or action in (SCREENSHOT, "wait") else desktop_activity.begin(
            account, action, what[:1].upper() + what[1:], args)
        try:
            if on_phone:
                # `B1751`: the same actions on the phone's screen.
                if action == SCREENSHOT:
                    shot = await client.phone(account, "screenshot")
                else:
                    if action == "type" and args.get("mark") is not None:
                        await client.phone(account, "input", input="click", x=args["x"], y=args["y"])
                    fields = {k: args[k] for k in _INPUT_FIELDS if args.get(k) is not None}
                    if action == "type":
                        fields = {k: v for k, v in fields.items() if k not in ("x", "y")}
                    answer = await client.phone(account, "input", input=action,
                                                screenshot_after=True, **fields)
                    shot = answer.get("screenshot")
            elif action == SCREENSHOT:
                shot = await client.screenshot(account)
            else:
                if action == "type" and args.get("mark") is not None:
                    # `G4`: into the field the mark names — clicked first.
                    await client.input(account, "click", x=args["x"], y=args["y"])
                fields = {k: args[k] for k in _INPUT_FIELDS if args.get(k) is not None}
                if action == "type":
                    fields = {k: v for k, v in fields.items() if k not in ("x", "y")}
                answer = await client.input(account, action, screenshot_after=True, **fields)
                shot = answer.get("screenshot")
        except WorkstationError as e:
            desktop_activity.finish(account, drawn, False)
            if e.code == "busy":
                return {"error": f"{e.message} {BUSY_ADVICE}", "exit_code": 1,
                        "workstation_error": e.code}
            return e.as_result()
        except BaseException:
            desktop_activity.finish(account, drawn, False)
            raise

        desktop_activity.finish(account, drawn, True)
        did = "Took a screenshot." if action == SCREENSHOT else f"Did: {what}."
        if not isinstance(shot, dict) or not shot.get("data_b64"):
            # The action happened; only the picture after it is missing. Said,
            # so the model takes another screenshot rather than assuming.
            return {"output": f"{did} No screenshot came back after it — take one before the "
                              "next action.", "exit_code": 0}
        caption = (("Phone" if on_phone else "Screen") if action == SCREENSHOT
                   else f"{'Phone' if on_phone else 'Screen'} after {what}")
        if on_phone and shot.get("state") == "starting":
            caption = "Phone booting"
        from src import screen_marks
        listed = ""
        if screen_marks.ENABLED and args.get("marks") is not False and shot.get("state") != "starting":
            shot, listed = await _marked(client, account, shot, owner, args["screen"])
        else:
            screen_marks.forget(owner, PHONE_SURFACE if on_phone else SURFACE)
        output = f"{did} {_shot_line(shot, args['screen'])}"
        if listed:
            output += "\n" + listed
        return {
            "output": output,
            "exit_code": 0,
            "images": [{"data": shot["data_b64"], "mimeType": shot.get("mime") or "image/png"}],
            "screenshot_caption": caption,
        }


__all__ = ["ACTIONS", "BUSY_ADVICE", "PHONE_CONTROLS", "ComputerTool", "MARK_ACTIONS", "SCREENSHOT", "TOOL_NAME", "command_line",
           "describe_action", "parse_args", "unavailable_reason"]
