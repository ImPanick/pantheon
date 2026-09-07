# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import SKILL.md bundles from public GitHub (or skills.sh → GitHub) URLs."""
from __future__ import annotations

import ipaddress
import logging
import os
import time
from dataclasses import dataclass
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

MAX_FILES = 64
MAX_TOTAL_BYTES = 2_000_000
MAX_FILE_BYTES = 400_000
ALLOWED_SUFFIXES = (
    ".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".toml",
    ".js", ".ts", ".css", ".html", ".xml", ".csv",
)
TEXT_NAMES = {"skill.md", "license", "license.md", "readme.md"}
_GITHUB_HOSTS = frozenset({
    "github.com", "www.github.com", "api.github.com", "raw.githubusercontent.com",
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

    def __init__(self, ips: List[ipaddress._BaseAddress]):
        self._pinned_ips = list(ips)
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
            content = b"".join(cast(Iterable[bytes], core_response.stream))
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
            transport=_PinnedTransport(pinned_ips),
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


def parse_skill_source(url: str) -> ResolvedSource:
    """Normalize skills.sh / GitHub web URLs into owner/repo/ref/path."""
    url = (url or "").strip()
    if not url:
        raise SkillImportError("URL is required")

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
        path = ""
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


def _list_github_dir(src: ResolvedSource, rel_dir: str, out: Dict[str, str], *, depth: int = 0) -> None:
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
            _list_github_dir(src, rel, out, depth=depth + 1)
            total = sum(len(v.encode("utf-8")) for v in out.values())
            continue
        if ent_type != "file" or not _is_text_file(name):
            continue
        dl = ent.get("download_url")
        if not dl:
            continue
        _assert_github_url(dl, context="download URL")
        text = _fetch_text(dl)
        total += len(text.encode("utf-8"))
        if total > MAX_TOTAL_BYTES:
            raise SkillImportError("skill bundle exceeds size limit")
        out[rel] = text


def fetch_skill_bundle(url: str) -> Tuple[Dict[str, str], ResolvedSource]:
    """Download SKILL.md and sibling text assets. Returns relative_path → content.

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
    try:
        # parse_skill_source can itself make a request — a skills.sh link is
        # resolved by following its redirect — so it has to be inside the budget
        # or the first call of every import is untracked and unpaced.
        src = parse_skill_source(url)
        return _fetch_skill_bundle_inner(url, src, {})
    finally:
        _request_budget.reset(token)


def _fetch_skill_bundle_inner(
    url: str, src: ResolvedSource, files: Dict[str, str]
) -> Tuple[Dict[str, str], ResolvedSource]:

    path = _safe_relpath(src.path) if src.path else ""
    if path.lower().endswith("skill.md"):
        files[path] = _fetch_text(_raw_url(src, path))
        parent = "/".join(path.split("/")[:-1])
        if parent:
            try:
                _list_github_dir(src, parent, files)
            except SkillImportError:
                pass
        return files, src

    if path:
        try:
            _fetch_text(_raw_url(src, f"{path}/SKILL.md"))
            _list_github_dir(src, path, files)
            return files, src
        except Exception:
            pass
        try:
            text = _fetch_text(_raw_url(src, path))
            if path.lower().endswith(".md"):
                files[path] = text
                return files, src
        except Exception:
            pass
        _list_github_dir(src, path, files)
    else:
        _list_github_dir(src, "", files)

    if not any(p.lower().endswith("skill.md") for p in files):
        # Flat repo root with SKILL.md only
        try:
            files["SKILL.md"] = _fetch_text(_raw_url(src, "SKILL.md"))
        except Exception as e:
            raise SkillImportError(
                "No SKILL.md found — link to a skill folder or SKILL.md on GitHub"
            ) from e
    return files, src


def pick_skill_md(files: Dict[str, str]) -> Tuple[str, str]:
    for rel, content in files.items():
        if rel.lower().endswith("skill.md"):
            return rel, content
    raise SkillImportError("bundle has no SKILL.md")


def default_category_from_source(src: ResolvedSource) -> str:
    return "imported"
