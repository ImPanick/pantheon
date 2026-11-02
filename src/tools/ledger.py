# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24-30` · `ledger_table` — the finance agents' table.

The audit (`P24-28`) named the finance five and said why they could not ship:
Pantheon had no place for a row of money — a document is prose, a note is a
reminder, a file is the person's own. This is that place: one table of lines
(`core.database.LedgerEntry`), each a date, a kind, an amount and who it was
with, and a tool with six actions over it.

    {"action": "add", "kind": "expense", "date": "2026-11-02", "amount": 120.50,
     "counterparty": "Hetzner", "category": "hosting", "memo": "November servers"}
    {"action": "list", "kind": "bill", "status": "open", "to": "2026-11-30"}
    {"action": "sum", "from": "2026-11-01", "to": "2026-11-30", "group_by": "category"}
    {"action": "update", "id": "3f2a", "status": "paid"}
    {"action": "import", "rows": [{"date": …, "kind": …, "amount": …}, …]}
    {"action": "delete", "id": "3f2a"}

`kind` says which way the money goes — `income`, `expense`, `invoice` (owed to
the person), `bill` (owed by them), `payroll`, `transfer`, `tax`; `amount` is
positive. `status` is `posted` for money that moved, `open` / `paid` / `void`
for an invoice or a bill, `draft` for a line someone still has to confirm.

The gate reads its actions from `src/tool_capabilities.py`: `list` and `sum`
are private reads, `add`, `update`, `import` private writes, `delete`
destructive. The tool never sends anything anywhere.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date as _date
from typing import Any, Dict, List, Optional

from src.tools._common import _parse_tool_args

logger = logging.getLogger(__name__)

KINDS = ("income", "expense", "invoice", "bill", "payroll", "transfer", "tax")
STATUSES = ("posted", "open", "paid", "void", "draft")
GROUPS = ("kind", "category", "counterparty", "account", "month", "status")
FIELDS = ("date", "kind", "account", "category", "counterparty", "amount", "currency",
          "memo", "status", "due", "ref")
LIST_LIMIT = 200
IMPORT_LIMIT = 2000

_ACTION_ALIASES = {
    "create": "add", "new": "add", "post": "add", "record": "add",
    "remove": "delete", "void": "delete",
    "total": "sum", "totals": "sum", "summary": "sum", "summarise": "sum", "summarize": "sum",
    "query": "list", "search": "list", "find": "list", "show": "list",
    "bulk_add": "import", "import_rows": "import",
}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_date(value: Any, field: str) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()[:10]
    if not _DATE.match(text):
        raise ValueError(f"{field} is a date written YYYY-MM-DD, not “{value}”.")
    return text


def _clean_amount(value: Any) -> float:
    try:
        amount = float(str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"amount is a number, not “{value}”.")
    if amount < 0:
        raise ValueError("amount is positive; `kind` says which way the money goes.")
    return round(amount, 2)


def _clean_row(args: Dict[str, Any], *, partial: bool) -> Dict[str, Any]:
    """The fields of a row from a call's arguments, checked. `partial` for an
    update, where a field left out stays as it was."""
    out: Dict[str, Any] = {}
    if "kind" in args or not partial:
        kind = str(args.get("kind") or "").strip().lower()
        if kind not in KINDS:
            raise ValueError(f"kind is one of {', '.join(KINDS)}, not “{args.get('kind')}”.")
        out["kind"] = kind
    if "amount" in args or not partial:
        if args.get("amount") is None:
            raise ValueError("amount is required.")
        out["amount"] = _clean_amount(args.get("amount"))
    if "date" in args or not partial:
        out["date"] = _clean_date(args.get("date"), "date") or _date.today().isoformat()
    if "due" in args:
        out["due"] = _clean_date(args.get("due"), "due")
    if "status" in args:
        status = str(args.get("status") or "").strip().lower()
        if status not in STATUSES:
            raise ValueError(f"status is one of {', '.join(STATUSES)}, not “{args.get('status')}”.")
        out["status"] = status
    elif not partial:
        out["status"] = "open" if out.get("kind") in ("invoice", "bill") else "posted"
    for key in ("account", "category", "counterparty", "currency", "ref"):
        if key in args:
            out[key] = str(args.get(key) or "").strip()[:200]
    if "memo" in args:
        out["memo"] = str(args.get("memo") or "").strip()[:4000]
    return out


