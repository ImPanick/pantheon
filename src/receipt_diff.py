"""What changed between the run that worked and the one that did not (`P4-28`).

The question receipts were built to answer. `P4-25` captured the configuration,
`P4-26` proved it round-trips, `P14-03` scores a set of them — and none of that
tells you *why* case 3 went from green to red. This does.

WHAT MAKES A DIFF WORTH READING, AND IT IS NOT COMPLETENESS.

Two receipts differ in dozens of ways that mean nothing: timestamps, ids, token
counts that moved by four. A diff that lists all of them is a diff nobody reads
twice, and an unread diff is worse than none because it was paid for.

So every difference is classified, and the classification is the product:

  **chosen**    — the operator asked for it. A model override in a replay is the
                  clearest case: it is not a finding, it is the experiment.
  **inflicted** — the world moved. A skill was edited, a tool's schema changed,
                  an endpoint was renamed. Nobody asked, and this is almost
                  always the answer to "why did it change".
  **outcome**   — what the run produced: rounds, tokens, failures, errors. Not a
                  cause, and never presented as one.
  **noise**     — timestamps, run ids, durations under a threshold. Collected
                  and counted, never printed by default.

`P4-26` already records `deliberate` on a replay, which is what lets *chosen*
and *inflicted* be told apart at all rather than guessed at from the shape of
the change.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CHOSEN, INFLICTED, OUTCOME, NOISE = "chosen", "inflicted", "outcome", "noise"

# Below this, a duration difference is the machine being a machine.
DURATION_NOISE_RATIO = 0.25


def _entry(kind: str, what: str, before: Any, after: Any,
           note: str = "") -> Dict[str, Any]:
    return {"kind": kind, "what": what, "before": before, "after": after,
            "note": note}


def _replay_link(rec: Dict[str, Any]) -> Tuple[Optional[str], List[str], List[str]]:
    """(replay_of, deliberate, drift) from a receipt's replay row, if it has one."""
    detail = None
    for row in (rec.get("replays") or []):
        detail = row.get("detail") or {}
        break
    if detail is None:
        return None, [], []
    return (detail.get("replay_of"), list(detail.get("deliberate") or []),
            list(detail.get("drift") or []))


def _tools_by_name(config: Dict[str, Any]) -> Dict[str, str]:
    return {t.get("name"): t.get("sha") for t in (config.get("tools") or [])
            if isinstance(t, dict) and t.get("name")}


def _skills_by_name(config: Dict[str, Any]) -> Dict[str, Any]:
    return {s.get("name"): s.get("confidence") for s in (config.get("skills") or [])
            if isinstance(s, dict) and s.get("name")}


