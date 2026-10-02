# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a workflow meets the outside — `P22-13` … `P22-16`, `P22-18` (contract C-E).

One module for every step that reaches past Pantheon's own process: an HTTP
request through a registered Integration, an MCP tool, a skill followed by a
model, the AI step's answer shape, and Code in the person's workstation — plus
the two builders the Workbench asks before any of them runs (the palette, and
the fields a step can pick from).

**THE ADVERSARY (`Law 17`, `D-2026-10-01-05` §4).** Whoever writes an inbound
mail or webhook body — and, through a model's output, whoever steered it.
Their bytes may reach a step's `value` slots and nothing else. Every executor
here dispatches the call `workflow_slots.render_call` built (`RenderedCall`,
contract C-R) **verbatim**: nothing here reads a value, splices one, or expands
a reference in one, so a value cannot become a path, a recipient or a command
on the way through. The HTTP and MCP steps go through the real dispatcher,
`tool_execution.execute_tool_block`, with a `ToolRunSecurityContext` the walker
hands in — so the disabled lists, `require_admin`'s tool twin
(`is_public_blocked_tool`), the trust rung, the SSRF validators with their
pinned transport and the outbound limiter all apply exactly as they do to the
agent (`FORBIDDEN.md` Part 2: none of them lift for a workflow).

**WHAT IS NOT HERE.** Whether a slot may be filled (`workflow_slots`, wf-rules),
when a step runs or parks (the walker, wf-walker), and how a card is minted
(`tool_capabilities.authored_call_context`, wf-walker). An executor is handed a
decision already made and carries it out.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)


# ── The outcome every executor answers (C-E) ─────────────────────────────────

STEP_SUCCESS = "success"
STEP_ERROR = "error"
STEP_OUTCOMES = (STEP_SUCCESS, STEP_ERROR)


class StepOutcome(NamedTuple):
    """How one effect step ended. `status` is `success` or `error` — the port
    it leaves by (`Law 10`: an enum, not a boolean). `text` is the human line
    (the output, or the sentence saying why not); `data` the structured value
    the next step can pick fields from, or `None`; `result` the dispatcher's
    own dict, kept for the step log."""
    status: str
    text: str
    data: Any
    result: Optional[dict]


