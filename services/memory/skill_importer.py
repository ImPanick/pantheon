# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import SKILL.md bundles from public GitHub (or skills.sh → GitHub) URLs."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple, cast
from urllib.parse import quote, urljoin, urlparse

import httpcore
import contextvars
import os

import httpx

from src.url_safety import _default_resolver, check_outbound_url

logger = logging.getLogger(__name__)

# Identify ourselves. The default `python-httpx/x.y` is a bot signature that
# GitHub's abuse detection scores against you before it has read a single path.
_USER_AGENT = "Pantheon-SkillImporter/1.0 (+https://github.com/ImPanick/pantheon)"

# A hard ceiling on HTTP requests for one import, independent of how many files
# come back. MAX_FILES below caps *files kept*, which is not the same thing: a
# directory costs a request whether or not it yields a file, and a tree of empty
# or binary-only folders used to cost an unbounded number of api.github.com calls
# while `len(out)` never moved. Unauthenticated GitHub allows 60 requests an hour
# in total, so one import must not be able to spend them all.
MAX_REQUESTS_UNAUTHENTICATED = 40
MAX_REQUESTS_AUTHENTICATED = 200

# `B926`: raised at the owner's request (2026-09-30) after
# `vercel-labs/agent-browser` failed on "file too large". The caps stay caps
# (`FORBIDDEN.md` Part 2, "keep the byte/count caps"); what changed is their
# size, and that a file over the per-file cap is now left out with a note
# instead of failing the whole import.
MAX_FILES = 256
MAX_TOTAL_BYTES = 10_000_000
MAX_FILE_BYTES = 2_000_000
# Files that are never part of what a skill tells a model — a dependency
# lockfile is the usual reason a bundle blew its size cap.
_SKIPPED_NAMES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
    "composer.lock", "poetry.lock", "cargo.lock", "gemfile.lock", "bun.lock",
})
ALLOWED_SUFFIXES = (
    ".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".toml",
    ".js", ".ts", ".css", ".html", ".xml", ".csv",
)
TEXT_NAMES = {"skill.md", "license", "license.md", "readme.md"}
_GITHUB_HOSTS = frozenset({
    "github.com", "www.github.com", "api.github.com", "raw.githubusercontent.com",
    # `P8-49`. Where GitHub serves a repository's archive — every
    # `github.com/<o>/<r>/archive/…` link redirects here. It serves the same
    # repository's files raw.githubusercontent.com does, one request for all
    # of them, so it widens no supply chain; the SSRF property is still held
    # by the outbound-URL check and the pinned transport (`FORBIDDEN.md`).
    "codeload.github.com",
})
_SKILLS_SH_HOSTS = frozenset({"skills.sh", "www.skills.sh"})


_request_budget: contextvars.ContextVar = contextvars.ContextVar("skill_import_budget", default=None)


class _Budget:
    """Requests remaining for one import, and what we spent them on."""

    __slots__ = ("remaining", "spent", "authenticated")

    def __init__(self, remaining: int, authenticated: bool):
        self.remaining = remaining
        self.spent = 0
        self.authenticated = authenticated

    def take(self) -> None:
        if self.remaining <= 0:
            raise SkillImportError(
                f"skill import stopped after {self.spent} requests to GitHub — the link points at "
                "a tree too large to walk politely. Link the skill's own folder or its SKILL.md "
                "rather than the repository root."
            )
        self.remaining -= 1
        self.spent += 1


def _github_credentials() -> str:
    """A GitHub token, if the operator has supplied one. Empty string otherwise.

    Unauthenticated api.github.com allows **60 requests per hour per IP**; with a
    token it is 5,000. A token is therefore the difference between "a couple of
    imports an hour" and "as many as you like", and it is the single most useful
    thing an operator can set here.

    The env fallback below is reachable, unlike the one `H06` found dead in
    `resolve_task_concurrency_cap`, and the difference is worth understanding
    before copying either: `get_setting` merges `DEFAULT_SETTINGS` on every read,
    so an env layer beneath a setting is dead **whenever the shipped default is
    truthy**. This default is `""`, so the `or` falls through exactly as written.
    Do not generalise from this to a numeric setting.
    """
    try:
        from src.settings import get_setting

        tok = (get_setting("github_token", "") or "").strip()
    except Exception:
        tok = ""
    if not tok:
        tok = (os.environ.get("PANTHEON_GITHUB_TOKEN") or "").strip()
    return tok


def _github_host(url: str) -> str:
    return (urlparse(str(url)).hostname or "").lower()


def _assert_github_url(url: str, *, context: str = "URL") -> None:
    host = _github_host(url)
    if host not in _GITHUB_HOSTS:
        raise SkillImportError(
            f"{context} must stay on GitHub (got {host or 'unknown host'})"
        )


@dataclass
class ResolvedSource:
    owner: str
    repo: str
    ref: str
    path: str  # directory or file path inside repo (no leading slash)
    # `B926`. A skill named rather than located — a skills.sh page or its
    # `npx skills add <repo> --skill <name>` line say which skill, not where
    # in the repository it lives. Found by `_locate_named_skill`.
    skill: str = ""
    # False when the link named no branch (a bare repository or a skills.sh
    # link): `main` is tried, then `master`.
    ref_known: bool = True


class SkillImportError(ValueError):
    pass


