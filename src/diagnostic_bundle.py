"""A bug report someone can read in full before it goes anywhere.

`P16-14`. The owner, weighing opt-in vendor telemetry: *"having people report
bugs is not very easy to get to happen."* True. The usual conclusion is to open
a telemetry pipe, and that treats the symptom.

People do not report bugs because **they do not know what to include** and
**they are afraid of leaking their own data** — and in this product the second
fear is correct. A stack trace here carries file paths (which contain their
username), endpoint URLs (which describe their LAN), model names, mail hosts,
and often a slice of the message that caused the failure. Someone running this
on their own hardware, for their own private stack, is right to hesitate.

So this builds the report *for* them, redacts it, and hands it back **as text on
their own screen**, editable, before anything is copied anywhere. There is no
collector, no standing pipe, no background upload, and no data-controller
obligation created. The destination is theirs and is chosen per incident — which
is `Law 16` satisfied by design rather than by restraint.

TWO RULES THAT SHAPE EVERYTHING BELOW

**1. Settings are allowlisted, never denylisted.** The obvious approach is to
strip keys matching `key|token|secret`. Measured against this tree's 71
settings, that heuristic flags `agent_input_token_budget`, `keybinds` and
`research_max_tokens` — none of them secret — and it would sail straight past a
credential someone names `openrouter_thing`. A denylist is a guess about
tomorrow's setting names. So: values appear only for keys on `SHOW_VALUE`, and
every other setting reports its *shape* — configured or not, and what type —
which is what a maintainer actually needs to read.

**2. Redaction runs over free text, because that is where the leak lives.**
Settings are structured and easy. Logs and tracebacks are not, and they are the
part worth sending. `redact()` is deliberately aggressive: over-redaction costs
a round trip, under-redaction costs someone their API key in a public issue, and
the person can put anything back before they copy — they are looking at it.
"""
import getpass
import json
import os
import platform
import re
import sys
from typing import Any, Dict, List

from core.log_safety import redact_url

# Settings whose VALUE is shown. Everything else reports only whether it is set.
# The test is "would a maintainer's first question be answered by this?" — not
# "is this secret?", which is the question that produces denylists.
SHOW_VALUE = frozenset({
    "memory_enabled", "rag_enabled", "web_search_enabled", "deep_research_enabled",
    "search_provider", "search_fallback_chain", "remote_images",
    "allow_model_download", "embedding_backend", "embedding_model",
    "tts_enabled", "stt_enabled", "theme", "font_family",
    "agent_mode_enabled", "browser_mcp_enabled", "code_execution_enabled",
    "notifications_enabled", "auth_enabled", "require_2fa",
})

_HOME_PATTERNS = (
    re.compile(r"(?i)[A-Z]:\\+Users\\+[^\\/:*?\"<>|\r\n]+"),   # C:\Users\someone
    re.compile(r"/(?:home|Users)/[^/\s:'\"]+"),                 # /home/someone
)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>\]);,]+", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_BEARER = re.compile(r"(?i)\b(bearer|token|api[_-]?key|authorization)\b\s*[:=]\s*\S+")
# Long opaque strings: keys, hashes, session ids. 32+ so a git short-sha or a
# model name with digits survives — those are useful and are not secrets.
_OPAQUE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
_KNOWN_PREFIX = re.compile(r"\b(?:sk|pk|ghp|gho|ghu|ghs|ghr|xox[abps]|hf|glpat)[-_][A-Za-z0-9_\-]{8,}\b")

# Loopback is not identifying and is load-bearing in almost every report about
# a local model server. Redacting it makes the bundle worse for no privacy gain.
_KEEP_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255", "::1"}


def redact(text: str) -> str:
    """Strip the six things a Pantheon log leaks about the person running it.

    Order matters and is not obvious. The username in a path goes first: it is
    the identifier most likely to turn up inside another match. URLs go next, so
    a credential in a query string leaves *with* the URL instead of leaving a
    mangled fragment behind. The bare username goes last, over whatever
    survived, so no earlier substitution can reintroduce it.
    """
    if not text:
        return text
    out = text
    for pat in _HOME_PATTERNS:
        out = pat.sub("~", out)
    # URLs first, and this ordering was measured rather than assumed. With
    # `_BEARER` ahead of it, `…/embeddings?api_key=abc` became
    # `…/embeddings<redacted>` — safe, but a mangled fragment, and the comment
    # claiming otherwise was wrong. `redact_url` drops userinfo, query and
    # fragment in one move, so the whole credential leaves with the URL.
    out = _URL.sub(lambda m: redact_url(m.group(0)) or "<url>", out)
    out = _KNOWN_PREFIX.sub("<redacted-credential>", out)
    out = _BEARER.sub(lambda m: f"{m.group(1)}=<redacted>", out)
    out = _EMAIL.sub("<email>", out)
    out = _IPV4.sub(lambda m: m.group(0) if m.group(0) in _KEEP_IPS else "<ip>", out)
    out = _OPAQUE.sub("<redacted>", out)
    # The username can appear outside any path — in a hostname, a mail address
    # already reduced to <email>, a "logged in as" line. Do it last, over what
    # survived, so it cannot be reintroduced by an earlier substitution.
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    if user and len(user) > 2:
        out = re.sub(rf"\b{re.escape(user)}\b", "<user>", out)
    return out