class StepRefused(Exception):
    """A step that cannot start, with the sentence that says why — raised by
    `skill_context` for a skill that is no longer there."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


def _error(text: str, result: Optional[dict] = None) -> StepOutcome:
    return StepOutcome(STEP_ERROR, str(text), None, result)


def _failed(result: Any) -> bool:
    return (not isinstance(result, dict)
            or bool(result.get("error"))
            or result.get("exit_code") not in (0, None))


def _outcome(result: Any, data: Any = None) -> StepOutcome:
    """A dispatcher result as a `StepOutcome`. A refusal (`blocked`) and a
    failure are both the `error` port; the dict keeps which it was."""
    if not isinstance(result, dict):
        return _error("The step answered nothing it could read.")
    if _failed(result):
        text = result.get("error") or result.get("stderr") or result.get("output") or ""
        return StepOutcome(STEP_ERROR, str(text) or "It failed and did not say why.", None, result)
    text = result.get("output")
    if text is None:
        text = result.get("stdout")
    return StepOutcome(STEP_SUCCESS, str(text or ""), data, result)


# ── Which call this is (C-R's `RenderedCall`) ────────────────────────────────

def _require_rendered(call: Any, kind: str) -> None:
    """`call` is a `workflow_slots.RenderedCall` of `kind`, or this raises.

    The executors take nothing else: a call some other code assembled has had
    no slot checked, so it is a programming error, not a step that fails
    (the same rule `tool_capabilities.authored_call_context` keeps).
    """
    from src.workflow_slots import RenderedCall
    if not isinstance(call, RenderedCall):
        raise TypeError(f"a workflow {kind} step runs a RenderedCall, not {type(call).__name__}")
    if call.kind != kind:
        raise TypeError(f"a workflow {kind} step was handed a {call.kind!r} call")


def _missing_sentence(call: Any) -> Optional[str]:
    """A reference that found nothing is not sent as an empty value: the author
    picked a field and it was not there, so the call is not the one they meant."""
    missing = [str(m) for m in (getattr(call, "missing", None) or ()) if m]
    if not missing:
        return None
    shown = ", ".join(missing[:3]) + (" …" if len(missing) > 3 else "")
    return f"Nothing was there for {shown}, so it was not sent."


def global_disabled_tools() -> set:
    """The tools switched off for everyone: the admin's `disabled_tools` list
    and the tools of a switched-off feature — what the agent loop denies a run
    before it starts (`tool_security.feature_disabled_tools`). Read per call."""
    out: set = set()
    try:
        from src.settings import get_setting
        listed = get_setting("disabled_tools", [])
        if isinstance(listed, list):
            out.update(str(t) for t in listed if t)
    except Exception as exc:  # noqa: BLE001
        # Fails closed for this step, where the scheduler's copy fails open:
        # a step that cannot learn what is switched off does not run.
        logger.warning("Could not read the global disabled-tool list: %s", exc)
        raise
    from src.tool_security import feature_disabled_tools
    out.update(feature_disabled_tools())
    return out


def _mcp_disabled_names() -> set:
    """Every MCP tool a server has switched off, by its qualified name — the
    spelling `execute_tool_block` matches (`FORBIDDEN.md` Part 1)."""
    from src.mcp_manager import load_disabled_map, qualify_mcp_tool_name
    out = set()
    for server_id, names in (load_disabled_map() or {}).items():
        out.update(qualify_mcp_tool_name(server_id, name) for name in names)
    return out


_UNREADABLE_DISABLED = ("Could not read which tools are switched off, so this step did not "
                        "run. Check the server's settings file.")


async def _dispatch(tool: str, content: str, *, owner, security_context, exact_approval,
                    disabled_tools: set) -> Tuple[str, dict]:
    from src.agent_tools import ToolBlock
    from src.tool_execution import execute_tool_block
    return await execute_tool_block(
        ToolBlock(tool, content),
        session_id=None,
        disabled_tools=disabled_tools,
        owner=owner,
        security_context=security_context,
        exact_approval=exact_approval,
    )


# ── P22-13 · HTTP through an Integration ─────────────────────────────────────

async def run_http_step(call, *, owner, security_context, exact_approval=None) -> StepOutcome:
    """One `api_call` to a registered Integration, through the real dispatcher.

    `call.content` is dispatched exactly as rendered: the Integration, method,
    path and headers are the author's (`never` slots), and the values in
    `query`/`body` are JSON values `render_call` placed with `json.dumps` — so
    the path the server receives is the path the author wrote. It must ask for
    `"structured": true`, which `render_call` writes for an `http` step: the
    step's `data` is the parsed JSON body (`execute_api_call`'s `body_json`).
    A call without it is refused here rather than run without data, because the
    next step's picker would then show fields that never arrive (`Law 13`).

    `exact_approval` (added to C-E, defaulted): the walker's replay of a sealed
    call after an Allow at a strict rung — the same argument the dispatcher takes.
    """
    _require_rendered(call, "http")
    if call.tool != "api_call":
        raise TypeError(f"an http step calls api_call, not {call.tool!r}")
    missing = _missing_sentence(call)
    if missing:
        return _error(missing)
    try:
        args = json.loads(call.content)
    except (TypeError, ValueError):
        args = None
    if not isinstance(args, dict) or args.get("structured") is not True:
        return _error("This step's request was not built to hand its answer on "
                      "(it does not ask for a structured reply), so it was not sent.")
    try:
        disabled = global_disabled_tools()
    except Exception:  # noqa: BLE001 — closed: see `global_disabled_tools`
        return _error(_UNREADABLE_DISABLED)
    _desc, result = await _dispatch(
        "api_call", call.content, owner=owner, security_context=security_context,
        exact_approval=exact_approval, disabled_tools=disabled)
    return _outcome(result, data=(result or {}).get("body_json") if isinstance(result, dict) else None)


# ── P22-14 · An MCP tool is a step ───────────────────────────────────────────

def _json_or_none(text: Any) -> Any:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


async def run_mcp_step(call, *, owner, security_context, exact_approval=None) -> StepOutcome:
    """One `mcp__{server}__{tool}` call through the real dispatcher.

    The tool and every `never` argument are the author's; the dispatcher adds
    the server's own refusals (a switched-off tool, a non-admin, a rung that
    asks) and the email server's own (`agent_email_confirm`: a send is staged
    as a draft — `FORBIDDEN.md` Part 2 holds by construction). The step's
    `data` is the tool's text when it is a JSON object or list.
    """
    _require_rendered(call, "mcp")
    from src.mcp_manager import split_mcp_tool_name
    if not isinstance(call.tool, str) or split_mcp_tool_name(call.tool) is None:
        raise TypeError(f"an mcp step calls an mcp__server__tool name, not {call.tool!r}")
    missing = _missing_sentence(call)
    if missing:
        return _error(missing)
    try:
        disabled = global_disabled_tools() | _mcp_disabled_names()
    except Exception:  # noqa: BLE001 — closed: see `global_disabled_tools`
        return _error(_UNREADABLE_DISABLED)
    _desc, result = await _dispatch(
        call.tool, call.content, owner=owner, security_context=security_context,
        exact_approval=exact_approval, disabled_tools=disabled)
    data = _json_or_none(result.get("stdout")) if isinstance(result, dict) else None
    return _outcome(result, data=data)


# ── P22-18 · Code in your workstation ────────────────────────────────────────

# The tail of stderr a failed step keeps in its sentence: enough for the line
# that says what went wrong, not a traceback's whole stack in a notification.
CODE_STDERR_TAIL_CHARS = 1200


def _code_timeout(node: dict, timeout) -> float:
    from workstation import protocol as P
    raw = timeout if timeout is not None else (node.get("config") or {}).get("timeout_seconds")
    try:
        value = float(raw) if raw is not None else P.DEFAULT_EXEC_TIMEOUT_S
    except (TypeError, ValueError):
        value = P.DEFAULT_EXEC_TIMEOUT_S
    return max(1.0, min(value, P.MAX_EXEC_TIMEOUT_S))


async def run_code_step(node, input_obj, *, owner, timeout) -> StepOutcome:
    """The step's source, run as the person's own workstation account.

    `D-2026-10-01-05` §3 and § 0.5 of the design: through the protocol's `exec`
    (`workstation_for` → `sync_config` → `client.exec`), not `run_in_workstation`,
    whose `python` handler takes its content as the script and has no stdin.
    The source is the author's and is sent byte for byte as the command; the
    input arrives as JSON on stdin and is never spliced into the source. Stdout
    that parses as JSON becomes `data`; anything else is text. A non-zero exit
    leaves by `error` with the tail of stderr.
    """
    from workstation import protocol as P
    from src.workstation_client import WorkstationError
    from src.workstation_access import sync_config, workstation_for

    config = (node or {}).get("config") or {}
    language = config.get("language")
    source = config.get("source")
    if language not in P.SHELLS:
        return _error(f"Code runs as {' or '.join(P.SHELLS)}; this step says {language!r}.")
    if not isinstance(source, str) or not source.strip():
        return _error("This step has no code to run.")
    try:
        stdin = json.dumps(input_obj, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return _error(f"What this step was handed could not be written as JSON: {exc}")
    seconds = _code_timeout(node or {}, timeout)
    try:
        client, account = workstation_for(owner)
        # `B987`: the admin's `sudo` and network mode, pushed to a daemon that
        # may have restarted and forgotten them, before the command they govern.
        await sync_config(client)
        res = await client.exec(account, source, shell=language, stdin=stdin, timeout_s=seconds)
    except WorkstationError as exc:
        return _error(exc.message, exc.as_result())
    if not isinstance(res, dict):
        return _error("The workstation answered nothing it could read.")
    stdout = str(res.get("stdout") or "")
    stderr = str(res.get("stderr") or "")
    if res.get("timed_out"):
        return _error(f"It ran longer than {seconds:g} seconds and was stopped.", res)
    code = res.get("exit_code")
    if code != 0:
        tail = stderr.strip()[-CODE_STDERR_TAIL_CHARS:]
        return _error(f"It stopped with exit code {code}" + (f": {tail}" if tail else "."), res)
    data = None
    text = stdout.strip()
    if text and not res.get("truncated"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return StepOutcome(STEP_SUCCESS, stdout, data, res)


# ── P22-15 · A skill is a step ───────────────────────────────────────────────

def _saved_at(sm, name: str, owner) -> Optional[str]:
    try:
        path = sm._find_skill_path(name, owner)
        if not path:
            return None
        when = datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:  # noqa: BLE001 — the time is a courtesy, never a refusal
        return None
    return f"{when.day} {when:%b %H:%M}"


def skill_context(owner, name) -> Tuple[List[dict], str]:
    """The skill's text as untrusted context, and the run log's line.

    Read at run time by name (`D-2026-09-30-01`: referenced, never copied), and
    wrapped as the skill test wraps it (`routes/skills_routes._skill_test_messages`):
    an untrusted-context message with the gate armed, so a skill that says
    "email everyone" asks before it does — P8-18's sentence, which the panel shows.
    Raises `StepRefused` when the skill is not there any more.
    """
    from services.memory.skills import SkillsManager
    from src.constants import DATA_DIR
    from src.prompt_security import untrusted_context_message

    label = str(name or "").strip()
    if not label:
        raise StepRefused("This step does not name a skill. Pick one from the list.")
    sm = SkillsManager(DATA_DIR)
    md = sm.read_skill_md(label, owner)
    if md is None:
        raise StepRefused(f"There is no skill named “{label}” any more. Pick another, "
                          "or put it back in Skills.")
    messages = [untrusted_context_message(f"the skill “{label}”", md)]
    saved = _saved_at(sm, label, owner)
    line = f"Followed the skill “{label}”" + (f" (saved {saved})." if saved else ".")
    return messages, line


# ── P22-16 · The AI step's answer shape ──────────────────────────────────────

# The four words an answer field's type is stored as (`D-2026-10-01-05` §2: a
# person picks one from a list; no schema language is typed).
ANSWER_TYPE_TEXT = "text"
ANSWER_TYPE_NUMBER = "number"
ANSWER_TYPE_YES_NO = "yes/no"
ANSWER_TYPE_LIST = "list"
ANSWER_FIELD_TYPES = (ANSWER_TYPE_TEXT, ANSWER_TYPE_NUMBER, ANSWER_TYPE_YES_NO, ANSWER_TYPE_LIST)
ANSWER_FIELDS_MAX = 20

_TYPE_PROMISE = {
    ANSWER_TYPE_TEXT: "text",
    ANSWER_TYPE_NUMBER: "a number",
    ANSWER_TYPE_YES_NO: "true or false",
    ANSWER_TYPE_LIST: "a list",
}

_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n(.*?)```", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _fields(fields) -> List[dict]:
    out = []
    for f in fields or ():
        if isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"].strip():
            out.append(f)
    return out[:ANSWER_FIELDS_MAX]


def answer_instruction(fields) -> str:
    """What the AI step's user turn ends with: answer as one JSON object with
    exactly these fields, each with the type a person picked."""
    lines = ["When you have finished, end your reply with one JSON object, in a ```json "
             "block, with exactly these fields and nothing else:"]
    for f in _fields(fields):
        kind = f.get("type") if f.get("type") in ANSWER_FIELD_TYPES else ANSWER_TYPE_TEXT
        about = str(f.get("description") or "").strip()
        lines.append(f'- "{f["name"].strip()}" ({_TYPE_PROMISE[kind]})' + (f": {about}" if about else ""))
    return "\n".join(lines)


def _first_object(text: str) -> Optional[dict]:
    decoder = json.JSONDecoder()
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _coerce(value: Any, kind: str) -> Tuple[bool, Any]:
    if kind == ANSWER_TYPE_NUMBER:
        if isinstance(value, bool):
            return False, None
        if isinstance(value, (int, float)):
            return True, value
        if isinstance(value, str):
            try:
                number = float(value.strip().replace(",", ""))
            except ValueError:
                return False, None
            return True, int(number) if number.is_integer() else number
        return False, None
    if kind == ANSWER_TYPE_YES_NO:
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str):
            # The one vocabulary a field's words are read with (`B97`); a
            # word outside it is not an answer, never a guessed False.
            from src.env_flags import request_truthy
            said = request_truthy(value)
            return (said is not None), said
        return False, None
    if kind == ANSWER_TYPE_LIST:
        return (True, value) if isinstance(value, list) else (False, None)
    # text
    if isinstance(value, str):
        return True, value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True, str(value)
    return False, None


def parse_answer(text, fields) -> Tuple[Optional[dict], Optional[str]]:
    """`(data, None)` when the reply ends in the shape asked, else `(None, problem)`.

    Code fences and a reasoning model's `<think>` block are looked through; the
    first JSON object found is the answer; every asked field must be in it with
    its type, and fields nobody asked for are dropped — so `data` is exactly
    what the next step's picker promised. Lenient where a model is: `"42"` is
    a number, `"yes"` is true.
    """
    wanted = _fields(fields)
    raw = _THINK_RE.sub("", str(text or ""))
    candidates = [m.group(1) for m in _FENCE_RE.finditer(raw)] + [raw]
    found = None
    for chunk in candidates:
        found = _first_object(chunk)
        if found is not None:
            break
    if found is None:
        return None, "The answer did not end in the JSON object this step asks for."
    data: Dict[str, Any] = {}
    for f in wanted:
        name = f["name"].strip()
        kind = f.get("type") if f.get("type") in ANSWER_FIELD_TYPES else ANSWER_TYPE_TEXT
        if name not in found:
            return None, f"The answer has no “{name}”."
        ok, value = _coerce(found[name], kind)
        if not ok:
            return None, f"The answer's “{name}” is not {_TYPE_PROMISE[kind]}."
        data[name] = value
    return data, None


# ── P22-16 · Which tools an AI step may be given ─────────────────────────────

def _words(name: str) -> str:
    return name.replace("_", " ").strip()


def ai_tool_choices(owner) -> list:
    """The tools a person may hand an AI step: what their agent can reach.

    Built-ins (`tool_index.BUILTIN_TOOL_DESCRIPTIONS`, the list a crew member's
    tools are chosen from) minus the non-admin blocklist (less the tools their
    workstation lifts, as the loop advertises them) and minus the tools
    switched off for everyone; plus every switched-on MCP tool, for a person
    who may call MCP tools at all (`is_public_blocked_tool`: admins and a
    single-user install). `[{name, label, kind}]`, `kind` `builtin` or `mcp`.
    """
    from src.tool_index import BUILTIN_TOOL_DESCRIPTIONS
    from src.tool_security import blocked_tools_for_owner

    blocked = set(blocked_tools_for_owner(owner))
    if blocked:
        try:
            from src.agent_tools.workstation_tools import lifted_tools
            blocked -= set(lifted_tools(owner))
        except Exception as exc:  # noqa: BLE001 — nothing lifted is the closed answer
            logger.debug("lifted tools unavailable: %s", exc)
    disabled = global_disabled_tools()
    out = [{"name": name, "label": _words(name), "kind": "builtin"}
           for name in sorted(BUILTIN_TOOL_DESCRIPTIONS)
           if name not in blocked and name not in disabled]
    for tool in _mcp_tools():
        if (tool.get("is_disabled") or tool["qualified_name"] in disabled
                or not _reaches(owner, tool["qualified_name"])):
            continue
        out.append({"name": tool["qualified_name"],
                    "label": f"{tool.get('server_name') or tool.get('server_id')} · {tool['name']}",
                    "kind": "mcp"})
    return out


def _mcp_tools() -> list:
    """`McpManager.get_all_tools` with the servers' disabled lists, or `[]`
    when no manager is running (a test, or a box with MCP off)."""
    from src.mcp_manager import load_disabled_map
    from src.tool_execution import get_mcp_manager
    mgr = get_mcp_manager()
    if mgr is None:
        return []
    return list(mgr.get_all_tools(load_disabled_map()))


# ── What a person can reach: `WorkflowResources` (C-R) ───────────────────────

# Any name under the `mcp__` prefix: the policy refuses the namespace, not one
# tool at a time (`tool_security.is_public_blocked_tool`).
_ANY_MCP_TOOL = "mcp__"


def _reaches(owner, tool: str) -> bool:
    """Whether this person's agent may call `tool` at all — the dispatcher's
    own rule (`tool_execution._execute_tool_block_impl`): a name
    `is_public_blocked_tool` refuses is refused to every owner the non-admin
    policy applies to (`blocked_tools_for_owner` is empty only for an admin or
    a single-user install). Asked of the tool policy, so the palette and the
    dispatcher cannot disagree — and not as a further "is this an admin"
    (`.pantheon/check-auth-map.py` rule C)."""
    from src.tool_security import blocked_tools_for_owner, is_public_blocked_tool
    return not (is_public_blocked_tool(tool) and blocked_tools_for_owner(owner))


def _integrations(owner) -> list:
    """The registered Integrations, as a person may see them: id, name,
    preset, description and whether it is on — never the key, never the base
    URL (`P22-13`: "never seeing the key"). Admins only, because only an
    admin's agent can call one (`api_call` is in `NON_ADMIN_BLOCKED_TOOLS`)."""
    if not _reaches(owner, "api_call"):
        return []
    from src.integrations import load_integrations
    out = []
    for item in load_integrations():
        if not isinstance(item, dict) or not item.get("id"):
            continue
        out.append({"id": str(item["id"]), "name": str(item.get("name") or item["id"]),
                    "preset": str(item.get("preset") or ""),
                    "description": str(item.get("description") or ""),
                    "enabled": item.get("enabled", True) is not False})
    return out