def _safe_relpath(rel: str) -> str:
    rel = (rel or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel.startswith("..") or "/../" in f"/{rel}/":
        raise SkillImportError(f"unsafe path: {rel!r}")
    parts = [p for p in rel.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise SkillImportError(f"unsafe path: {rel!r}")
    return "/".join(parts)


def _is_text_file(name: str) -> bool:
    low = name.lower()
    if low in TEXT_NAMES:
        return True
    return any(low.endswith(s) for s in ALLOWED_SUFFIXES)


# Max redirect hops to follow manually while re-validating each one.
_MAX_FETCH_REDIRECTS = 5


def _validated_ips(raw_ips: List[str]) -> List[ipaddress._BaseAddress]:
    """Parse and de-duplicate one resolver snapshot in resolver order."""
    ips: List[ipaddress._BaseAddress] = []
    seen = set()
    for raw in raw_ips:
        if not isinstance(raw, str):
            continue
        try:
            ip = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            continue
        if ip in seen:
            continue
        seen.add(ip)
        ips.append(ip)
    return ips


def _resolve_and_check_url(url: str) -> List[ipaddress._BaseAddress]:
    """Return the exact address snapshot approved for one fetch hop."""
    resolved_ips: List[str] = []

    def _recording_resolver(host: str) -> List[str]:
        answers = list(_default_resolver(host))
        resolved_ips[:] = answers
        return answers

    ok, reason = check_outbound_url(
        url,
        block_private=True,
        resolver=_recording_resolver,
    )
    if not ok:
        raise SkillImportError(f"outbound URL blocked: {reason}")

    pinned_ips = _validated_ips(resolved_ips)
    if not pinned_ips:
        raise SkillImportError("outbound URL blocked: host did not resolve to a usable address")
    return pinned_ips


# Backward compatibility alias for tests importing _check_fetch_url directly
_check_fetch_url = _resolve_and_check_url


class _PinnedBackend(httpcore.NetworkBackend):
    """Connect only to addresses from one validated DNS snapshot."""

    def __init__(self, ips: List[ipaddress._BaseAddress]):
        self._ips = [str(ip) for ip in ips]
        self._real = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        deadline = None if timeout is None else time.monotonic() + timeout
        last_exc: Optional[Exception] = None
        for ip in self._ips:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                return self._real.connect_tcp(
                    ip,
                    port,
                    remaining,
                    local_address,
                    socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
                if deadline is not None and time.monotonic() >= deadline:
                    break
        if last_exc is not None:
            raise last_exc
        raise httpcore.ConnectError("no validated address available")

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return self._real.connect_unix_socket(path, timeout, socket_options)

    def sleep(self, seconds: float) -> None:
        return self._real.sleep(seconds)


_HTTPCORE_TO_HTTPX_EXC = {
    httpcore.ConnectError: httpx.ConnectError,
    httpcore.ConnectTimeout: httpx.ConnectTimeout,
    httpcore.LocalProtocolError: httpx.LocalProtocolError,
    httpcore.NetworkError: httpx.NetworkError,
    httpcore.PoolTimeout: httpx.PoolTimeout,
    httpcore.ProtocolError: httpx.ProtocolError,
    httpcore.ProxyError: httpx.ProxyError,
    httpcore.ReadError: httpx.ReadError,
    httpcore.ReadTimeout: httpx.ReadTimeout,
    httpcore.RemoteProtocolError: httpx.RemoteProtocolError,
    httpcore.TimeoutException: httpx.TimeoutException,
    httpcore.UnsupportedProtocol: httpx.UnsupportedProtocol,
    httpcore.WriteError: httpx.WriteError,
    httpcore.WriteTimeout: httpx.WriteTimeout,
}


class _PinnedTransport(httpx.BaseTransport):
    """Pin socket connects while preserving URL authority, Host, and TLS SNI."""

    def __init__(self, ips: List[ipaddress._BaseAddress], max_bytes: Optional[int] = None):
        self._pinned_ips = list(ips)
        # `P8-49`. A ceiling on the body, enforced while it streams: a
        # repository archive is the one response here whose size is not
        # bounded by what GitHub serves for a single file.
        self._max_bytes = max_bytes
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            http1=True,
            http2=False,
            network_backend=_PinnedBackend(ips),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        core_response = None
        try:
            core_response = self._pool.handle_request(core_request)
            if self._max_bytes is None:
                content = b"".join(cast(Iterable[bytes], core_response.stream))
            else:
                chunks, got = [], 0
                for chunk in cast(Iterable[bytes], core_response.stream):
                    got += len(chunk)
                    if got > self._max_bytes:
                        raise SkillImportError(
                            f"download larger than {self._max_bytes:,} bytes")
                    chunks.append(chunk)
                content = b"".join(chunks)
        except Exception as exc:
            mapped = _HTTPCORE_TO_HTTPX_EXC.get(type(exc))
            if mapped is not None:
                raise mapped(str(exc)) from exc
            raise
        finally:
            if core_response is not None:
                core_response.close()

        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            content=content,
            extensions=core_response.extensions,
        )

    def close(self) -> None:
        self._pool.close()


def _response_headers(response) -> dict:
    """Headers as a plain lowercase dict, tolerating a response without any.

    Every real `httpx.Response` has `.headers`, so this looks like belt and
    braces — but it sits on the *error* path, and an `AttributeError` here would
    replace "GitHub rate-limited you until 14:32" with a stack trace. The guard
    costs nothing and protects the message that matters most.
    """
    raw = getattr(response, "headers", None) or {}
    try:
        return {str(k).lower(): str(v) for k, v in dict(raw).items()}
    except (TypeError, ValueError):
        return {}


def _rate_limit_hint(response) -> str:
    """The bit of a GitHub error body that says whether this is a rate limit.

    GitHub's **primary** rate limit is a `403`, not a `429`, and it is
    indistinguishable from an ordinary permission denial without reading the
    message. Getting this wrong means treating a ban as a 404 and carrying on.
    """
    if getattr(response, "status_code", 0) not in (403, 429):
        return ""
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("message") or "")[:200]
    except Exception:
        pass
    try:
        return (response.text or "")[:200]
    except Exception:
        return ""


def _get_checked(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = 30.0,
    max_bytes: Optional[int] = None,
) -> httpx.Response:
    """GET that follows redirects manually, re-running the SSRF guard per hop.

    ``httpx``'s ``follow_redirects=True`` validates only the initial URL, so a
    ``3xx`` to an internal address (``169.254.169.254``, ``127.0.0.1``, …) would
    still be connected to before any post-hoc host check. Following redirects by
    hand lets us re-validate every hop, closing that blind-SSRF gap.
    """
    from src.rate_limiter import OutboundRateLimited, host_of, outbound

    budget = _request_budget.get()
    token = _github_credentials()
    sent = dict(headers or {})
    sent.setdefault("User-Agent", _USER_AGENT)
    if token:
        sent.setdefault("Authorization", f"Bearer {token}")

    current = url
    for _ in range(_MAX_FETCH_REDIRECTS + 1):
        pinned_ips = _resolve_and_check_url(current)
        host = host_of(current)

        # Pace before the connection is opened, not after. A fresh TLS handshake
        # per request is deliberate here — it is what keeps the DNS pin honest
        # against a rebind — but 64 of them back to back is precisely the burst
        # shape abuse detection scores on, so the fix is spacing, not pooling.
        if budget is not None:
            budget.take()
        try:
            outbound.acquire(host, authenticated=bool(token))
        except OutboundRateLimited as e:
            raise SkillImportError(str(e)) from e

        with httpx.Client(
            transport=_PinnedTransport(pinned_ips, max_bytes=max_bytes),
            follow_redirects=False,
            timeout=timeout,
        ) as client:
            r = client.get(current, headers=sent)

        # Hand the response back so the next caller knows what this one learned.
        # A 200 clears the cooldown; a 403 carrying X-RateLimit-Reset sets one.
        outbound.observe(host, r.status_code, _response_headers(r), body_hint=_rate_limit_hint(r))

        if r.status_code in (301, 302, 303, 307, 308):
            location = r.headers.get("location")
            if not location:
                return r
            current = urljoin(str(r.url), location)
            continue
        return r
    raise SkillImportError("too many redirects while fetching skill bundle")


# `B926`. What skills.sh actually offers a person to copy. Its skill pages show
# `npx skills add https://github.com/<owner>/<repo> --skill <name>`, and the
# page's own address is `skills.sh/<owner>/<repo>/<name>`. Neither worked: the
# line has no scheme and was refused as "Only GitHub or skills.sh URLs", and
# the page answers 200 rather than redirecting to GitHub, which is the only
# thing the old skills.sh branch accepted. Both are read here, with no request
# to skills.sh at all — the owner, repository and skill name are in the text.
_INSTALL_LINE = re.compile(
    r"^\s*(?:npx|pnpx|bunx|pnpm\s+dlx|yarn\s+dlx)\s+(?:-y\s+|--yes\s+)?"
    r"skills(?:@\S+)?\s+(?:add|install|use)\s+(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_VALUED_FLAGS = {"--agent", "-a", "--dir", "--target"}
_REPO_SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})$")
_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _skill_name_or_error(name: str) -> str:
    name = (name or "").strip().strip("/")
    if name and not _SKILL_NAME.match(name):
        raise SkillImportError(f"“{name}” is not a skill name this importer can look up")
    return name


