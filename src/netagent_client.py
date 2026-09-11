# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pantheon's side of the network agent. A credential, not a capability.

`P17-01`. The agent runs on the host and has the LAN; this module holds a token
for it. The container still cannot reach `192.168.1.1` and that stays true —
adding this must not become the hole `FORBIDDEN.md` Part 2 says never opens.

**HOW THAT IS GUARANTEED, because "we'll be careful" is not a control.**

The only two inputs are the operator's setting and a path from a *fixed table in
this file*. There is no parameter through which a target address can arrive. A
prompt injection reading *"fetch `http://169.254.169.254/` through the network
agent"* has nowhere to put the address: `call()` takes a route name, the route
names are a frozenset declared below, and the base comes from `netagent_url`
which the agent may read and may never write (`_is_secret` covers the token; the
URL is a structured operator setting). That is the same argument `P17-02` makes
about CIDRs — *refused because it was never named*, not because the model
declined, which is not a security control.

**The SSRF validators are untouched and stay that way.** They guard URLs that
arrive from *content*, and `web_fetch` still refuses `192.168.1.1`. This is a
call to an address the operator wrote down, which is the distinction
`D-2026-09-10-01` draws and `src/paced_http.py`'s own docstring already drew:
*"this module is for the calls a developer wrote down… where the address is not
attacker-controlled."*
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# Every route this client will ever ask for. Declared, not derived: a client
# that forwards an arbitrary path is a proxy, and a proxy into the host network
# is precisely what the container is not allowed to have.
ROUTES = frozenset({"health", "whoami", "networks", "neighbours"})

# Routes that take an address. Separate from `ROUTES` for the same reason the
# agent keeps `TARGET_ROUTES` separate: it makes "does this need a target" a
# property of the table rather than of whoever wrote the call, so a new one
# cannot skip the question.
#
# **The bound that matters is on the agent, not here.** `P17-02`: a gate the
# gated party can widen is not a gate, and Pantheon is the gated party. This
# side refuses early so the operator gets a sentence instead of a 403, and
# because a call that was never going to be allowed should not be made — but if
# this check were deleted the agent would still refuse, and a test asserts that
# rather than trusting it.
TARGET_ROUTES = frozenset({"reach", "dns"})

# What a healthy agent calls itself. Checked so "something answered on that
# port" is not mistaken for "the agent is up" — the most likely something else
# on a LAN port is a router's admin page, and reporting that as the agent would
# send the operator hunting the wrong fault.
AGENT_NAME = "pantheon-netagent"

_TIMEOUT = 5.0


def _setting(key: str) -> str:
    try:
        from src.settings import get_setting
        return str(get_setting(key, "") or "").strip()
    except Exception:
        # Settings unreadable is "no agent configured", not a crash. Every
        # caller below already handles that.
        return ""