def _own_skills(owner) -> list:
    """The skills a step can follow: the person's own, switched on — exactly
    the ones `skill_context` can read (`read_skill_md` reads the person's own
    store, not the bundled library or the legacy list)."""
    from services.memory.skills import SkillsManager
    from src.constants import DATA_DIR
    want = owner or ""
    out = []
    for skill in SkillsManager(DATA_DIR).load_active(owner=owner):
        if skill.get("bundled") or skill.get("_legacy") or (skill.get("owner") or "") != want:
            continue
        if isinstance(skill.get("name"), str) and skill["name"]:
            out.append({"name": skill["name"], "description": str(skill.get("description") or "")})
    return sorted(out, key=lambda s: s["name"])


def workstation_why(owner) -> Optional[str]:
    """`None` when a Code step can run for this person, else the sentence the
    palette greys Code with (`OFF_SENTENCE`, `UNCONFIGURED_SENTENCE`,
    `NOT_PERMITTED_SENTENCE`) — the same three conditions `workstation_for`
    checks before every call; whether the daemon is up is the run's to say."""
    from src.workstation_client import WorkstationError
    from src.workstation_access import workstation_for
    try:
        workstation_for(owner)
    except WorkstationError as exc:
        return exc.message
    return None


def _usable_mcp_tools(owner, disabled: set) -> list:
    """The MCP tools a step may call: ones this person's agent reaches,
    switched on by the server and not switched off for everyone."""
    return [t for t in _mcp_tools()
            if not t.get("is_disabled") and t.get("qualified_name") not in disabled
            and _reaches(owner, t.get("qualified_name") or _ANY_MCP_TOOL)]


