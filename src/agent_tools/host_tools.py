# SPDX-License-Identifier: AGPL-3.0-or-later
"""`host_shell` — a command on the machine, not in the container.

`P17-11`, from `D-2026-09-11-01`. The owner's ask: *"I want to be able to have
something for agents inside of Pantheon to reach out and touch beyond docker's
sandbox."*

**THIS TOOL GAINS NO CAPABILITY. IT HOLDS A PHONE NUMBER.**

Nothing here escapes the container, because nothing can: that is what a container
is, and the four ways to break it — the Docker socket, `--privileged`, host SSH
credentials, a host process — are three bad answers and one good one. This is the
fourth. The command is sent to a small agent the operator started on the host,
which applies its own compiled-in denylist that Pantheon cannot read past, edit,
or switch off.

So a compromised Pantheon gains **the ability to ask**. It does not gain the
ability to widen what may be asked, and that difference is the whole design.

**THREE CHECKS, IN THIS ORDER, AND THE ORDER MATTERS.**

  1. The operator's own lists, here (`src/host_exec_policy.py`). Editable in
     Settings. Narrows what Pantheon will even send. Not a boundary, and the UI
     says so.
  2. The trust gate, via the ordinary approval machinery — `host_shell` is
     classified `EXECUTE_CODE` + `DESTRUCTIVE`, so the approval card names both.
  3. The agent's own list, on the host. The boundary.

**ONE SWITCH, NOT TWO.** The chat's existing *enable shell* toggle sends
`allow_bash`, and that governs this tool as well as `bash`. `Law 14`: a second
control for "may the agent run commands" is a second thing to forget to turn off.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _parse(content: str) -> Dict[str, Any]:
    """A JSON object, or the whole block as the command.

    Both spellings, because the model reaches for both and rejecting one is a
    silent failure the person sees as "it ignored me". The bare form is the
    common case and stays one line.
    """
    text = str(content or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            # Not JSON after all — a command that happens to start with a brace.
            pass
    return {"command": text}


class HostShellTool:
    """Run a command on the host, through the agent."""

    async def execute(self, content: str, **kwargs) -> Dict[str, Any]:
        from src import host_exec_policy, netagent_client

        args = _parse(content)
        command = str(args.get("command") or "").strip()
        if not command:
            return {"error": "host_shell needs a command", "exit_code": 1}

        if not netagent_client.configured():
            return {
                "error": "no host agent is configured, so there is nothing outside "
                         "the container to run this on. Settings → Networks → "
                         "Network agent, or run netagent/install.py on the host.",
                "exit_code": 1,
            }

        decision = host_exec_policy.check_from_settings(command)
        if not decision.allowed:
            # Refused before the request is made. The operator said not to send
            # this, so it is not sent — reaching the host to be told no would
            # leak the attempt into somebody else's logs for no benefit.
            return {"error": decision.reason, "refused_by": decision.source,
                    "exit_code": 1}

        result = await netagent_client.exec_on_host(
            command,
            elevated=bool(args.get("elevated")),
            timeout=args.get("timeout"),
            cwd=(str(args["cwd"]) if args.get("cwd") else None),
        )
        if result.get("error"):
            return {"error": result["error"],
                    "refused_by": result.get("refused_by") or result.get("rule"),
                    "exit_code": 1}

        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        exit_code = result.get("exit_code")
        # Shaped like `bash`'s result so the trace renderer and the agent loop
        # need no special case — `Law 14` at the boundary of a new tool.
        out = {"output": stdout, "exit_code": exit_code,
               "host": True, "elevated": bool(result.get("elevated"))}
        if stderr:
            out["stderr"] = stderr
        if result.get("timed_out"):
            out["timed_out"] = True
        return out