def _filters(q, LedgerEntry, args: Dict[str, Any]):
    for key in ("kind", "status", "account"):
        if args.get(key):
            q = q.filter(getattr(LedgerEntry, key) == str(args[key]).strip().lower()
                         if key in ("kind", "status") else getattr(LedgerEntry, key) == str(args[key]).strip())
    for key in ("category", "counterparty"):
        if args.get(key):
            q = q.filter(getattr(LedgerEntry, key).ilike(f"%{str(args[key]).strip()}%"))
    since = _clean_date(args.get("from"), "from")
    until = _clean_date(args.get("to"), "to")
    if since:
        q = q.filter(LedgerEntry.date >= since)
    if until:
        q = q.filter(LedgerEntry.date <= until)
    if args.get("due_by"):
        q = q.filter(LedgerEntry.due != None, LedgerEntry.due <= _clean_date(args["due_by"], "due_by"))  # noqa: E711
    return q


def _money(amount: float, currency: str = "") -> str:
    text = f"{amount:,.2f}"
    return f"{text} {currency}".strip()


def _table(rows: List[Any]) -> str:
    lines = ["| id | date | kind | counterparty | category | amount | status | due | memo |",
             "|---|---|---|---|---|---:|---|---|---|"]
    for r in rows:
        memo = (r.memo or "").replace("|", "/").replace("\n", " ")
        if len(memo) > 60:
            memo = memo[:57] + "…"
        lines.append(f"| {r.id[:8]} | {r.date} | {r.kind} | {r.counterparty or ''} | {r.category or ''} | "
                     f"{_money(r.amount or 0.0, r.currency or '')} | {r.status} | {r.due or ''} | {memo} |")
    return "\n".join(lines)


def _signed(r) -> float:
    """A line's effect on cash: in for income and a paid invoice, out for the
    rest, nothing for a transfer, a void line or one still open."""
    if r.status in ("void", "draft"):
        return 0.0
    if r.kind == "income" or (r.kind == "invoice" and r.status == "paid"):
        return float(r.amount or 0.0)
    if r.kind in ("expense", "payroll", "tax") or (r.kind == "bill" and r.status == "paid"):
        return -float(r.amount or 0.0)
    return 0.0