def _limits(owner) -> dict:
    """The For-each cap and the longest Wait, resolved by the walker's own
    readers (`workflow_runs`, wf-walker), and the steps a run takes side by side."""
    from src import workflow_runs
    return {"foreach_max_items": int(workflow_runs.foreach_max_items(owner)),
            "wait_max_hours": int(workflow_runs.wait_max_hours()),
            "parallel_steps": int(workflow_runs.WORKFLOW_PARALLEL_STEPS)}


def workflow_resources(owner):
    """`workflow_document.WorkflowResources` for this person — what
    `validate_document` checks a step against at save and again at run."""
    from src.workflow_document import WorkflowResources
    disabled = global_disabled_tools()
    limits = _limits(owner)
    return WorkflowResources(
        integrations={i["id"]: i for i in _integrations(owner)},
        mcp_tools={t["qualified_name"]: {"input_schema": t.get("input_schema") or {},
                                         "disabled": False,
                                         "is_readonly": t.get("is_readonly"),
                                         "server_name": t.get("server_name"),
                                         "name": t.get("name")}
                   for t in _usable_mcp_tools(owner, disabled)},
        skills=frozenset(s["name"] for s in _own_skills(owner)),
        ai_tools=frozenset(c["name"] for c in ai_tool_choices(owner)),
        workstation_why=workstation_why(owner),
        foreach_max_items=limits["foreach_max_items"],
        wait_max_hours=limits["wait_max_hours"],
    )