def _from_install_line(text: str) -> Optional[ResolvedSource]:
    """`npx skills add <repo> [--skill <name>]` → a source, or None if it is not one."""
    import shlex

    m = _INSTALL_LINE.match(text.replace("\\\n", " "))
    if not m:
        return None
    try:
        tokens = shlex.split(m.group("rest").replace("\\", " "))
    except ValueError as e:
        raise SkillImportError(f"could not read that install line: {e}") from e
    repo_ref, skill, i = None, "", 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("--skill", "-s") and i + 1 < len(tokens):
            skill, i = tokens[i + 1], i + 2
            continue
        if tok.startswith("--skill="):
            skill, i = tok.split("=", 1)[1], i + 1
            continue
        if tok in _VALUED_FLAGS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if repo_ref is None:
            repo_ref = tok
        i += 1
    if not repo_ref:
        raise SkillImportError("that install line names no repository")
    if "@" in repo_ref and not repo_ref.lower().startswith(("http://", "https://")):
        repo_ref, _, at_skill = repo_ref.partition("@")
        skill = skill or at_skill
    skill = _skill_name_or_error(skill)
    if repo_ref.lower().startswith(("http://", "https://", "github.com/", "www.github.com/")):
        src = parse_skill_source(repo_ref)
    else:
        bits = [b for b in repo_ref.split("/") if b]
        if len(bits) < 2 or not all(_REPO_SLUG.match(b) for b in bits[:2]):
            raise SkillImportError(f"“{repo_ref}” is not a GitHub owner/repository")
        src = ResolvedSource(owner=bits[0], repo=bits[1], ref="main", path="/".join(bits[2:]),
                             ref_known=False)
        if not skill and len(bits) >= 3 and not src.path.lower().endswith("skill.md"):
            skill, src.path = _skill_name_or_error(bits[-1]), "/".join(bits[2:-1])
    if skill and not src.path:
        src.skill = skill
    return src


def _from_skills_sh(parsed) -> ResolvedSource:
    """`skills.sh/<owner>/<repo>[/<skill>]` → a source, from the address alone."""
    bits = [b for b in parsed.path.split("/") if b]
    if len(bits) >= 2 and all(_REPO_SLUG.match(b) for b in bits[:2]):
        return ResolvedSource(owner=bits[0], repo=bits[1], ref="main", path="",
                              skill=_skill_name_or_error(bits[2]) if len(bits) >= 3 else "",
                              ref_known=False)
    raise SkillImportError(
        "That skills.sh page is not a skill. Open a skill on skills.sh and paste "
        "its page link, or the `npx skills add …` line it shows."
    )


def parse_skill_source(url: str) -> ResolvedSource:
    """Normalize skills.sh / GitHub web URLs into owner/repo/ref/path.

    `B926`: also a skills.sh page link and the `npx skills add` line skills.sh
    shows, which name a skill instead of a path (`ResolvedSource.skill`).
    """
    url = (url or "").strip()
    if not url:
        raise SkillImportError("URL is required")

    installed = _from_install_line(url)
    if installed is not None:
        return installed

    # ``urlparse`` only reports an unambiguous scheme when the URL carries the
    # ``scheme://`` form. Opaque schemes (``mailto:``, ``javascript:``) and a
    # schemeless ``host:port`` both parse a "scheme" that is not one, so they
    # fall through to the host check below and are rejected on the host instead.
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        if scheme and url.lower().startswith(f"{scheme}://"):
            raise SkillImportError(f"unsupported URL scheme: {scheme}")
        # Schemeless "github.com/owner/repo" — accept only a supported host.
        rough_host = (urlparse("//" + url).hostname or "").lower()
        if rough_host not in _GITHUB_HOSTS and rough_host not in _SKILLS_SH_HOSTS:
            raise SkillImportError("Only GitHub or skills.sh URLs are supported")
        url = "https://" + url

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname not in _GITHUB_HOSTS and hostname not in _SKILLS_SH_HOSTS:
        raise SkillImportError("Only GitHub or skills.sh URLs are supported")

    # A skills.sh link is only usable if it redirects to an exact supported
    # GitHub host. Scraping the page body for a github.com link cannot work:
    # skill pages only ever link the repository root, never the skill's
    # subdirectory, so the scrape resolves every skill in a repo to the same
    # (wrong) bundle. Fail with an actionable message instead.
    if hostname in _SKILLS_SH_HOSTS:
        # `B926`: a skills.sh page's address is `/<owner>/<repo>/<skill>`, so it
        # names the skill itself and nothing on skills.sh is fetched. A link of
        # one segment is a short link, and keeps being unwrapped by following
        # its redirect, as below; a link of none is not a skill.
        segments = [b for b in parsed.path.split("/") if b]
        if len(segments) != 1:
            return _from_skills_sh(parsed)
    if hostname in _SKILLS_SH_HOSTS:
        r = _get_checked(url, timeout=20.0)
        if r.status_code >= 400:
            raise _github_response_error(r)
        final = str(r.url)
        if _github_host(final) not in _GITHUB_HOSTS:
            raise SkillImportError(
                "skills.sh did not redirect to GitHub — open the skill's "
                "repository on GitHub, navigate to the exact skill folder or "
                "SKILL.md file, and paste that URL; the repository-root link "
                "alone is not sufficient"
            )
        url = final

    # Update parsed and hostname to reflect the new GitHub URL
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    _assert_github_url(url)

    if hostname == "raw.githubusercontent.com":
        # /owner/repo/ref/path/to/file
        bits = [p for p in parsed.path.split("/") if p]
        if len(bits) < 4:
            raise SkillImportError("Invalid raw GitHub URL")
        owner, repo, ref = bits[0], bits[1], bits[2]
        path = "/".join(bits[3:])
        return ResolvedSource(owner=owner, repo=repo, ref=ref, path=path)

    bits = [p for p in parsed.path.split("/") if p]
    if len(bits) < 2:
        raise SkillImportError("Invalid GitHub URL")
    owner, repo = bits[0], bits[1]
    ref = "main"
    path = ""

    if len(bits) >= 4 and bits[2] in ("tree", "blob"):
        ref = bits[3]
        path = "/".join(bits[4:])
    elif len(bits) == 2:
        # A bare repository names no branch (`B926`): `main`, then `master`.
        return ResolvedSource(owner=owner, repo=repo.removesuffix(".git"), ref=ref, path="",
                              ref_known=False)
    else:
        raise SkillImportError("GitHub URL must include /tree/<branch>/... or /blob/<branch>/...")

    return ResolvedSource(owner=owner, repo=repo, ref=ref, path=path)


