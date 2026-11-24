# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which mail is worth unsubscribing from, and how — one scorer.

`B2171`. The Email page's *Unsubscribe* review (`routes/email_routes.py`) and
the agent's mail tools (`mcp_servers/email_server.py`, its own process) each
carried a copy of this: the List-Unsubscribe parser, the scorer and the
de-duplication, three of the four byte-identical. The scorers had drifted: only
the page's adds +35 for a message the spam classifier already marked, and says
why. The owner's pick (`D-2026-11-24-02`): the page's scorer is the one scorer.
It lives in `src/` because the MCP server cannot import a request-handler module
(the reason `src/mail_headers.py` exists, `B1232`); both import it from here.

A candidate needs a List-Unsubscribe header (score 45); a mailing-list header,
a bulk precedence, an auto-submitted mark, a spam verdict on record and a
promotional subject add to it, capped at 100.
"""
from __future__ import annotations

import email.utils
import re
from urllib.parse import parse_qs, unquote, urlparse

from src.mail_headers import decode_header


def parse_list_unsubscribe_header(value: str | None) -> list[dict]:
    """Parse RFC List-Unsubscribe entries into safe reviewable actions.

    We return mailto/http entries but only the mailto kind is executable by the
    first-pass Pantheon flow. HTTP unsubscribe links are useful evidence but
    often contain tracking tokens and should be opened manually unless/until we
    add a browser-confirmed flow.
    """
    raw = str(value or "").strip()
    if not raw:
        return []
    # `B1902`. What `re.findall(r"<([^>]+)>", raw)` found, in linear time.
    from src.tool_parsing import iter_angle_tags
    pieces = [raw[inner_start:inner_end] for _s, inner_start, inner_end, _e in iter_angle_tags(raw)]
    if not pieces:
        pieces = [p.strip() for p in raw.split(",") if p.strip()]
    out: list[dict] = []
    seen = set()
    for piece in pieces:
        target = piece.strip().strip("<>").strip()
        if not target:
            continue
        parsed = urlparse(target)
        scheme = parsed.scheme.lower()
        key = target.lower()
        if key in seen:
            continue
        seen.add(key)
        if scheme == "mailto":
            addr = unquote(parsed.path or "").strip()
            if not addr or "\r" in addr or "\n" in addr:
                continue
            query = parse_qs(parsed.query or "", keep_blank_values=True)
            subject = unquote((query.get("subject") or ["unsubscribe"])[0] or "unsubscribe")
            body = unquote((query.get("body") or ["unsubscribe"])[0] or "unsubscribe")
            subject = re.sub(r"[\r\n]+", " ", subject).strip() or "unsubscribe"
            body = re.sub(r"[\r\n]+", "\n", body).strip() or "unsubscribe"
            out.append({
                "kind": "mailto",
                "target": addr,
                "subject": subject[:200],
                "body": body[:1000],
                "executable": True,
            })
        elif scheme in {"http", "https"}:
            out.append({
                "kind": "url",
                "target": target,
                "executable": False,
            })
    return out


def unsubscribe_candidate_from_msg(msg, uid: str, folder: str, *, spam_cached: dict | None = None) -> dict | None:
    sender = decode_header(msg.get("From", ""))
    sender_name, sender_addr = email.utils.parseaddr(sender)
    subject = decode_header(msg.get("Subject", "(no subject)"))
    list_id = decode_header(msg.get("List-Id", ""))
    precedence = (msg.get("Precedence") or "").strip().lower()
    auto_submitted = (msg.get("Auto-Submitted") or "").strip().lower()
    methods = parse_list_unsubscribe_header(msg.get("List-Unsubscribe"))
    has_unsub = bool(methods)
    reasons: list[str] = []
    score = 0
    if has_unsub:
        score += 45
        reasons.append("has unsubscribe header")
    if list_id:
        score += 20
        reasons.append("mailing-list header")
    if precedence in {"bulk", "junk", "list"}:
        score += 20
        reasons.append(f"precedence={precedence}")
    if auto_submitted and auto_submitted != "no":
        score += 10
        reasons.append(f"auto-submitted={auto_submitted}")
    if spam_cached and spam_cached.get("spam"):
        score += 35
        if spam_cached.get("reason"):
            reasons.append(str(spam_cached.get("reason")))
        else:
            reasons.append("previously classified as spam")
    subj_l = (subject or "").lower()
    if re.search(r"\b(unsubscribe|newsletter|sale|discount|offer|promo|limited time)\b", subj_l):
        score += 10
        reasons.append("promotional subject")
    executable = [m for m in methods if m.get("executable")]
    if score < 45 or not has_unsub:
        return None
    return {
        "uid": str(uid),
        "folder": folder,
        "message_id": (msg.get("Message-ID") or "").strip(),
        "subject": subject,
        "from_name": sender_name or sender_addr,
        "from_address": sender_addr,
        "list_id": list_id,
        "score": min(score, 100),
        "reasons": reasons[:5],
        "methods": methods,
        "can_execute": bool(executable),
        "recommended_method": executable[0] if executable else (methods[0] if methods else None),
        "spam_reason": (spam_cached or {}).get("reason") or "",
    }


def unsubscribe_candidate_dedupe_key(candidate: dict) -> tuple[str, str, str]:
    list_id = str(candidate.get("list_id") or "").strip().lower()
    method = candidate.get("recommended_method") or {}
    method_kind = str(method.get("kind") or "").strip().lower()
    method_target = str(method.get("target") or "").strip().lower()
    sender = str(candidate.get("from_address") or "").strip().lower()
    if list_id:
        return ("list", list_id, method_target or sender)
    if method_target:
        return ("method", method_kind, method_target)
    return ("sender", sender, str(candidate.get("subject") or "").strip().lower())


def dedupe_unsubscribe_candidates(candidates: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, str, str], dict] = {}
    for candidate in candidates or []:
        key = unsubscribe_candidate_dedupe_key(candidate)
        existing = deduped.get(key)
        if not existing:
            copy = dict(candidate)
            copy["duplicate_count"] = 1
            copy["duplicate_uids"] = [str(candidate.get("uid") or "")]
            deduped[key] = copy
            continue
        existing["duplicate_count"] = int(existing.get("duplicate_count") or 1) + 1
        uid = str(candidate.get("uid") or "")
        if uid:
            existing.setdefault("duplicate_uids", []).append(uid)
        if int(candidate.get("score") or 0) > int(existing.get("score") or 0):
            keep_count = existing.get("duplicate_count")
            keep_uids = existing.get("duplicate_uids")
            replacement = dict(candidate)
            replacement["duplicate_count"] = keep_count
            replacement["duplicate_uids"] = keep_uids
            deduped[key] = replacement
    return list(deduped.values())