# ── The palette (`GET /api/workflows/palette`, contract C-W) ─────────────────

# The words a person meets for each kind. The first four are Slice B's, as the
# Workbench says them today (`static/js/tasks/workflowDiagram.js:KIND_WORDS`,
# `workflowPanels.js:PALETTE_KINDS`); the browser reads these from the palette
# now and derives none (a merge point with wf-canvas: one copy, not two).
KIND_WORDS = {
    "llm": "Prompt", "research": "Research", "action": "Action", "run_task": "Run task",
    "if": "If", "switch": "Switch", "set": "Set",
    "merge": "Merge", "wait": "Wait", "foreach": "For each",
    "http": "HTTP request", "mcp": "MCP tool", "skill": "Skill", "code": "Code",
}
KIND_HINTS = {
    "llm": "Ask a model to read, write or decide something.",
    "research": "Look something up and write a report.",
    "action": "Run one of Pantheon’s built-in actions.",
    "run_task": "Run one of your tasks, with its own settings.",
    "if": "Go one way when the conditions hold, and another when they do not.",
    "switch": "Go the way of the first case that holds.",
    "set": "Hand the next step fields with the names you choose.",
    "merge": "Wait for branches that run at the same time to come back together.",
    "wait": "Hold the run for a while, or until a time of day.",
    "foreach": "Run one step once for each item in a list.",
    "http": "Send a request to one of your Integrations.",
    "mcp": "Call a tool on one of your MCP servers.",
    "skill": "Have a model follow one of your skills.",
    "code": "Run your own Python or bash in your workstation.",
}
KIND_GROUPS = {
    "llm": "Ask a model", "research": "Ask a model", "skill": "Ask a model",
    "action": "Run in Pantheon", "run_task": "Run in Pantheon",
    "if": "Decide and reshape", "switch": "Decide and reshape", "set": "Decide and reshape",
    "merge": "Flow", "wait": "Flow", "foreach": "Flow",
    "http": "Reach out", "mcp": "Reach out", "code": "Reach out",
}
_ADMIN_ONLY_WHY = {
    "http": "Only an admin's agent can send HTTP requests from the server.",
    "mcp": "Only an admin's agent can call MCP tools: each reaches whatever its server was connected to.",
}
NO_INTEGRATIONS_SENTENCE = ("No Integrations are switched on. An admin adds one in "
                            "Settings → Integrations.")
