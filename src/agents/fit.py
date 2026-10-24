# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-18` · The fit badge: has this agent been measured on the model it would run on?

A proof run (`python -m src.agents.evals <agent> --endpoint … --model … --runs 5
--out <data>/agent_proofs.jsonl`) leaves one row per agent and model —
`src.agents.evals.proof_row`. Rows come from two places: the install's own
(`<data>/agent_proofs.jsonl`, appended by every proof run here) and the
repository's (`library/pantheon/agents/<id>/proofs.json`, the reference
models' rows, `D-2026-10-22-01` §6). The newest row for the agent's current
version and the model's family decides:

  * **Runs well** — every case passed at least 4 runs in 5, inside the time budget;
  * **Runs, slowly** — it passes, but its median run is past `max_minutes`;
  * **Needs a bigger model** — any case passed less than that;
  * **Not measured** — no row; *Try it once* is still offered.

The badge is a measurement or it says there is none — never a claim.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

PROOFS_FILE = "agent_proofs.jsonl"
SHIPPED_PROOFS = "proofs.json"
PASS_SHARE = 0.8

WORDS = {"runs-well": "Runs well", "runs-slowly": "Runs, slowly",
         "needs-bigger": "Needs a bigger model", "not-measured": "Not measured"}


def family(model: Optional[str]) -> str:
    """`openai/gpt-oss-20b@q4_k_m` and `gpt-oss-20b:latest` are one family."""
    name = str(model or "").strip().lower()
    name = name.rsplit("/", 1)[-1]
    name = re.split(r"[@:]", name, 1)[0]
    name = re.sub(r"[-_.](q\d[\w]*|gguf|mlx|awq|gptq|fp16|bf16|int[48]|\d+bit)$", "", name)
    return name


def _install_rows(data_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    if data_dir is None:
        from src.constants import DATA_DIR as data_dir
    path = os.path.join(data_dir, PROOFS_FILE)
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("agent") and row.get("model"):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _shipped_rows(manifest) -> List[Dict[str, Any]]:
    path = os.path.join(os.path.dirname(manifest.path or ""), SHIPPED_PROOFS) if manifest.path else ""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def verdict(row: Dict[str, Any], max_minutes: float) -> str:
    cases = row.get("cases") or {}
    if not cases:
        return "needs-bigger"
    for c in cases.values():
        of = c.get("of") or 0
        if not of or (c.get("passed") or 0) / of < PASS_SHARE:
            return "needs-bigger"
    if float(row.get("median_minutes") or 0) > float(max_minutes):
        return "runs-slowly"
    return "runs-well"


def fit(manifest, model: Optional[str], *, rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The badge for `manifest` on `model`: `{badge, words, model, row}`."""
    fam = family(model)
    pool = rows if rows is not None else (_shipped_rows(manifest) + _install_rows())
    mine = [r for r in pool if r.get("agent") == manifest.id and r.get("version") == manifest.version
            and fam and family(r.get("model")) == fam]
    if not mine:
        return {"badge": "not-measured", "words": WORDS["not-measured"], "model": model, "row": None}
    row = max(mine, key=lambda r: str(r.get("at") or ""))
    badge = verdict(row, manifest.budget.get("max_minutes", 10))
    return {"badge": badge, "words": WORDS[badge], "model": row.get("model"),
            "row": {k: row.get(k) for k in ("model", "runs", "pass_rate", "median_minutes", "at", "failures")}}


def model_for(owner: Optional[str]) -> Optional[str]:
    """The model a hire of `owner`'s runs on: scheduled work's model."""
    try:
        from src.task_endpoint import resolve_task_endpoint
        _url, model, _h = resolve_task_endpoint(owner=owner or None)
        return model or None
    except Exception:
        return None
