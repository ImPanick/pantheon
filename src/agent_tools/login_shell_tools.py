# SPDX-License-Identifier: AGPL-3.0-or-later
"""`shell_with_login` — one shell command run with logins from the person's
vault in its environment. `P27-07`.

The owner (2026-10-24): *"store the login details for the agent to login and
automate (using shell or even the browser)."* `agent_browser login` is the
browser half (`P27-06`); this is the shell half.

**By reference.** The model names the logins; it never sees them. For each,
the command's environment carries `LOGIN_<NAME>_USER`, `_PASSWORD`, `_OTP` (a
one-time code made now, when the login has a secret for one) and `_URL` (its
first address) — and, when only one login is named, the same without the name:
`LOGIN_USER`, `LOGIN_PASSWORD`, … So the model writes
`curl -u "$LOGIN_USER:$LOGIN_PASSWORD" "$LOGIN_URL/api/health"` and the values
exist only in that one process's environment: not in the command line the
approval card and the transcript show, not in a shell history (the shell is not
interactive), not on the disk. What the command prints is scrubbed of every
value before anyone sees it (`vault.scrub`).

**Where.** Exactly where `git` runs (`git_tools._Place`, the same question):
the person's workstation when their tools run there, otherwise this machine
for an admin — which is why it is blocked for everyone else
(`tool_security.NON_ADMIN_BLOCKED_TOOLS`) and lifted with `bash` for a person
with a workstation (`workstation_tools.LIFTED_TOOLS`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

TOOL_NAME = "shell_with_login"
LOGINS_MAX = 4
COMMAND_MAX = 8000
TIMEOUT_S = 300.0
OUTPUT_MAX = 20_000


def parse_args(content: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    if isinstance(content, dict):
        raw: Any = dict(content)
    else:
        text = str(content or "").strip()
        if not text.startswith("{"):
            return {}, ('`shell_with_login` arguments are a JSON object: {"logins": ["Grafana (agent)"], '
                        '"command": "curl -u \\"$LOGIN_USER:$LOGIN_PASSWORD\\" \\"$LOGIN_URL/api/health\\""}.')
        try:
            raw = json.loads(text)
        except ValueError:
            return {}, "`shell_with_login` arguments are a JSON object."
    if not isinstance(raw, dict):
        return {}, "`shell_with_login` arguments are a JSON object."
    logins = raw.get("logins", raw.get("login"))
    if isinstance(logins, str):
        logins = [logins]
    if not isinstance(logins, list) or not logins or not all(isinstance(x, str) and x.strip() for x in logins):
        return {}, "“logins” is the names of one or more logins in the person's vault."
    if len(logins) > LOGINS_MAX:
        return {}, f"At most {LOGINS_MAX} logins in one command."
    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        return {}, "“command” is the shell command to run."
    if len(command) > COMMAND_MAX:
        return {}, f"“command” is at most {COMMAND_MAX} characters."
    cwd = raw.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        return {}, "“cwd” is a folder, relative to the workspace."
    return {"logins": [x.strip() for x in logins], "command": command, "cwd": cwd}, None


def env_name(label: str) -> str:
    """`Grafana (agent)` → `GRAFANA_AGENT`."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper()
    return slug or "ITEM"


def environment(items: List[Dict[str, Any]]) -> Tuple[Dict[str, str], List[str]]:
    """The command's environment for these vault items, and the variable
    names it was given — names only, for the answer."""
    env: Dict[str, str] = {}
    for item in items:
        fields = {"USER": item.get("username") or "", "PASSWORD": item.get("secret") or "",
                  "OTP": item.get("otp") or "", "URL": (item.get("origins") or [""])[0]}
        prefixes = [f"LOGIN_{env_name(item['label'])}_"] + (["LOGIN_"] if len(items) == 1 else [])
        for prefix in prefixes:
            for k, v in fields.items():
                if v:
                    env[prefix + k] = v
    return env, sorted(env)


def describe(args: Dict[str, Any]) -> str:
    first = args["command"].strip().splitlines()[0]
    return f"[{', '.join(args['logins'])}] {first[:160]}"


def command_line(content: Any) -> str:
    args, problem = parse_args(content)
    return str(content or "").strip()[:200] if problem else describe(args)


async def run_with_login(content: Any, *, owner: Optional[str], station_workspace: Optional[str] = None,
                         session_id: Optional[str] = None, agent_id: Optional[str] = None) -> Dict[str, Any]:
    from core.database import SessionLocal
    from src import vault as V
    from src.agent_tools.git_tools import _GitProblem, _Place, _where

    args, problem = parse_args(content)
    if problem:
        return {"error": problem, "exit_code": 1}
    place = _Place(owner, station_workspace)
    refused = await place.open()
    if refused is not None:
        return refused
    try:
        cwd = place.resolve(args.get("cwd"))
    except _GitProblem:
        return {"error": f"{args.get('cwd')} is outside your home, so nothing runs there.", "exit_code": 1,
                **_where(place)}
    db = SessionLocal()
    items = []
    try:
        for ref in args["logins"]:
            items.append(await V.resolve(db, owner, ref, by=TOOL_NAME, session=session_id, agent=agent_id))
    except V.VaultRefused as r:
        return {"error": r.sentence, "exit_code": 1, **_where(place)}
    finally:
        db.close()
    env, names = environment(items)
    values = [v for v in env.values() if v and not v.startswith(("http://", "https://"))]
    r = await place.run(args["command"], cwd, env, TIMEOUT_S)
    out = V.scrub(r.get("stdout") or "", values)
    err = V.scrub(r.get("stderr") or "", values)
    text = (out + (("\n" + err) if err.strip() else "")).strip()
    if len(text) > OUTPUT_MAX:
        text = text[:OUTPUT_MAX // 2] + "\n… (cut) …\n" + text[-OUTPUT_MAX // 2:]
    given = f"(The command had {', '.join('$' + n for n in names)}.)"
    if r.get("timed_out"):
        return {"error": f"The command did not finish within {int(TIMEOUT_S)} seconds. {given}",
                "output": text, "exit_code": 124, **_where(place)}
    code = r.get("exit_code")
    result = {"output": f"{text or '(no output)'}\n{given}", "exit_code": code if code is not None else 1,
              **_where(place)}
    if code not in (0, None):
        result["error"] = f"The command exited with {code}."
    return result


class LoginShellTool:
    """The registry's handler: the dispatcher calls `run_with_login` by name
    with the turn's owner and workspace; this answers a call that reaches it
    another way, with the owner in `ctx`."""

    async def execute(self, content: str, ctx: Optional[dict] = None) -> Dict[str, Any]:
        return await run_with_login(content, owner=(ctx or {}).get("owner"),
                                    session_id=(ctx or {}).get("session_id"),
                                    agent_id=(ctx or {}).get("agent_id"))