NO_MCP_TOOLS_SENTENCE = "No MCP tools are switched on. An admin connects a server in Settings → MCP."
NO_SKILLS_SENTENCE = "You have no skills switched on yet. Make one in Skills."


def _slot_json(slot) -> dict:
    return {"mapping": slot.mapping, "why": slot.why}


def _kind_slots(kind: str) -> dict:
    """`{field pattern: {mapping, why}}` from `workflow_slots.NODE_SLOTS`. A
    field decided per entry is said fail-closed with the classifier's or the
    table's sentence (the browser offers no picker there and says why); one
    the palette answers elsewhere is left out — an MCP tool's arguments
    (`mcp_tools[].args`) and a For-each's inner step (its own kind's entry)."""
    from src import workflow_slots as ws
    out = {}
    for pattern, rule in (ws.NODE_SLOTS.get(kind) or {}).items():
        if isinstance(rule, ws.Slot):
            out[pattern] = _slot_json(rule)
        elif rule is ws.BY_ENTRY_NAME:
            out[pattern] = {"mapping": ws.MAPPING_NEVER, "why": ws.WHY_NOT_TEXT}
        elif rule is ws.BY_PARAM:
            out[pattern] = {"mapping": ws.MAPPING_NEVER, "why": ws.WHY_WHAT}
    return out


