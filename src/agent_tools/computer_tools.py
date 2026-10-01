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
ACTIONS: Tuple[str, ...] = (SCREENSHOT,) + tuple(P.INPUT_ACTIONS)

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
_INT_FIELDS = ("x", "y", "to_x", "to_y", "dx", "dy", "ms")
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
    return args, None


def _point(args: Dict[str, Any], kx: str = "x", ky: str = "y") -> str:
    return f"({args.get(kx)}, {args.get(ky)})"


def describe_action(args: Dict[str, Any]) -> str:
    """One line a person reads: *click at (640, 400)*, *type “hello”*. The tool
    card's command line and the screenshot's summary are both this, so the card
    says what was done without the raw arguments (they stay one click away)."""
    action = args.get("action")
    if action == SCREENSHOT:
        return "screenshot"
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


def _shot_line(shot: Dict[str, Any]) -> str:
    width = shot.get("width") or P.SCREEN_WIDTH
    height = shot.get("height") or P.SCREEN_HEIGHT
    return (f"The screen is attached: {width}×{height} pixels, and the coordinates you send are "
            f"in those pixels.")


class ComputerTool:
    """One action on the person's workstation display."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        from src.workstation_access import workstation_for
        from src.workstation_client import WorkstationError

        owner = (ctx or {}).get("owner")
        args, problem = parse_args(content)
        if problem:
            return {"error": problem, "exit_code": 1}
        action = args["action"]
        try:
            client, account = workstation_for(owner)
        except WorkstationError as e:
            return e.as_result()

        what = describe_action(args)
        try:
            if action == SCREENSHOT:
                shot = await client.screenshot(account)
            else:
                fields = {k: args[k] for k in _INPUT_FIELDS if args.get(k) is not None}
                answer = await client.input(account, action, screenshot_after=True, **fields)
                shot = answer.get("screenshot")
        except WorkstationError as e:
            if e.code == "busy":
                return {"error": f"{e.message} {BUSY_ADVICE}", "exit_code": 1,
                        "workstation_error": e.code}
            return e.as_result()

        did = "Took a screenshot." if action == SCREENSHOT else f"Did: {what}."
        if not isinstance(shot, dict) or not shot.get("data_b64"):
            # The action happened; only the picture after it is missing. Said,
            # so the model takes another screenshot rather than assuming.
            return {"output": f"{did} No screenshot came back after it — take one before the "
                              "next action.", "exit_code": 0}
        caption = "Screen" if action == SCREENSHOT else f"Screen after {what}"
        return {
            "output": f"{did} {_shot_line(shot)}",
            "exit_code": 0,
            "images": [{"data": shot["data_b64"], "mimeType": shot.get("mime") or "image/png"}],
            "screenshot_caption": caption,
        }


__all__ = ["ACTIONS", "BUSY_ADVICE", "ComputerTool", "SCREENSHOT", "TOOL_NAME", "command_line",
           "describe_action", "parse_args", "unavailable_reason"]