def diff_receipts(before_id: str, after_id: str) -> Dict[str, Any]:
    """Compare two runs. Returns classified differences and a one-line verdict."""
    from src.events import receipt

    out: Dict[str, Any] = {"before": before_id, "after": after_id,
                           "differences": [], "noise_count": 0,
                           "headline": "", "error": None}
    a, b = receipt(before_id), receipt(after_id)
    for label, rec in (("before", a), ("after", b)):
        if rec.get("error"):
            out["error"] = f"{label} receipt unavailable: {rec['error']}"
            out["headline"] = out["error"]
            return out
        if not rec.get("rounds") and not rec.get("config"):
            out["error"] = f"{label} run {rec.get('run_id')!r} recorded nothing"
            out["headline"] = out["error"]
            return out

    diffs: List[Dict[str, Any]] = []
    _, deliberate, drift = _replay_link(b)
    chosen_text = " ".join(deliberate).lower()

    # --- model and endpoint ------------------------------------------------
    a_round = (a.get("rounds") or [{}])[0]
    b_round = (b.get("rounds") or [{}])[0]
    if a_round.get("model") != b_round.get("model"):
        # A model change is only a finding when nobody asked for it. `P4-26`
        # records an override as `deliberate`, which is why this can be told
        # rather than guessed.
        asked = "model" in chosen_text
        diffs.append(_entry(
            CHOSEN if asked else INFLICTED, "model",
            a_round.get("model"), b_round.get("model"),
            "requested for this run" if asked else "the model changed and nobody asked"))
    if a_round.get("endpoint") != b_round.get("endpoint"):
        diffs.append(_entry(INFLICTED, "endpoint",
                            a_round.get("endpoint"), b_round.get("endpoint"),
                            "same model may now be served from elsewhere"))

    # --- sampling ----------------------------------------------------------
    a_cfg, b_cfg = (a.get("config") or {}), (b.get("config") or {})
    a_s, b_s = (a_cfg.get("sampling") or {}), (b_cfg.get("sampling") or {})
    for key in sorted(set(a_s) | set(b_s)):
        if a_s.get(key) != b_s.get(key):
            diffs.append(_entry(INFLICTED, f"sampling.{key}",
                                a_s.get(key), b_s.get(key)))

    # --- tools -------------------------------------------------------------
    a_t, b_t = _tools_by_name(a_cfg), _tools_by_name(b_cfg)
    for name in sorted(set(a_t) - set(b_t)):
        diffs.append(_entry(INFLICTED, f"tool:{name}", "present", "absent",
                            "the model can no longer call this"))
    for name in sorted(set(b_t) - set(a_t)):
        diffs.append(_entry(INFLICTED, f"tool:{name}", "absent", "present",
                            "the model was offered something new"))
    for name in sorted(set(a_t) & set(b_t)):
        if a_t[name] != b_t[name]:
            # The hash is the whole reason `P4-25` stores one: the schema moved,
            # and the name alone would have said nothing.
            diffs.append(_entry(INFLICTED, f"tool:{name}", a_t[name], b_t[name],
                                "the schema changed"))

    # --- skills ------------------------------------------------------------
    a_k, b_k = _skills_by_name(a_cfg), _skills_by_name(b_cfg)
    for name in sorted(set(a_k) - set(b_k)):
        diffs.append(_entry(INFLICTED, f"skill:{name}", "injected", "not injected",
                            "the procedure the model was following is gone"))
    for name in sorted(set(b_k) - set(a_k)):
        diffs.append(_entry(INFLICTED, f"skill:{name}", "not injected", "injected"))
    for name in sorted(set(a_k) & set(b_k)):
        if a_k[name] != b_k[name]:
            diffs.append(_entry(INFLICTED, f"skill:{name}.confidence",
                                a_k[name], b_k[name]))

    # --- outcome -----------------------------------------------------------
    a_tot, b_tot = (a.get("totals") or {}), (b.get("totals") or {})
    for key in ("rounds", "tool_calls", "tool_failures", "approvals"):
        if a_tot.get(key) != b_tot.get(key):
            diffs.append(_entry(OUTCOME, key, a_tot.get(key), b_tot.get(key)))
    for key in ("input_tokens", "output_tokens"):
        before_v, after_v = a_tot.get(key) or 0, b_tot.get(key) or 0
        if before_v == after_v:
            continue
        # Token counts wobble on identical inputs. Only a real move is signal.
        ratio = abs(after_v - before_v) / max(1, before_v)
        diffs.append(_entry(NOISE if ratio < DURATION_NOISE_RATIO else OUTCOME,
                            key, before_v, after_v))

    a_dur = sum(r.get("duration_ms") or 0 for r in a.get("rounds", []))
    b_dur = sum(r.get("duration_ms") or 0 for r in b.get("rounds", []))
    if a_dur != b_dur:
        ratio = abs(b_dur - a_dur) / max(1, a_dur)
        diffs.append(_entry(NOISE if ratio < DURATION_NOISE_RATIO else OUTCOME,
                            "duration_ms", a_dur, b_dur))

    for line in drift:
        diffs.append(_entry(INFLICTED, "drift", None, line,
                            "reported by the replay that produced the second run"))

    out["noise_count"] = sum(1 for d in diffs if d["kind"] == NOISE)
    out["differences"] = [d for d in diffs if d["kind"] != NOISE]
    out["headline"] = _headline(out)
    return out


def _headline(result: Dict[str, Any]) -> str:
    """Leads with the inflicted differences, because those are the answer.

    Ordering is the argument: *what changed that nobody chose* is the question
    somebody is actually asking when they open a diff, and putting the outcome
    first would bury it under numbers that are consequences.
    """
    diffs = result["differences"]
    if not diffs:
        return (f"No meaningful differences"
                + (f" ({result['noise_count']} noise)" if result["noise_count"] else ""))
    inflicted = [d for d in diffs if d["kind"] == INFLICTED]
    chosen = [d for d in diffs if d["kind"] == CHOSEN]
    outcome = [d for d in diffs if d["kind"] == OUTCOME]
    parts = []
    if inflicted:
        parts.append(f"{len(inflicted)} unasked-for change(s): "
                     + ", ".join(d["what"] for d in inflicted[:4])
                     + ("…" if len(inflicted) > 4 else ""))
    if chosen:
        parts.append(f"{len(chosen)} chosen: " + ", ".join(d["what"] for d in chosen))
    if outcome:
        parts.append(f"{len(outcome)} outcome change(s): "
                     + ", ".join(d["what"] for d in outcome[:4]))
    return " · ".join(parts)