def _mcp_tool_entry(tool: dict) -> dict:
    from src.workflow_slots import classify_argument
    props = (tool.get("input_schema") or {}).get("properties")
    props = props if isinstance(props, dict) else {}
    return {
        "qualified_name": tool["qualified_name"],
        "server_name": tool.get("server_name"),
        "name": tool.get("name"),
        "description": tool.get("description") or "",
        "input_schema": tool.get("input_schema") or {},
        "annotations": tool.get("annotations"),
        "is_readonly": tool.get("is_readonly"),
        "readonly_source": tool.get("readonly_source"),
        "override": tool.get("override"),
        "args": {name: _slot_json(classify_argument(name, schema)) for name, schema in props.items()},
    }


def build_palette(owner) -> dict:
    """What a person may put on their canvas, and what each setting may be
    filled with — the browser is handed these answers and derives nothing
    (`workflow_slots` is the one place that decides, `Law 7`).

    `D-2026-10-01-05`'s minor call: the palette offers only what the person's
    agent can already reach. A kind they may not use is listed greyed, with
    the sentence that says why; the Integrations' keys and base URLs are never
    in it.
    """
    from src.workflow_document import NODE_KINDS, ports_of
    from src.workflow_logic import OPERATOR_WORDS, OPERATORS

    reaches = {"http": _reaches(owner, "api_call"), "mcp": _reaches(owner, _ANY_MCP_TOOL)}
    disabled = global_disabled_tools()
    integrations = [i for i in _integrations(owner) if i["enabled"]]
    mcp_tools = [_mcp_tool_entry(t) for t in _usable_mcp_tools(owner, disabled)]
    skills = _own_skills(owner)
    station_why = workstation_why(owner)

    def availability(kind: str) -> Tuple[bool, str]:
        if kind in _ADMIN_ONLY_WHY and not reaches[kind]:
            return False, _ADMIN_ONLY_WHY[kind]
        if kind == "http" and not integrations:
            return False, NO_INTEGRATIONS_SENTENCE
        if kind == "mcp" and not mcp_tools:
            return False, NO_MCP_TOOLS_SENTENCE
        if kind == "skill" and not skills:
            return False, NO_SKILLS_SENTENCE
        if kind == "code" and station_why:
            return False, station_why
        return True, ""

    kinds = []
    for kind in NODE_KINDS:
        available, why = availability(kind)
        kinds.append({
            "kind": kind,
            "word": KIND_WORDS.get(kind, kind),
            "group": KIND_GROUPS.get(kind, ""),
            "hint": KIND_HINTS.get(kind, ""),
            "ports": list(ports_of({"kind": kind, "config": {}})),
            "available": available,
            "why": why,
            "slots": _kind_slots(kind),
        })
    return {
        "kinds": kinds,
        "integrations": [{k: i[k] for k in ("id", "name", "preset", "description")}
                         for i in integrations],
        "mcp_tools": mcp_tools,
        "skills": skills,
        "ai_tools": ai_tool_choices(owner),
        "workstation": {"available": station_why is None, "why": station_why or ""},
        "limits": _limits(owner),
        "operators": [{"op": op, "word": OPERATOR_WORDS.get(op, op)} for op in OPERATORS],
    }


# ── The fields a step can pick from (`GET …/nodes/{node_id}/fields`, C-W) ────

ORIGIN_LAST_RUN = "last_run"
ORIGIN_PIN = "pin"
ORIGIN_DECLARED = "declared"
FIELD_ORIGINS = (ORIGIN_LAST_RUN, ORIGIN_PIN, ORIGIN_DECLARED)


def _loads(text):
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _iso(value) -> Optional[str]:
    return value.isoformat() + "Z" if value is not None else None


def _fields_of(node_id: str, text, data) -> list:
    """`[{ref, path, type, example}]` for what a step made: its text, then
    every field of its data that a reference can name (`flatten_fields`)."""
    from src.workflow_refs import flatten_fields, format_ref
    out = []
    if text is not None:
        about = flatten_fields(text)[0]
        out.append({"ref": format_ref(node_id, "text"), "path": [], "type": about["type"],
                    "example": about["example"]})
    if data is not None:
        for f in flatten_fields(data):
            out.append({"ref": format_ref(node_id, "data", f["path"]), "path": f["path"],
                        "type": f["type"], "example": f["example"]})
    return out


def _declared_fields(node_id: str, names_types) -> list:
    from src.workflow_refs import format_ref
    out = []
    for name, kind in names_types:
        try:
            ref = format_ref(node_id, "data", [name])
        except ValueError:
            continue                       # a name no reference can name is not offered
        out.append({"ref": ref, "path": [name], "type": kind, "example": None})
    return out