def _raw_url(src: ResolvedSource, rel_path: str) -> str:
    rel = _safe_relpath(rel_path)
    return f"https://raw.githubusercontent.com/{src.owner}/{src.repo}/{quote(src.ref, safe='')}/{quote(rel, safe='/')}"


def _api_contents_url(src: ResolvedSource, rel_path: str = "") -> str:
    rel = _safe_relpath(rel_path) if rel_path else ""
    base = f"https://api.github.com/repos/{src.owner}/{src.repo}/contents"
    if rel:
        base += f"/{quote(rel, safe='/')}"
    return f"{base}?ref={quote(src.ref, safe='')}"


def _github_response_error(response: httpx.Response) -> SkillImportError:
    """Turn a failed GitHub HTTP response into a user-visible import error."""
    status = response.status_code
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or "").strip()
    except Exception:
        detail = (response.text or "").strip()[:200]

    low = detail.lower()
    if status == 403 and ("rate limit" in low or "abuse" in low):
        # "try again in a bit" was the old text. GitHub tells us exactly when in
        # X-RateLimit-Reset, so say it — a person who knows the number waits,
        # and a person who does not clicks again and deepens the ban.
        from src.rate_limiter import parse_reset_header, parse_retry_after

        hdrs = _response_headers(response)
        wait = parse_retry_after(hdrs.get("retry-after"))
        if wait is None:
            wait = parse_reset_header(hdrs.get("x-ratelimit-reset"))
        when = ""
        if wait:
            when = (
                f" — wait {wait:.0f} seconds"
                if wait < 90
                else f" — wait about {wait / 60:.0f} minutes"
            )
        authed = " Set a GitHub token in Settings to raise the limit from 60 to 5,000 an hour." if not _github_credentials() else ""
        return SkillImportError(
            f"GitHub rate limit reached{when}. Pantheon has stopped calling GitHub until then, "
            f"which is what lets the limit expire.{authed}"
            + (f" ({detail})" if detail else "")
        )
    if status == 404:
        return SkillImportError("path not found on GitHub")
    if detail:
        return SkillImportError(f"GitHub request failed ({status}): {detail}")
    return SkillImportError(f"GitHub request failed ({status})")


def _fetch_bytes(url: str) -> bytes:
    r = _get_checked(url, headers={"Accept": "application/vnd.github+json"}, timeout=30.0)
    if r.status_code >= 400:
        raise _github_response_error(r)
    _assert_github_url(str(r.url), context="redirect target")
    if len(r.content) > MAX_FILE_BYTES:
        raise SkillImportError(f"file too large: {url}")
    return r.content


def _fetch_text(url: str) -> str:
    data = _fetch_bytes(url)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SkillImportError(f"non-text file: {url}") from e


def _list_github_dir(src: ResolvedSource, rel_dir: str, out: Dict[str, str], *, depth: int = 0,
                     notes: Optional[List[str]] = None) -> None:
    if depth > 4 or len(out) >= MAX_FILES:
        return
    url = _api_contents_url(src, rel_dir)
    r = _get_checked(url, headers={"Accept": "application/vnd.github+json"}, timeout=30.0)
    if r.status_code >= 400:
        raise _github_response_error(r)
    _assert_github_url(str(r.url), context="redirect target")
    entries = r.json()
    if not isinstance(entries, list):
        raise SkillImportError("expected a directory on GitHub")
    total = sum(len(v.encode("utf-8")) for v in out.values())
    for ent in entries:
        if len(out) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            break
        if not isinstance(ent, dict):
            continue
        name = ent.get("name") or ""
        ent_type = ent.get("type")
        rel = _safe_relpath(f"{rel_dir}/{name}" if rel_dir else name)
        if ent_type == "dir":
            if name in ("node_modules", ".git"):
                continue
            _list_github_dir(src, rel, out, depth=depth + 1, notes=notes)
            total = sum(len(v.encode("utf-8")) for v in out.values())
            continue
        if ent_type != "file" or not _is_text_file(name):
            continue
        if name.lower() in _SKIPPED_NAMES:
            if notes is not None:
                notes.append(f"Left out {rel}: a dependency lockfile, not part of the skill.")
            continue
        size = ent.get("size")
        if isinstance(size, int) and size > MAX_FILE_BYTES:
            # `B926`: one big file no longer sinks the import. It is left out,
            # and the person is told which and why.
            if notes is not None:
                notes.append(f"Left out {rel}: {size:,} bytes, over the {MAX_FILE_BYTES:,}-byte "
                             "limit for one file.")
            continue
        dl = ent.get("download_url")
        if not dl:
            continue
        _assert_github_url(dl, context="download URL")
        try:
            text = _fetch_text(dl)
        except SkillImportError as e:
            if "too large" not in str(e):
                raise
            if notes is not None:
                notes.append(f"Left out {rel}: over the {MAX_FILE_BYTES:,}-byte limit for one file.")
            continue
        if total + len(text.encode("utf-8")) > MAX_TOTAL_BYTES:
            if notes is not None:
                notes.append(f"Stopped at {len(out)} files: the skill's files passed the "
                             f"{MAX_TOTAL_BYTES:,}-byte limit for one import, so the rest were left out.")
            return
        total += len(text.encode("utf-8"))
        out[rel] = text


def fetch_skill_bundle(url: str) -> Tuple[Dict[str, str], ResolvedSource]:
    """Download SKILL.md and sibling text assets. Returns relative_path → content.

    The two-value form every existing caller uses (`Law 1`). `B926`:
    `fetch_skill_bundle_report` is the same fetch and also says what it could
    not bring, which the import route shows the person.
    """
    files, src, _notes = fetch_skill_bundle_report(url)
    return files, src


def fetch_skill_bundle_report(url: str) -> Tuple[Dict[str, str], ResolvedSource, List[str]]:
    """Download SKILL.md and sibling text assets, and say what was left behind.

    Returns ``(files, source, notes)``: relative_path → content, the resolved
    GitHub source, and one plain sentence per thing the import could not fetch
    but did not need (a folder that could not be listed, so only SKILL.md came).

    Every request made under here is paced by the shared outbound limiter and
    counted against one budget, so a single import cannot spend an hour's worth
    of GitHub quota — which is what it did before 2026-08-31, when it earned the
    owner a soft ban walking a repository tree at wire speed.
    """
    authed = bool(_github_credentials())
    budget = _Budget(
        MAX_REQUESTS_AUTHENTICATED if authed else MAX_REQUESTS_UNAUTHENTICATED,
        authed,
    )
    token = _request_budget.set(budget)
    notes: List[str] = []
    try:
        # parse_skill_source can itself make a request — a skills.sh link is
        # resolved by following its redirect — so it has to be inside the budget
        # or the first call of every import is untracked and unpaced.
        src = parse_skill_source(url)
        files, src = _fetch_skill_bundle_inner(url, src, {}, notes)
        return files, src, notes
    finally:
        _request_budget.reset(token)