async def do_ledger_table(content: str, owner: Optional[str] = None) -> Dict:
    """Handle `ledger_table` calls."""
    from core.database import LedgerEntry, SessionLocal

    try:
        args = _parse_tool_args(content)
    except ValueError:
        return {"error": "Invalid JSON arguments", "exit_code": 1}
    if not isinstance(args, dict):
        return {"error": "Arguments are a JSON object.", "exit_code": 1}
    action = str(args.get("action") or "list").replace("-", "_").strip().lower()
    action = _ACTION_ALIASES.get(action, action)

    db = SessionLocal()

    def _mine():
        q = db.query(LedgerEntry)
        return q.filter(LedgerEntry.owner == owner) if owner else q

    def _one(row_id: str):
        row_id = str(row_id or "").strip()
        if not row_id:
            return None
        return _mine().filter(LedgerEntry.id.startswith(row_id)).first()

    try:
        if action == "list":
            q = _filters(_mine(), LedgerEntry, args)
            limit = max(1, min(int(args.get("limit") or LIST_LIMIT), LIST_LIMIT))
            rows = q.order_by(LedgerEntry.date.desc(), LedgerEntry.created_at.desc()).limit(limit + 1).all()
            more = len(rows) > limit
            rows = rows[:limit]
            if not rows:
                return {"response": "No ledger lines match.", "count": 0, "exit_code": 0}
            total = round(sum(float(r.amount or 0.0) for r in rows), 2)
            net = round(sum(_signed(r) for r in rows), 2)
            foot = (f"\n\n{len(rows)} line(s){' of more — narrow the filters or raise limit' if more else ''}; "
                    f"amounts total {_money(total)}; net effect on cash {_money(net)}.")
            return {"results": _table(rows) + foot, "count": len(rows), "total": total, "net": net,
                    "exit_code": 0}

        if action == "sum":
            q = _filters(_mine(), LedgerEntry, args)
            rows = q.all()
            group = str(args.get("group_by") or "kind").strip().lower()
            if group not in GROUPS:
                return {"error": f"group_by is one of {', '.join(GROUPS)}.", "exit_code": 1}
            buckets: Dict[str, Dict[str, float]] = {}
            for r in rows:
                key = (r.date or "")[:7] if group == "month" else (getattr(r, group) or "(none)")
                b = buckets.setdefault(str(key), {"count": 0, "total": 0.0, "net": 0.0})
                b["count"] += 1
                b["total"] += float(r.amount or 0.0)
                b["net"] += _signed(r)
            if not buckets:
                return {"response": "No ledger lines match.", "count": 0, "groups": {}, "exit_code": 0}
            lines = [f"| {group} | lines | amounts | net cash |", "|---|---:|---:|---:|"]
            for key in sorted(buckets):
                b = buckets[key]
                lines.append(f"| {key} | {b['count']} | {_money(b['total'])} | {_money(b['net'])} |")
            grand = round(sum(b["total"] for b in buckets.values()), 2)
            net = round(sum(b["net"] for b in buckets.values()), 2)
            lines.append(f"| **all** | {len(rows)} | {_money(grand)} | {_money(net)} |")
            return {"results": "\n".join(lines), "count": len(rows), "total": grand, "net": net,
                    "groups": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in buckets.items()},
                    "exit_code": 0}

        if action == "add":
            try:
                fields = _clean_row(args, partial=False)
            except ValueError as e:
                return {"error": str(e), "exit_code": 1}
            row = LedgerEntry(id=str(uuid.uuid4()), owner=owner, source="agent", **fields)
            db.add(row)
            db.commit()
            return {"response": f"Ledger line added: {row.kind} {_money(row.amount, row.currency)} "
                                f"{('with ' + row.counterparty) if row.counterparty else ''} on {row.date} "
                                f"(id: {row.id[:8]}).".replace("  ", " "),
                    "id": row.id, "exit_code": 0}

        if action == "import":
            rows_in = args.get("rows")
            if not isinstance(rows_in, list) or not rows_in:
                return {"error": "import takes `rows`, a list of lines each with date, kind and amount.",
                        "exit_code": 1}
            if len(rows_in) > IMPORT_LIMIT:
                return {"error": f"import takes at most {IMPORT_LIMIT} rows at a time.", "exit_code": 1}
            made, refused = 0, []
            for n, raw in enumerate(rows_in, start=1):
                if not isinstance(raw, dict):
                    refused.append(f"row {n}: not an object")
                    continue
                try:
                    fields = _clean_row(raw, partial=False)
                except ValueError as e:
                    refused.append(f"row {n}: {e}")
                    continue
                db.add(LedgerEntry(id=str(uuid.uuid4()), owner=owner, source="import", **fields))
                made += 1
            db.commit()
            out = {"response": f"Imported {made} ledger line(s)" + (f"; {len(refused)} refused." if refused else "."),
                   "imported": made, "refused": refused[:50], "exit_code": 0}
            return out

        if action == "update":
            row = _one(args.get("id"))
            if not row:
                return {"error": f"Ledger line “{args.get('id')}” not found.", "exit_code": 1}
            try:
                fields = _clean_row({k: v for k, v in args.items() if k in FIELDS}, partial=True)
            except ValueError as e:
                return {"error": str(e), "exit_code": 1}
            if not fields:
                return {"error": "Nothing to change: name a field (" + ", ".join(FIELDS) + ").", "exit_code": 1}
            for k, v in fields.items():
                setattr(row, k, v)
            db.commit()
            return {"response": f"Ledger line {row.id[:8]} updated: " + ", ".join(f"{k} = {v}" for k, v in fields.items()) + ".",
                    "id": row.id, "exit_code": 0}

        if action == "delete":
            row = _one(args.get("id"))
            if not row:
                return {"error": f"Ledger line “{args.get('id')}” not found.", "exit_code": 1}
            said = f"{row.kind} {_money(row.amount, row.currency)} on {row.date}"
            db.delete(row)
            db.commit()
            return {"response": f"Deleted ledger line {said}.", "exit_code": 0}

        return {"error": f"Unknown action: {action}. Use list/sum/add/update/delete/import.", "exit_code": 1}
    except Exception as e:  # pragma: no cover - the one catch, as the notes tool has
        logger.error("ledger_table error: %s", e)
        return {"error": str(e), "exit_code": 1}
    finally:
        db.close()