def _setting_shape(value: Any) -> str:
    """What a setting looks like, for the ones whose value is not shown."""
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "set" if value.strip() else "not set"
    if isinstance(value, (list, tuple, set)):
        return f"{len(value)} item(s)" if value else "empty"
    if isinstance(value, dict):
        return f"{len(value)} key(s)" if value else "empty"
    return type(value).__name__


def collect_settings() -> Dict[str, Any]:
    try:
        from src.settings import DEFAULT_SETTINGS, get_setting
    except Exception as e:  # pragma: no cover - import guard
        return {"_error": f"settings unavailable: {e}"}
    out: Dict[str, Any] = {}
    for key in sorted(DEFAULT_SETTINGS):
        try:
            value = get_setting(key, DEFAULT_SETTINGS.get(key))
        except Exception:
            out[key] = "unreadable"
            continue
        if key in SHOW_VALUE:
            out[key] = redact(str(value)) if isinstance(value, str) else value
        else:
            out[key] = _setting_shape(value)
    return out


def collect_environment() -> Dict[str, Any]:
    try:
        from src.constants import APP_VERSION
    except Exception:
        APP_VERSION = "unknown"
    return {
        "pantheon": APP_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(terse=True),
        "machine": platform.machine(),
        "in_docker": os.path.exists("/.dockerenv"),
    }


def collect_logs(limit: int = 120) -> List[str]:
    """The tail of app.log, redacted line by line."""
    try:
        from core.constants import DATA_DIR
        path = os.path.join(DATA_DIR, "logs", "app.log")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        return [f"<log unavailable: {type(e).__name__}>"]
    return [redact(line.rstrip("\r\n")) for line in lines[-max(1, min(limit, 500)):]]


def collect_self_checks() -> Dict[str, Any]:
    """Reuse `P16-15`. A bug report should carry what the product already knows
    is wrong — often that IS the bug, and it is the section a maintainer reads
    first."""
    try:
        from src.self_checks import run_self_checks
        return run_self_checks()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def collect_outbound() -> Dict[str, Any]:
    """Which hosts the limiter is holding off (`P15`). A report that says
    'GitHub import failed' is a different bug depending on whether we were in a
    cooldown at the time."""
    try:
        from src.rate_limiter import outbound
        return {redact(k): v for k, v in (outbound.snapshot() or {}).items()}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def build_bundle(*, note: str = "", trace: str = "", log_limit: int = 120) -> Dict[str, Any]:
    """Everything, redacted. Assembled locally; sent nowhere by this function."""
    return {
        "what_happened": redact(note or ""),
        "traceback": redact(trace or ""),
        "environment": collect_environment(),
        "self_checks": collect_self_checks(),
        "outbound_throttling": collect_outbound(),
        "settings": collect_settings(),
        "recent_logs": collect_logs(log_limit),
    }


def render_markdown(bundle: Dict[str, Any]) -> str:
    """The bundle as text a person can read, edit and paste into an issue.

    Markdown rather than JSON because the destination is a GitHub issue and the
    reader is a human. The user sees exactly these characters before anything
    leaves — which is the entire design.
    """
    env = bundle.get("environment", {})
    lines: List[str] = ["### What happened", ""]
    lines.append(bundle.get("what_happened") or "_(describe it here)_")
    if bundle.get("traceback"):
        lines += ["", "### Traceback", "", "```", bundle["traceback"], "```"]

    lines += ["", "### Environment", ""]
    for k, v in env.items():
        lines.append(f"- **{k}**: {v}")

    checks = bundle.get("self_checks") or {}
    interesting = [c for c in (checks.get("checks") or []) if c.get("status") != "ok"]
    lines += ["", "### Self-checks", ""]
    if interesting:
        for c in interesting:
            lines.append(f"- **{c.get('status')}** — {c.get('title')}: {c.get('summary')}")
    else:
        lines.append("- all passing")

    throttled = bundle.get("outbound_throttling") or {}
    if throttled and "error" not in throttled:
        lines += ["", "### Outbound throttling", "", "```json",
                  json.dumps(throttled, indent=2, sort_keys=True)[:2000], "```"]

    lines += ["", "### Settings", "",
              "_Values are shown only for feature flags. Everything else reports "
              "whether it is configured, never what it is set to._", "", "```json",
              json.dumps(bundle.get("settings", {}), indent=2, sort_keys=True), "```"]

    logs = bundle.get("recent_logs") or []
    lines += ["", f"### Recent logs ({len(logs)} lines, redacted)", "", "```"]
    lines += logs or ["(no log file)"]
    lines += ["```", "",
              "_Assembled locally by Pantheon and redacted before display. "
              "Nothing was sent anywhere — read it, edit anything you would "
              "rather not share, then copy it._"]
    return "\n".join(lines)