def _listing_note(err: Exception) -> str:
    text = str(err)
    if "rate-limit" in text.lower() or "rate limit" in text.lower():
        # GitHub's own sentence is long and addressed to a developer. Say what
        # happened and the one thing that lifts it.
        wait = re.search(r"not retrying for (\d+ minutes?)", text)
        return ("Only SKILL.md was imported: GitHub allows 60 folder lookups an hour "
                "without a token, and this server has used them"
                + (f" (it resets in {wait.group(1)})" if wait else "")
                + ". Import the skill again later for its other files, or set "
                "PANTHEON_GITHUB_TOKEN so imports can list whole folders.")
    return f"Only SKILL.md was imported. The folder's other files could not be listed: {text}"


def _fetch_skill_bundle_inner(
    url: str, src: ResolvedSource, files: Dict[str, str],
    notes: Optional[List[str]] = None,
) -> Tuple[Dict[str, str], ResolvedSource]:
    notes = notes if notes is not None else []

    if not src.path:
        _locate_named_skill(src)

    path = _safe_relpath(src.path) if src.path else ""
    if path.lower().endswith("skill.md"):
        files[path] = _fetch_text(_raw_url(src, path))
        parent = "/".join(path.split("/")[:-1])
        if parent:
            try:
                _list_github_dir(src, parent, files, notes=notes)
            except SkillImportError as e:
                notes.append(_listing_note(e))
        return files, src

    if path:
        # `B926`. SKILL.md comes from raw.githubusercontent.com; listing the
        # folder's other files needs api.github.com, which allows 60 requests
        # an hour without a token and is the first thing to run out. The
        # SKILL.md fetched here used to be thrown away, and a listing that
        # failed sent the import on to two more readings of the same path —
        # the last of which listed the folder again and failed the whole
        # import with the rate-limit sentence. A skill whose SKILL.md arrived
        # is imported; what could not be listed is said, not hidden.
        skill_md = None
        try:
            skill_md = _fetch_text(_raw_url(src, f"{path}/SKILL.md"))
        except Exception:
            skill_md = None
        if skill_md is not None:
            files[f"{path}/SKILL.md"] = skill_md
            try:
                _list_github_dir(src, path, files, notes=notes)
            except SkillImportError as e:
                notes.append(_listing_note(e))
            return files, src
        try:
            text = _fetch_text(_raw_url(src, path))
            if path.lower().endswith(".md"):
                files[path] = text
                return files, src
        except Exception:
            pass
        _list_github_dir(src, path, files, notes=notes)
    else:
        # A repository that is itself one skill (`_locate_named_skill` found
        # its root SKILL.md). The same rule as a folder: SKILL.md first, and a
        # listing that fails is a note, not a failed import.
        files["SKILL.md"] = _fetch_text(_raw_url(src, "SKILL.md"))
        try:
            _list_github_dir(src, "", files, notes=notes)
        except SkillImportError as e:
            notes.append(_listing_note(e))
        return files, src

    if not any(p.lower().endswith("skill.md") for p in files):
        # Flat repo root with SKILL.md only
        try:
            files["SKILL.md"] = _fetch_text(_raw_url(src, "SKILL.md"))
        except Exception as e:
            raise SkillImportError(
                "No SKILL.md found — link to a skill folder or SKILL.md on GitHub"
            ) from e
    return files, src


# Where a repository keeps a named skill, in the order they are tried. The
# layouts of the repositories skills.sh lists: `skills/<name>` (anthropics,
# vercel-labs), `<name>` at the root, and the agent-tool folders.
_SKILL_DIR_CANDIDATES = ("skills/{name}", "{name}", ".claude/skills/{name}",
                         ".agents/skills/{name}", "skills/.curated/{name}")


def _raw_exists(src: ResolvedSource, rel: str) -> bool:
    try:
        r = _get_checked(_raw_url(src, rel), timeout=20.0)
    except SkillImportError:
        raise
    return r.status_code == 200


def _find_skill_in_tree(src: ResolvedSource, refs: List[str]) -> Optional[Tuple[str, str]]:
    """`(folder, ref)` of `<anything>/<skill>/SKILL.md` in the repo, or None.

    One `git/trees?recursive=1` request per branch tried. A rate-limited API
    is an error the person is told about, not a silent "not found".
    """
    want = src.skill.lower()
    for ref in refs:
        url = (f"https://api.github.com/repos/{quote(src.owner, safe='')}/"
               f"{quote(src.repo, safe='')}/git/trees/{quote(ref, safe='')}?recursive=1")
        r = _get_checked(url, headers={"Accept": "application/vnd.github+json"}, timeout=30.0)
        if r.status_code == 404:
            continue
        if r.status_code >= 400:
            raise _github_response_error(r)
        try:
            tree = r.json().get("tree") or []
        except Exception:
            continue
        folders = sorted(
            (e.get("path") or "")[: -len("/SKILL.md")]
            for e in tree
            if isinstance(e, dict) and e.get("type") == "blob"
            and (e.get("path") or "").endswith("/SKILL.md")
        )
        hits = [f for f in folders if f.split("/")[-1].lower() == want]
        if hits:
            return min(hits, key=len), ref
        # `B928`. The name `npx skills add … --skill <name>` takes is the one
        # the skill's SKILL.md gives itself, and its folder need not share it:
        # `Leonxlnx/taste-skill` keeps `design-taste-frontend` in
        # `skills/taste-skill/`. Read the names — raw files, not the API —
        # before saying the skill is not there.
        src.ref = ref
        for folder in folders[:_NAME_SCAN_LIMIT]:
            try:
                head = _fetch_text(_raw_url(src, f"{folder}/SKILL.md"))
            except SkillImportError:
                continue
            if _frontmatter_name(head).lower() == want:
                return folder, ref
    return None


# How many SKILL.md files `_find_skill_in_tree` will read to match a name.
_NAME_SCAN_LIMIT = 60


def _frontmatter_name(text: str) -> str:
    """The `name:` a SKILL.md gives itself, or "" — never raises."""
    try:
        from .skill_format import parse_frontmatter

        fm, _body = parse_frontmatter(text or "")
        return str((fm or {}).get("name") or "").strip()
    except Exception:
        return ""