def parse_agent_base(raw: str) -> Optional[str]:
    """An agent origin out of a string, or None. Pure — reads no settings.

    Returns the *origin only*, rebuilt from the parts rather than trimmed from
    the string, so a value like `http://host:7010/../../x` cannot survive by
    looking like a base URL. Same reasoning as
    `companion/pairing.parse_companion_base_url`, which refuses anything that
    does not round-trip to its own origin.

    Split from `agent_base()` so the settings route can refuse a bad address at
    the moment somebody types it, rather than storing it and having every call
    fail silently afterwards — which is `P17-09`'s lesson applied before it can
    happen again.
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    if not parts.hostname:
        return None
    if parts.username or parts.password:
        # Credentials in a URL are a credential in a log. The token goes in a
        # header where it can be redacted.
        return None
    try:
        if parts.port is not None and not (1 <= parts.port <= 65535):
            return None
    except ValueError:
        return None
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def agent_base() -> Optional[str]:
    """The configured agent origin, or None."""
    return parse_agent_base(_setting("netagent_url"))


def configured() -> bool:
    """Both halves, because one without the other reaches nothing."""
    return bool(agent_base()) and bool(_setting("netagent_token"))


def _url_for(route: str) -> Tuple[Optional[str], Optional[str]]:
    if route not in ROUTES and route not in TARGET_ROUTES:
        # Not an error the caller can talk its way out of: the route table is
        # in this file and nothing outside it can add a name.
        return None, f"unknown network-agent route {route!r}"
    base = agent_base()
    if not base:
        return None, "no network agent is configured"
    if not _setting("netagent_token"):
        return None, "no network-agent credential is configured"
    return f"{base}/{route}", None


def _target_param(target: str) -> Tuple[Optional[str], Optional[str]]:
    """A `?target=` query string, or a refusal.

    Encoded rather than concatenated, so a target carrying `&` or `#` cannot add
    a second parameter to a request this file built. The agent reads exactly one
    `target` and ignores the rest, but "the other end is careful" is not a reason
    to send something ambiguous.
    """
    target = str(target or "").strip()
    if not target:
        return None, "this network-agent route needs a target"
    if len(target) > 255:
        return None, "that target is too long to be an address or a hostname"
    if any(c.isspace() for c in target):
        return None, f"{target!r} is not an address or a hostname"
    return "?" + urlencode({"target": target}), None


async def call(route: str, target: str = "") -> Dict[str, Any]:
    """Ask the agent one of the questions it answers. Never raises.

    **`target` is not an address this function will fetch.** It is a value passed
    to a route already in the table above, which the *agent* then checks against
    an allowlist Pantheon cannot edit. There is still no way to name a
    destination here: the origin comes from the operator's setting and the path
    from `ROUTES`/`TARGET_ROUTES`. `"reach 169.254.169.254"` produces a request
    to the operator's own agent, which refuses it — refused because the address
    was never named, which is `P17-02`'s whole argument.

    Paced through `src.paced_http` like every other outbound call in this
    product — the agent's host is local so the policy costs nothing, but
    `check-outbound.py`'s rule is that a call leaves the process through the
    limiter, not that it leaves it quickly.
    """
    url, problem = _url_for(route)
    if problem:
        return {"error": problem, "exit_code": 1}

    if route in TARGET_ROUTES:
        query, problem = _target_param(target)
        if problem:
            return {"error": problem, "exit_code": 1}
        url = f"{url}{query}"
    elif target:
        return {"error": f"the {route!r} route does not take a target",
                "exit_code": 1}

    token = _setting("netagent_token")
    try:
        from src import paced_http
        response = await paced_http.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
            authenticated=True,
        )
    except Exception as e:  # noqa: BLE001
        # The message must not carry the token, and `url` never does — the
        # credential is a header precisely so this line is safe to write.
        logger.info("network agent unreachable at %s: %s", url, type(e).__name__)
        return {"error": f"the network agent did not answer ({type(e).__name__})",
                "exit_code": 1}

    status = getattr(response, "status_code", 0)
    if status == 403:
        # The agent's allowlist refused it. Its own sentence says what the list
        # is and where it is set, which is more useful than anything this side
        # could invent, so it is passed through rather than replaced.
        try:
            return {"error": response.json().get("error", "refused by the network agent"),
                    "refused": True, "exit_code": 1}
        except Exception:  # noqa: BLE001
            return {"error": "refused by the network agent's allowlist",
                    "refused": True, "exit_code": 1}
    if status == 401:
        return {"error": "the network agent refused this credential; re-paste the "
                         "token it printed when it started", "exit_code": 1}
    if status != 200:
        return {"error": f"the network agent answered {status}", "exit_code": 1}
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return {"error": "the network agent answered with something that is not JSON",
                "exit_code": 1}
    return payload if isinstance(payload, dict) else {"result": payload}


async def exec_on_host(command: str, *, elevated: bool = False,
                       timeout: Any = None, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Send a command to the agent. Never raises.

    **The destination is still fixed.** `command` is a *body field* to the one
    `/exec` path on the operator's own agent — it is not a URL and there is no
    parameter here that names where the request goes. The same property
    `test_no_parameter_can_change_where_the_request_goes` asserts for `call()`
    holds for this, and the same test covers it.
    """
    base = agent_base()
    token = _setting("netagent_token")
    if not base:
        return {"error": "no network agent is configured", "exit_code": 1}
    if not token:
        return {"error": "no network-agent credential is configured", "exit_code": 1}
    if not str(command or "").strip():
        return {"error": "an empty command is not a command", "exit_code": 1}

    payload: Dict[str, Any] = {"command": command, "elevated": bool(elevated)}
    if timeout:
        payload["timeout"] = timeout
    if cwd:
        payload["cwd"] = cwd

    try:
        from src import paced_http
        response = await paced_http.post(
            f"{base}/exec",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            # A host command may legitimately take minutes; the agent caps it
            # itself, and this only has to outlast that cap.
            timeout=float(timeout or 120) + 30.0,
            authenticated=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.info("host agent unreachable at %s: %s", base, type(e).__name__)
        return {"error": f"the network agent did not answer ({type(e).__name__})",
                "exit_code": 1}

    status = getattr(response, "status_code", 0)
    try:
        payload_back = response.json()
    except Exception:  # noqa: BLE001
        return {"error": "the network agent answered with something that is not JSON",
                "exit_code": 1}
    if status == 401:
        return {"error": "the network agent refused this credential; re-paste the "
                         "token it printed when it started", "exit_code": 1}
    if status == 403:
        # The agent's own refusal, passed through verbatim. Its sentence names
        # the rule and says the list cannot be changed from here, which is more
        # useful than anything this side could invent.
        return {"error": payload_back.get("error", "refused by the host agent"),
                "refused_by": payload_back.get("refused_by"),
                "rule": payload_back.get("rule"), "exit_code": 1}
    if status != 200:
        return {"error": f"the network agent answered {status}", "exit_code": 1}
    return payload_back if isinstance(payload_back, dict) else {"result": payload_back}


async def health() -> Dict[str, Any]:
    """Is the agent there, and is it the agent?

    A 200 from the configured address is not enough. The most likely other
    listener on a LAN port is a router's admin page, and reporting that as a
    healthy agent sends the operator hunting the wrong fault.
    """
    result = await call("health")
    if result.get("error"):
        return {"reachable": False, "detail": result["error"]}
    if result.get("agent") != AGENT_NAME:
        return {"reachable": False,
                "detail": "something answered on that address, but it is not the "
                          "network agent"}
    return {"reachable": True, "version": result.get("version")}
