# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which model plays each part, the person's mode, and the matching numbers.

Three roles, each an endpoint and model in Settings, any provider (the paper's
choices were Opus and Haiku; nothing here assumes either):

  * **builder** — turns a finished run into an entry. Background only, and the
    heaviest job here, so the strongest model you have, ideally local;
  * **target**  — pulls a request's parameters out of its words and answers the
    entry's small `lm` and `extract` calls. A 1-4B instruct model is enough;
  * **judge**   — the second opinion: the builder and the judge must both agree
    before an entry is kept, or before a shadow run counts as agreement.

A role left empty falls back to the Utility model, then the default chat model
(`endpoint_resolver._configured_entry`), as every other side model does.

The mode is each person's own (`PUT /api/prefs/reasoning_cache`): `off` (the
default), `shadow` (entries are built and checked, the model always answers)
or `live` (an entry that has earned it answers in the model's place).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

ROLES = ("builder", "target", "judge")
MODES = ("off", "shadow", "live")
MODE_PREF = "reasoning_cache"

MATCH_PERCENT_SETTING = "reasoning_cache_match_percent"
AGREEMENTS_SETTING = "reasoning_cache_agreements"
MATCH_PERCENT_DEFAULT = 88
AGREEMENTS_DEFAULT = 3


def checked_mode(value: Any) -> str:
    """A stored mode, or `ValueError` naming the three it may be."""
    mode = str(value or "").strip().lower()
    if mode not in MODES:
        raise ValueError(f"reasoning_cache must be one of: {', '.join(MODES)}")
    return mode


def mode_for(owner: Optional[str]) -> str:
    """This person's mode. Anything unreadable is `off`: the cache is opt-in."""
    if not owner:
        return "off"
    try:
        from routes.prefs_routes import _load_for_user
        return checked_mode((_load_for_user(owner) or {}).get(MODE_PREF) or "off")
    except Exception:
        return "off"


def match_threshold() -> float:
    from src.settings import get_setting
    try:
        return int(get_setting(MATCH_PERCENT_SETTING, MATCH_PERCENT_DEFAULT)) / 100.0
    except (TypeError, ValueError):
        return MATCH_PERCENT_DEFAULT / 100.0


def agreements_needed() -> int:
    from src.settings import get_setting
    try:
        return max(1, int(get_setting(AGREEMENTS_SETTING, AGREEMENTS_DEFAULT)))
    except (TypeError, ValueError):
        return AGREEMENTS_DEFAULT


def resolve(role: str, owner: Optional[str]) -> Tuple[Optional[str], Optional[str], Dict]:
    """`(url, model, headers)` for a role, or Nones when nothing is configured."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    from src.endpoint_resolver import resolve_endpoint
    url, model, headers = resolve_endpoint(f"reasoning_cache_{role}", owner=owner)
    return url, model, dict(headers or {})


async def call(role: str, owner: Optional[str], messages: List[Dict[str, Any]], *,
               max_tokens: int = 1024, workload: str = "background") -> str:
    """One call to a role's model. Raises when no model is configured or the
    call fails, which every caller here reads as a miss."""
    url, model, headers = resolve(role, owner)
    if not url or not model:
        raise RuntimeError(f"no model is set for the reasoning cache {role}")
    from src.llm_core import llm_call_async
    text = await llm_call_async(url, model, messages, temperature=0.0,
                                max_tokens=max_tokens, headers=headers,
                                workload=workload, thinking=False)
    return text if isinstance(text, str) else str(text[0])


def model_name(role: str, owner: Optional[str]) -> Optional[str]:
    try:
        return resolve(role, owner)[1]
    except Exception:
        return None



def all_local(owner: Optional[str]) -> bool:
    """Whether every role's model is one nobody bills for. A run inside a
    space pinned to local models consults the cache only when this holds, so
    its words never reach a paid API by way of the cache either."""
    from src.apollo import budget
    for role in ROLES:
        url, model, _ = resolve(role, owner)
        if not url or not model or budget.billed(url):
            return False
    return True

_embedder_lock = threading.Lock()
_embedder: Any = None


def embed(text: str) -> Optional[List[float]]:
    """The request's vector, from the embedding client Pantheon already runs,
    or None when there is none (the cache then sits the turn out). Blocking:
    call it off the event loop."""
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            try:
                from src.embeddings import get_embedding_client
                _embedder = get_embedding_client() or False
            except Exception as exc:
                logger.info("reasoning cache: no embedding client (%s)", exc)
                _embedder = False
        client = _embedder
    if not client:
        return None
    try:
        vecs = client.encode([text[:4000]], normalize_embeddings=True)
        return [float(x) for x in vecs[0]]
    except Exception as exc:
        logger.info("reasoning cache: embedding failed (%s)", exc)
        return None


def same_params(expected: Dict[str, Any], got: Dict[str, Any], names: Sequence[str]) -> bool:
    """Whether an extraction matched, compared the way a person would read it:
    case, surrounding space and thousands separators aside."""
    def norm(v: Any) -> str:
        return " ".join(str(v if v is not None else "").replace(",", "").split()).casefold()
    return all(norm(expected.get(n)) == norm(got.get(n)) for n in names)
