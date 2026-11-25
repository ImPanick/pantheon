# SPDX-License-Identifier: AGPL-3.0-or-later
"""Answering a request from an entry: pull its parameters, run its code.

The small (target) model does two jobs here and nothing else: it reads the
request's words for the entry's parameters, and it answers the code's own
`lm` and `extract` calls. Tools are reached only through `ReadOnlyTools`,
which refuses anything that is not a read, anything the entry was not built
with, and anything the run's gate would stop and ask about. Every refusal is a
miss: the turn goes to the model as it would have without the cache.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from src.reasoning_cache import roles
from src.reasoning_cache.sandbox import RunResult, run_entry

#: The only effects a cached entry's tool call may have.
READ_EFFECT_NAMES = frozenset({"read_public", "read_workspace", "read_private",
                               "brokered_network_read"})


class Miss(RuntimeError):
    """The entry cannot answer this request; the model answers instead."""


def first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """The first JSON object in a model's answer, fenced or not."""
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


EXTRACT_SYSTEM = (
    "You pull values out of a request. Answer with one JSON object and nothing "
    "else. Use exactly the keys you are given. Copy each value as the request "
    "states it, as a string. If the request does not state a value, use null.")


async def extract_params(owner: Optional[str], request: str,
                         parameters: List[Dict[str, Any]], *,
                         workload: str = "foreground") -> Dict[str, Any]:
    """The entry's parameters, read from the request's words by the target
    model. A parameter the request does not state is a miss."""
    if not parameters:
        return {}
    lines = [f'- "{p.get("name")}": {p.get("description") or ""}' for p in parameters]
    prompt = ("Keys:\n" + "\n".join(lines) + "\n\nRequest:\n" + request.strip()
              + "\n\nJSON:")
    answer = await roles.call("target", owner,
                              [{"role": "system", "content": EXTRACT_SYSTEM},
                               {"role": "user", "content": prompt}],
                              max_tokens=600, workload=workload)
    found = first_json_object(answer) or {}
    params: Dict[str, Any] = {}
    for p in parameters:
        name = str(p.get("name") or "")
        value = found.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise Miss(f"the request does not say {name!r}")
        params[name] = value if isinstance(value, (int, float, bool)) else str(value)
    return params


class ReadOnlyTools:
    """The tool primitive for one run of one entry."""

    def __init__(self, owner: Optional[str], *, allowed: Set[str],
                 session_id: Optional[str] = None,
                 disabled_tools: Optional[Set[str]] = None,
                 untrusted_seen: bool = False):
        self.owner = owner
        self.allowed = set(allowed)
        self.session_id = session_id
        self.disabled_tools = set(disabled_tools or ())
        self.untrusted_seen = bool(untrusted_seen)
        self._context = None

    def _security_context(self):
        if self._context is None:
            from src.agent_loop import apply_role_floor, resolve_trust_rung
            from src.tool_capabilities import ToolRunSecurityContext
            self._context = ToolRunSecurityContext(
                external_untrusted_context_seen=self.untrusted_seen,
                rung=apply_role_floor(resolve_trust_rung(), self.owner))
        return self._context

    async def __call__(self, name: str, content: str) -> str:
        from src.tool_capabilities import ResultIntegrity, capabilities_for_action
        if name not in self.allowed:
            raise PermissionError(f"{name} is not a tool this entry was built with")
        if name in self.disabled_tools:
            raise PermissionError(f"{name} is switched off")
        caps = capabilities_for_action(name, content)
        effects = {getattr(e, "value", str(e)) for e in caps.effects}
        if not caps.known or not effects or not effects <= READ_EFFECT_NAMES:
            raise PermissionError(f"{name} is not a read")
        context = self._security_context()
        if context.asks_for(name, content):
            raise PermissionError(f"{name} would need your approval")
        from src.agent_tools import ToolBlock
        from src.tool_execution import execute_tool_block
        desc, result = await execute_tool_block(
            ToolBlock(name, content), session_id=self.session_id,
            disabled_tools=self.disabled_tools or None, owner=self.owner,
            security_context=context)
        result = result if isinstance(result, dict) else {}
        if result.get("blocked") or result.get("error") or result.get("exit_code") not in (None, 0):
            raise RuntimeError(f"{name} did not run: {result.get('error') or desc}"[:300])
        if caps.result_integrity is ResultIntegrity.EXTERNAL_UNTRUSTED:
            # What came back may be anyone's words: every later call in this
            # run is held to the gate an agent run would be held to.
            context.external_untrusted_context_seen = True
        output = result.get("output")
        return str(output if output is not None else desc or "")


async def answer(entry: Dict[str, Any], request: str, owner: Optional[str], *,
                 workload: str = "foreground", session_id: Optional[str] = None,
                 disabled_tools: Optional[Set[str]] = None,
                 untrusted_seen: bool = False) -> RunResult:
    """Run one entry for one request. Raises `Miss`, `CodeRefused` or
    `EntryFailed`; the gate reads every one of them as a miss."""
    params = await extract_params(owner, request, entry.get("parameters") or [],
                                  workload=workload)
    tools = ReadOnlyTools(owner, allowed=set(entry.get("tools") or ()),
                          session_id=session_id, disabled_tools=disabled_tools,
                          untrusted_seen=untrusted_seen)

    async def on_call(name: str, args: List[str]) -> Any:
        if name == "lm":
            return await roles.call("target", owner,
                                    [{"role": "user", "content": args[0]}],
                                    max_tokens=900, workload=workload)
        if name == "extract":
            text, what = (args + ["", ""])[:2]
            return await roles.call(
                "target", owner,
                [{"role": "system", "content": "Answer with only the value asked for, nothing else."},
                 {"role": "user", "content": f"From the text below, give only {what}.\n\nText:\n{text}"}],
                max_tokens=300, workload=workload)
        if name == "invoke_tool":
            tool, content = (args + ["", ""])[:2]
            return await tools(tool, content)
        raise PermissionError(f"{name} is not a primitive")

    return await run_entry(entry["code"], entry.get("root") or "solve", params, on_call)