def _locate_named_skill(src: ResolvedSource) -> None:
    """Point `src.path` at the named skill's folder, or at a root SKILL.md.

    `B926`. Raw files only — raw.githubusercontent.com is not the 60-an-hour
    API — so finding the folder costs a handful of paced requests and no
    listing. A repository link with no skill named is imported only when the
    repository is itself one skill; walking a whole repository of skills to
    pick one was how the old path imported the wrong skill or ran out of budget.
    """
    refs = [src.ref] if src.ref_known else ["main", "master"]
    if src.skill:
        for ref in refs:
            src.ref = ref
            for pattern in _SKILL_DIR_CANDIDATES:
                folder = pattern.format(name=src.skill)
                if _raw_exists(src, f"{folder}/SKILL.md"):
                    src.path, src.ref_known = folder, True
                    return
        # Not in a usual place: ask GitHub for the repository's file list
        # once (one API request, however large the tree) and look for a
        # folder of that name holding a SKILL.md.
        try:
            found = _find_skill_in_tree(src, refs)
        except SkillImportError as e:
            if "rate-limit" not in str(e).lower() and "rate limit" not in str(e).lower():
                raise
            wait = re.search(r"not retrying for (\d+ minutes?)", str(e))
            raise SkillImportError(
                f"“{src.skill}” is not in the usual folders of {src.owner}/{src.repo}, and "
                "looking through the whole repository needs GitHub's API, which has "
                "rate-limited this server" + (f" for {wait.group(1)}" if wait else "")
                + ". Try again then, set PANTHEON_GITHUB_TOKEN, or paste the GitHub link "
                "to the skill's own folder."
            ) from e
        if found:
            src.path, src.ref, src.ref_known = found[0], found[1], True
            return
        raise SkillImportError(
            f"Couldn't find a skill called “{src.skill}” in {src.owner}/{src.repo}. "
            "Open the skill's folder on GitHub and paste that link instead."
        )
    for ref in refs:
        src.ref = ref
        if _raw_exists(src, "SKILL.md"):
            src.ref_known = True
            return
    # A one-skill repository usually names the skill after itself
    # (`vercel-labs/agent-browser` keeps `skills/agent-browser/SKILL.md`).
    for ref in refs:
        src.ref = ref
        for pattern in _SKILL_DIR_CANDIDATES[:1] + _SKILL_DIR_CANDIDATES[2:]:
            folder = pattern.format(name=src.repo)
            if _raw_exists(src, f"{folder}/SKILL.md"):
                src.path, src.ref_known = folder, True
                return
    raise SkillImportError(
        f"{src.owner}/{src.repo} is a whole repository, not one skill. Paste a skill's "
        "skills.sh page, its `npx skills add … --skill <name>` line, or the GitHub "
        "link to the skill's own folder."
    )


def pick_skill_md(files: Dict[str, str]) -> Tuple[str, str]:
    for rel, content in files.items():
        if rel.lower().endswith("skill.md"):
            return rel, content
    raise SkillImportError("bundle has no SKILL.md")


def default_category_from_source(src: ResolvedSource) -> str:
    return "imported"



# ── Whole packages — `P8-49` ────────────────────────────────────────────────
#
# The owner, 2026-09-30: *"adding a multi-layer skill package also does not
# build its segmented 'category' and group skills together... Which it
# should."* Asked what importing a repository that holds many skills should
# do, he chose **the whole package, even when `--skill` names one**
# (`D-2026-09-30-01`).
#
# One request brings the whole repository: GitHub's archive of it, from
# codeload.github.com, which is not the 60-an-hour API. That is also what
# `npx skills` does in effect — it clones — and it is the difference between
# one paced request and one per file. Nothing in the archive is written to
# disk from here: the members this module wants are read into memory by
# repository path, every path goes through `_safe_relpath`, only regular files
# are read (no links, no devices), and the byte and count caps below hold at
# every step. The writer is `SkillsManager.install_package`, which applies
# `_safe_relpath` again on the way to disk.

MAX_ARCHIVE_BYTES = 100_000_000      # the download, compressed
MAX_ARCHIVE_UNPACKED = 500_000_000   # how far into the unpacked stream we read
MAX_PACKAGE_SKILLS = 100
MAX_PACKAGE_BYTES = 40_000_000       # text kept across every skill of one package
# A package import makes: a skills.sh short link's redirect (rare), then one
# archive request per branch tried. Everything else is read out of the archive.
MAX_PACKAGE_REQUESTS = 8
_MAX_NOTES = 20

_MARKETPLACE = ".claude-plugin/marketplace.json"
_PLUGIN = ".claude-plugin/plugin.json"
# `<anything>/skills/<name>/SKILL.md` is where every agent tool keeps skills
# (`skills/`, `.claude/skills/`, `.agents/skills/`, a plugin's own
# `skills/`), and `skills/.curated|.experimental|.system/` is the layout of
# the agent-skills catalogues.
_SKILLS_PARENT = re.compile(r"(^|/)skills(/\.[a-z]+)?$")


def package_id(owner: str, repo: str) -> str:
    """`owner--repo`, lower-cased. GitHub never allows `--` in an owner name,
    so the id splits back one way only, and it is a safe path segment."""
    return f"{owner}--{repo}".lower()


@dataclass
class PackageSkill:
    folder: str                 # the skill's folder in the repository; "" is the root
    name: str                   # the name its SKILL.md gives itself, else its folder's
    files: Dict[str, str]       # path relative to `folder` → text
    section: str = ""           # `PackageSection.id`


@dataclass
class PackageSection:
    id: str
    title: str
    description: str = ""
    folders: List[str] = field(default_factory=list)


@dataclass
class FetchedPackage:
    src: ResolvedSource
    title: str
    description: str = ""
    version: str = ""
    commit: str = ""
    skills: List[PackageSkill] = field(default_factory=list)
    sections: List[PackageSection] = field(default_factory=list)
    named: str = ""             # folder of the skill the link named, when it named one
    notes: List[str] = field(default_factory=list)
    partial: bool = False       # a link to one skill's folder, not to the package

    @property
    def id(self) -> str:
        return package_id(self.src.owner, self.src.repo)

    @property
    def source_url(self) -> str:
        return f"https://github.com/{self.src.owner}/{self.src.repo}"


def _note(notes: List[str], text: str) -> None:
    if len(notes) < _MAX_NOTES:
        notes.append(text)
    elif len(notes) == _MAX_NOTES:
        notes.append("More files were left out than are listed here.")