def _start_targets(graph: dict) -> list:
    """The steps the start leads to: its own arrows, or — in a document with
    none (Slice B's) — the steps nothing leads to."""
    from src.workflow_document import START_KEY
    edges = graph.get("edges") or ()
    explicit = [e["to"] for e in edges if e.get("from") == START_KEY]
    if explicit:
        return explicit
    led_to = {e["to"] for e in edges}
    return [n["id"] for n in graph.get("nodes") or () if n["id"] not in led_to]


def _successors(graph: dict, node_id: str) -> list:
    return [e["to"] for e in graph.get("edges") or () if e.get("from") == node_id]


def _source(node_id, label, kind, origin, at, fields) -> dict:
    return {"node_id": node_id, "label": label, "kind": kind, "origin": origin,
            "at": at, "fields": fields}


def available_fields(db, wf, trigger, graph, node_id) -> dict:
    """`{sources: [...]}` — the fields `node_id` can pick from: the start's and
    every step upstream of it (`workflow_document.upstream_of`), each from up
    to three places, saying which:

      * `last_run` — the newest real record of that step (`last_node_record`;
        a dry run is never "the last run"), its text and data;
      * `pin` — the sample pinned on a step it leads to, which is exactly what
        that step would be handed: the step's result and data, or for the
        start the trigger's data;
      * `declared` — what the step promises before any run: an AI step's
        answer fields, a Set step's names, the start's event or webhook fields.

    A record cut to fit its cap is not read for fields: its fields are not
    all there, and offering half of them would offer a path that resolves to
    nothing.
    """
    from src.event_bus import EVENT_PAYLOAD_FIELDS, WEBHOOK_PAYLOAD_FIELDS
    from src.workflow_document import START_KEY, upstream_of
    from src.workflow_runs import is_truncated, last_node_record

    nodes = {n["id"]: n for n in graph.get("nodes") or ()}
    upstream = upstream_of(graph, node_id)
    task_id = getattr(trigger, "id", None)
    sources = []

    # The start: what fired the run.
    starters = _start_targets(graph)
    for first in starters:
        rec = last_node_record(db, task_id, first) if task_id else None
        envelope = _loads(rec.input) if rec is not None else None
        if isinstance(envelope, dict) and not is_truncated(envelope) \
                and isinstance(envelope.get("data"), dict):
            sources.append(_source(START_KEY, "What started it", "start", ORIGIN_LAST_RUN,
                                   _iso(rec.started_at),
                                   _fields_of(START_KEY, None, envelope["data"])))
            break
    for first in starters:
        pinned = (nodes.get(first) or {}).get("pinned")
        if isinstance(pinned, dict) and isinstance(pinned.get("data"), dict):
            sources.append(_source(START_KEY, "What started it", "start", ORIGIN_PIN, None,
                                   _fields_of(START_KEY, None, pinned["data"])))
            break
    trigger_type = getattr(trigger, "trigger_type", None)
    if trigger_type == "event":
        declared = EVENT_PAYLOAD_FIELDS.get(getattr(trigger, "trigger_event", None), ())
    elif trigger_type == "webhook":
        declared = WEBHOOK_PAYLOAD_FIELDS
    else:
        declared = ()
    if declared:
        sources.append(_source(START_KEY, "What started it", "start", ORIGIN_DECLARED, None,
                               _declared_fields(START_KEY, [(f, None) for f in declared])))

    for up_id in [n for n in nodes if n in upstream]:
        node = nodes[up_id]
        label, kind = node.get("label") or up_id, node.get("kind")
        rec = last_node_record(db, task_id, up_id) if task_id else None
        output = _loads(rec.output) if rec is not None else None
        if isinstance(output, dict) and not is_truncated(output):
            sources.append(_source(up_id, label, kind, ORIGIN_LAST_RUN,
                                   _iso(rec.finished_at or rec.started_at),
                                   _fields_of(up_id, output.get("text"), output.get("data"))))
        for nxt in _successors(graph, up_id):
            pinned = (nodes.get(nxt) or {}).get("pinned")
            handed = pinned.get("data") if isinstance(pinned, dict) else None
            if isinstance(handed, dict) and ("result" in handed or "data" in handed):
                sources.append(_source(up_id, label, kind, ORIGIN_PIN, None,
                                       _fields_of(up_id, handed.get("result"), handed.get("data"))))
                break
        config = node.get("config") or {}
        promised = []
        if kind == "llm" and isinstance(config.get("answer_fields"), list):
            promised = [(f.get("name"), f.get("type")) for f in config["answer_fields"]
                        if isinstance(f, dict) and isinstance(f.get("name"), str)]
        elif kind == "set" and isinstance(config.get("fields"), list):
            promised = [(f.get("name"), None) for f in config["fields"]
                        if isinstance(f, dict) and isinstance(f.get("name"), str)]
        if promised:
            sources.append(_source(up_id, label, kind, ORIGIN_DECLARED, None,
                                   _declared_fields(up_id, promised)))
    return {"sources": sources}