class _Archive:
    """A repository archive, held compressed and read by walking it.

    Two walks at most: one for the list of files and their sizes, one for the
    handful of files an import keeps. Seeking inside a gzip stream restarts it
    from the top, so a walk per wanted file would be quadratic.
    """

    def __init__(self, data: bytes):
        self.data = data
        self.sizes: Dict[str, int] = {}
        self.commit = ""
        self._walk(None)

    def _walk(self, want: Optional[set]) -> Dict[str, str]:
        import io
        import tarfile
        import zlib

        out: Dict[str, str] = {}
        root: Optional[str] = None
        try:
            with tarfile.open(fileobj=io.BytesIO(self.data), mode="r|gz") as tar:
                for m in tar:
                    if not self.commit:
                        # GitHub's archives carry the commit in a pax global header.
                        self.commit = str((tar.pax_headers or {}).get("comment") or "")[:64]
                    size = max(int(m.size or 0), 0)
                    if m.offset_data + size > MAX_ARCHIVE_UNPACKED:
                        raise SkillImportError(
                            f"the repository unpacks to more than "
                            f"{MAX_ARCHIVE_UNPACKED // 1_000_000} MB. Paste the GitHub link to "
                            "one skill's folder instead — that imports just that skill.")
                    if not m.isfile():
                        continue
                    first, _, rest = m.name.partition("/")
                    if root is None:
                        root = first
                    if first != root or not rest:
                        continue
                    try:
                        rel = _safe_relpath(rest)
                    except SkillImportError:
                        continue
                    if any(p in ("node_modules", ".git") for p in rel.split("/")):
                        continue
                    if want is None:
                        self.sizes[rel] = size
                        continue
                    if rel not in want or size > MAX_FILE_BYTES:
                        continue
                    fh = tar.extractfile(m)
                    if fh is None:
                        continue
                    raw = fh.read(MAX_FILE_BYTES + 1)
                    if len(raw) > MAX_FILE_BYTES:
                        continue
                    try:
                        out[rel] = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
        except SkillImportError:
            raise
        except (tarfile.TarError, EOFError, OSError, zlib.error) as e:
            raise SkillImportError(
                f"GitHub's archive of this repository could not be read ({type(e).__name__}: {e})"
            ) from e
        return out

    def read(self, paths: Iterable[str]) -> Dict[str, str]:
        want = {p for p in paths if p in self.sizes}
        return self._walk(want) if want else {}


def _fetch_archive(src: ResolvedSource) -> _Archive:
    refs = [src.ref] if src.ref_known else ["main", "master"]
    for ref in refs:
        url = (f"https://codeload.github.com/{quote(src.owner, safe='')}/"
               f"{quote(src.repo, safe='')}/tar.gz/{quote(ref, safe='/')}")
        try:
            r = _get_checked(url, timeout=120.0, max_bytes=MAX_ARCHIVE_BYTES)
        except SkillImportError as e:
            if "download larger than" not in str(e):
                raise
            raise SkillImportError(
                f"{src.owner}/{src.repo} is larger than {MAX_ARCHIVE_BYTES // 1_000_000} MB, more "
                "than a whole-package import downloads. Paste the GitHub link to one skill's "
                "folder instead — that imports just that skill."
            ) from e
        if r.status_code == 404:
            continue
        if r.status_code >= 400:
            raise _github_response_error(r)
        _assert_github_url(str(r.url), context="redirect target")
        src.ref, src.ref_known = ref, True
        return _Archive(r.content)
    raise SkillImportError(
        f"GitHub has no {src.owner}/{src.repo} with a "
        + " or ".join(f"`{r}`" for r in refs)
        + " branch that this server can see. Check the link — a private repository "
        "cannot be imported — or paste the link to the branch you want (…/tree/<branch>)."
    )


def _json_object(text: Optional[str]) -> dict:
    try:
        value = json.loads(text or "")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _join_folder(base: str, rel: str) -> Optional[str]:
    parts: List[str] = []
    for p in f"{base}/{rel}".replace("\\", "/").split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            return None
        parts.append(p)
    return "/".join(parts)


def _parent(folder: str) -> str:
    return folder.rsplit("/", 1)[0] if "/" in folder else ""


def _choose_folders(folders: List[str], declared: List[str]) -> List[str]:
    """Which folders holding a SKILL.md are the package's skills.

    What the package declares, the conventional `…/skills/<name>/` folders and
    a root SKILL.md, in that order. Only when there are none of those does a
    folder at the top level count, and only when there are none of *those* does
    any folder at all — which is what keeps `anthropics/skills`' `template/`
    out of it, and a repository of loose skills importable.
    """
    chosen = list(declared)
    for f in folders:
        if f not in chosen and (f == "" or _SKILLS_PARENT.search(_parent(f))):
            chosen.append(f)
    if chosen:
        return chosen
    top = [f for f in folders if f and "/" not in f]
    return top or [f for f in folders if f.count("/") < 6]


def _discover_package(arc: _Archive, src: ResolvedSource, *, named_skill: str = "",
                      only_folders: Optional[Iterable[str]] = None) -> FetchedPackage:
    from .skill_format import slugify

    notes: List[str] = []
    md_path = {}
    for p in sorted(arc.sizes):
        if p.rsplit("/", 1)[-1].lower() == "skill.md":
            md_path.setdefault(_parent(p) if "/" in p else "", p)
    folders = sorted(md_path)

    meta = arc.read([p for p in (_MARKETPLACE, _PLUGIN) if p in arc.sizes])
    market, plugin = _json_object(meta.get(_MARKETPLACE)), _json_object(meta.get(_PLUGIN))
    mdata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
    title = (str(market.get("name") or plugin.get("name") or src.repo).strip() or src.repo)[:80]
    description = str(plugin.get("description") or mdata.get("description")
                      or market.get("description") or "").strip()[:500]
    version = str(plugin.get("version") or mdata.get("version") or "").strip()[:40]

    # The sections a marketplace declares: `anthropics/skills` splits into
    # document-skills, example-skills, claude-api and more.
    sections: List[PackageSection] = []
    declared: List[str] = []
    plugins = market.get("plugins") if isinstance(market.get("plugins"), list) else []
    for pl in plugins:
        if not isinstance(pl, dict):
            continue
        base = _join_folder("", pl.get("source") if isinstance(pl.get("source"), str) else "") or ""
        listed: List[str] = []
        if isinstance(pl.get("skills"), list):
            for item in pl["skills"]:
                f = _join_folder(base, item) if isinstance(item, str) else None
                if f is not None and f in md_path and f not in listed and f not in declared:
                    listed.append(f)
        elif base:
            listed = [f for f in folders
                      if (f == base or f.startswith(base + "/")) and f not in declared]
        if listed:
            st = (str(pl.get("name") or "").strip() or title)[:80]
            sections.append(PackageSection(
                id=slugify(st, fallback="section"), title=st,
                description=str(pl.get("description") or "").strip()[:300], folders=listed))
            declared.extend(listed)

    chosen = _choose_folders(folders, declared)

    named = ""
    if named_skill:
        want = named_skill.lower()
        by_folder = [f for f in folders if (f.rsplit("/", 1)[-1] if f else src.repo).lower() == want]
        if not by_folder:
            heads = arc.read([md_path[f] for f in folders])
            by_folder = [f for f in folders if _frontmatter_name(heads.get(md_path[f], "")).lower() == want]
        if by_folder:
            named = min(by_folder, key=len)
            if named not in chosen:
                chosen.append(named)
        else:
            _note(notes, f"{src.owner}/{src.repo} has no skill called “{named_skill}”, so the "
                         "whole package was imported without it.")

    if only_folders is not None:
        keep = list(dict.fromkeys(only_folders))
        for f in keep:
            if f not in md_path:
                _note(notes, f"{f or 'The root skill'} is no longer in {src.owner}/{src.repo}; "
                             "the copy here was left as it is.")
        chosen = [f for f in keep if f in md_path]

    if len(chosen) > MAX_PACKAGE_SKILLS:
        _note(notes, f"{src.owner}/{src.repo} holds {len(chosen)} skills; the first "
                     f"{MAX_PACKAGE_SKILLS} were imported.")
        chosen = chosen[:MAX_PACKAGE_SKILLS]
    if not chosen:
        raise SkillImportError(
            f"{src.owner}/{src.repo} has no SKILL.md in it, so there is no skill to import.")

    # Every file belongs to the deepest chosen folder above it, so a skill
    # nested inside another keeps its own files.
    chosen_set = set(chosen)

    def _home(path: str) -> Optional[str]:
        cur = _parent(path)
        while True:
            if cur in chosen_set:
                return cur
            if not cur:
                return None
            cur = _parent(cur)

    wanted: Dict[str, List[str]] = {f: [] for f in chosen}
    per_count: Dict[str, int] = {f: 0 for f in chosen}
    per_bytes: Dict[str, int] = {f: 0 for f in chosen}
    package_bytes = 0
    # SKILL.md first, so a cap never costs a skill its procedure.
    order = sorted(arc.sizes, key=lambda p: (p.rsplit("/", 1)[-1].lower() != "skill.md", p))
    for path in order:
        home = _home(path)
        if home is None:
            continue
        name = path.rsplit("/", 1)[-1]
        rel = path[len(home) + 1:] if home else path
        size = arc.sizes[path]
        if not _is_text_file(name):
            continue
        if name.lower() in _SKIPPED_NAMES:
            _note(notes, f"Left out {path}: a dependency lockfile, not part of the skill.")
            continue
        if size > MAX_FILE_BYTES:
            _note(notes, f"Left out {path}: {size:,} bytes, over the {MAX_FILE_BYTES:,}-byte "
                         "limit for one file.")
            continue
        if rel.lower() != "skill.md" and (per_count[home] >= MAX_FILES
                                          or per_bytes[home] + size > MAX_TOTAL_BYTES):
            _note(notes, f"Left out {path}: its skill reached the limit of {MAX_FILES} files "
                         f"or {MAX_TOTAL_BYTES:,} bytes.")
            continue
        if package_bytes + size > MAX_PACKAGE_BYTES:
            _note(notes, f"Left out {path}: the package passed the {MAX_PACKAGE_BYTES:,}-byte "
                         "limit for one import.")
            continue
        wanted[home].append(path)
        per_count[home] += 1
        per_bytes[home] += size
        package_bytes += size

    texts = arc.read(p for paths in wanted.values() for p in paths)
    section_of = {f: s.id for s in sections for f in s.folders}
    rest_id = slugify(title, fallback="skills")
    skills: List[PackageSkill] = []
    for folder in chosen:
        md = texts.get(md_path[folder])
        if md is None:
            _note(notes, f"Left out {folder or 'the root skill'}: its SKILL.md could not be read.")
            continue
        files = {}
        for path in wanted[folder]:
            if path in texts:
                files[path[len(folder) + 1:] if folder else path] = texts[path]
        name = _frontmatter_name(md) or (folder.rsplit("/", 1)[-1] if folder else src.repo)
        skills.append(PackageSkill(folder=folder, name=name, files=files,
                                   section=section_of.get(folder, rest_id)))
    if not skills:
        raise SkillImportError(f"none of the skills in {src.owner}/{src.repo} could be read.")

    present = {s.folder for s in skills}
    sections = [PackageSection(s.id, s.title, s.description, [f for f in s.folders if f in present])
                for s in sections]
    sections = [s for s in sections if s.folders]
    rest = [s.folder for s in skills if s.section == rest_id and s.folder not in section_of]
    if rest:
        sections.append(PackageSection(id=rest_id, title=title, description=description,
                                       folders=rest))
    return FetchedPackage(src=src, title=title, description=description, version=version,
                          commit=arc.commit, skills=skills, sections=sections,
                          named=named if named in present else "", notes=notes,
                          partial=only_folders is not None)


def is_package_link(url: str) -> bool:
    """True when the text names a repository or a skill by name — the forms
    that import the whole package — rather than one folder or file in it.

    No request is made. A one-segment skills.sh short link is resolved by
    following its redirect, so it is left to the single-skill path it has
    always taken.
    """
    text = (url or "").strip()
    if _INSTALL_LINE.match(text.replace("\\\n", " ")):
        return True
    rough = urlparse(text if "://" in text else "https://" + text)
    host = (rough.hostname or "").lower()
    if host in _SKILLS_SH_HOSTS:
        return len([b for b in rough.path.split("/") if b]) >= 2
    if host not in _GITHUB_HOSTS or host in ("raw.githubusercontent.com", "codeload.github.com"):
        return False
    try:
        return not parse_skill_source(text).path
    except SkillImportError:
        return False


def fetch_skill_package(url: str, *, only_folders: Optional[Iterable[str]] = None) -> FetchedPackage:
    """Every skill in the repository a link names, with its sections.

    `only_folders` narrows it to those folders — a package that was imported
    one skill at a time is refreshed one skill at a time.
    """
    budget = _Budget(MAX_PACKAGE_REQUESTS, bool(_github_credentials()))
    token = _request_budget.set(budget)
    try:
        src = parse_skill_source(url)
        named, src.path = src.skill, ""
        return _discover_package(_fetch_archive(src), src, named_skill=named,
                                 only_folders=only_folders)
    finally:
        _request_budget.reset(token)


def single_skill_package(files: Dict[str, str], src: ResolvedSource,
                         notes: Optional[List[str]] = None) -> FetchedPackage:
    """One skill fetched by its folder link, as a package of one.

    So a skill imported on its own is still filed under the repository it
    came from, and importing the rest of that repository later joins it.
    """
    from .skill_format import slugify

    rel, md = pick_skill_md(files)
    folder = _parent(rel) if "/" in rel else ""
    prefix = f"{folder}/" if folder else ""
    own = {(k[len(prefix):] if prefix and k.startswith(prefix) else k): v for k, v in files.items()}
    name = _frontmatter_name(md) or (folder.rsplit("/", 1)[-1] if folder else src.repo)
    section = PackageSection(id=slugify(src.repo, fallback="skills"), title=src.repo, folders=[folder])
    return FetchedPackage(src=src, title=src.repo, skills=[PackageSkill(folder, name, own, section.id)],
                          sections=[section], named=folder, notes=list(notes or []), partial=True)
