"""P7-04 — the owner-scoped auto-allow rule store behind the `allow_listed` rung.

`src/tool_capabilities.py` owns the gate. This module owns the rules it asks,
and the seam between them is one callable, `(tool_name, content) -> bool`, built
once per run by :func:`allow_rule_lookup_for` and handed to
`ToolRunSecurityContext.allow_rule_lookup` by `src/agent_loop.py`.

Nothing here decides whether an action may run. The gate consults a rule only
for an action it would otherwise refuse, so a rule can turn a refusal into an
allow and can do nothing else — there is no deny rule, because `src/tool_policy.py`
already decides what may run at all and a second, weaker copy of that here would
be a fork where one side goes stale.

Three match kinds, and deliberately no fourth:

    any     every action of this tool
    exact   the normalised content equals the stored pattern
    prefix  the normalised content starts with the stored pattern

There is no regex kind and there must not be one. Users cannot write a regex
that means what they think it means, which in an allow-list means granting more
than they intended; and a catastrophically backtracking pattern evaluated on the
tool-dispatch path is a denial of service. Neither failure is worth the
expressiveness.

Normalisation is ``strip()`` on both sides and nothing else. Internal whitespace
is not collapsed and case is not folded, so ``git  push`` and ``GIT PUSH`` do not
match a rule written for ``git push``. This control only ever grants, so matching
*less* than the author meant costs a confirmation prompt, while matching *more*
costs the thing the prompt was protecting.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


MATCH_ANY = "any"
MATCH_EXACT = "exact"
MATCH_PREFIX = "prefix"

# The set of kinds that exist. This tuple is authoritative for *which* kinds a
# chooser may offer — `GET /api/tool-allow-rules` returns it so nothing keeps a
# second copy of the three strings — but **not for the order they are shown in**.
#
# CORRECTED 2026-08-29. This comment used to read "ordered widest-first, which is
# the order a chooser should present them in", and the UI it was written for
# deliberately does the opposite. The UI is right: the widest grant is the one
# clicked without reading, and a list of permissions should widen as it goes
# rather than open on the answer that gives the most away. Presentation order is
# the chooser's call; membership is this tuple's.
MATCH_KINDS: Tuple[str, ...] = (MATCH_ANY, MATCH_EXACT, MATCH_PREFIX)

MAX_TOOL_NAME_LEN = 200
# Long enough for any realistic command or argument prefix, short enough that
# the identity index stays inside the btree row-size limit of the non-SQLite
# backends this schema is written to survive on.
MAX_PATTERN_LEN = 1024
# One owner's rules are loaded into memory for the life of a run, and the list
# view returns all of them. Neither wants an unbounded row count.
MAX_RULES_PER_OWNER = 200

# How long a run may keep its snapshot of an owner's rules.
#
# Rules are loaded once and reused because a database read per tool call on the
# dispatch path is a cost with no reader. But a snapshot held for the whole run
# is a revocation that does not take effect, and a run can last hours. Five
# seconds is short enough that "revoke" means revoked before the user has
# finished reading the confirmation, and long enough that one model turn's worth
# of tool calls shares a single query.
#
# The stale direction that matters is revocation, not creation: a rule created
# mid-run and not yet visible costs one confirmation prompt, while a rule revoked
# mid-run and still visible costs the thing the prompt was protecting.
#
# A TTL rather than an in-process invalidation counter on purpose. A counter is
# exact, but only within one worker: under any multi-worker deployment a
# revocation issued to worker A would go on being ignored by worker B forever.
# Bounded-and-wrong beats exact-and-silently-partial for a control that grants.
SNAPSHOT_TTL_SECONDS = 5.0


class AllowRuleError(ValueError):
    """A rule the store refuses to write. The message is shown to the user."""


def _database():
    """Resolve `core.database` at call time.

    Imported here rather than at module scope so `SessionLocal` is read from the
    live module attribute — tests rebind it, and a `from ... import SessionLocal`
    would silently keep the first factory it saw.
    """
    import core.database as cdb

    return cdb


def normalize_owner(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_tool_name(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_content(value: Any) -> str:
    """`strip()` and nothing more — see the module docstring."""
    return str(value).strip() if value is not None else ""


def normalize_pattern(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_match_kind(value: Any) -> str:
    kind = str(value).strip().lower() if value is not None else ""
    return kind if kind in MATCH_KINDS else ""


def rule_matches(match_kind: Any, pattern: Any, content: Any) -> bool:
    """Does one stored rule cover this action's content?

    Every branch that is not a match the caller can state precisely answers
    False, including an unrecognised kind: this function is the last thing
    between a stored row and an allow, so "I do not know what this row means"
    has to read as "no".
    """
    kind = normalize_match_kind(match_kind)
    if kind == MATCH_ANY:
        return True
    stored = normalize_pattern(pattern)
    if not stored:
        # An empty exact/prefix pattern is `any` wearing another kind's name —
        # every string starts with "". `create_rule` rejects one, and this
        # rejects a row that reached the table by some other path.
        return False
    normalized = normalize_content(content)
    if kind == MATCH_EXACT:
        return normalized == stored
    if kind == MATCH_PREFIX:
        # Literal prefix, with no token-boundary rule bolted on. A boundary rule
        # would stop `git s` matching `git shove-everything`, but it would stop
        # it matching `git status` too — it separates nothing while making the
        # control impossible to predict from its own name. The mitigation for an
        # over-broad prefix belongs where the rule is written, which is why the
        # list shows the pattern verbatim and revoking is one call.
        return normalized.startswith(stored)
    return False


def _as_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "owner": row.owner,
        "tool_name": row.tool_name,
        "match_kind": row.match_kind,
        "pattern": row.pattern,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_rules(owner: Any) -> List[Dict[str, Any]]:
    """Every rule this owner has, newest first. An unusable owner has none."""
    owner_key = normalize_owner(owner)
    if not owner_key:
        return []
    cdb = _database()
    db = cdb.SessionLocal()
    try:
        rows = (
            db.query(cdb.ToolAllowRule)
            .filter(cdb.ToolAllowRule.owner == owner_key)
            .order_by(cdb.ToolAllowRule.created_at.desc())
            .limit(MAX_RULES_PER_OWNER)
            .all()
        )
        return [_as_dict(row) for row in rows]
    finally:
        db.close()


def create_rule(
    owner: Any,
    tool_name: Any,
    match_kind: Any,
    pattern: Any = "",
) -> Dict[str, Any]:
    """Write one rule, or return the identical rule this owner already has.

    Re-creating an existing rule answers with that rule rather than a second
    copy of it. The caller's intent — "this should be allowed" — is satisfied
    either way, and the list stays free of twins that make revocation look
    broken.

    Raises :class:`AllowRuleError` on anything it will not store. Refusing is
    always safe here; writing a rule nobody can describe is not.
    """
    owner_key = normalize_owner(owner)
    if not owner_key:
        raise AllowRuleError("An allow rule needs an owner.")

    tool = normalize_tool_name(tool_name)
    if not tool:
        raise AllowRuleError("An allow rule needs a tool name.")
    if len(tool) > MAX_TOOL_NAME_LEN:
        raise AllowRuleError(f"Tool name is longer than {MAX_TOOL_NAME_LEN} characters.")

    kind = normalize_match_kind(match_kind)
    if not kind:
        raise AllowRuleError(
            "Match kind must be one of: " + ", ".join(MATCH_KINDS) + "."
        )

    stored_pattern = normalize_pattern(pattern)
    if kind == MATCH_ANY:
        # Whatever was sent alongside `any` is not consulted by the matcher, so
        # storing it would put a string in the list that reads like a condition
        # and is not one.
        stored_pattern = ""
    elif not stored_pattern:
        raise AllowRuleError(
            f"A '{kind}' rule needs a pattern. To allow every use of a tool, "
            f"choose '{MATCH_ANY}' instead."
        )
    elif len(stored_pattern) > MAX_PATTERN_LEN:
        raise AllowRuleError(f"Pattern is longer than {MAX_PATTERN_LEN} characters.")

    cdb = _database()
    db = cdb.SessionLocal()
    try:
        existing = (
            db.query(cdb.ToolAllowRule)
            .filter(
                cdb.ToolAllowRule.owner == owner_key,
                cdb.ToolAllowRule.tool_name == tool,
                cdb.ToolAllowRule.match_kind == kind,
                cdb.ToolAllowRule.pattern == stored_pattern,
            )
            .first()
        )
        if existing is not None:
            return _as_dict(existing)

        count = (
            db.query(cdb.ToolAllowRule)
            .filter(cdb.ToolAllowRule.owner == owner_key)
            .count()
        )
        if count >= MAX_RULES_PER_OWNER:
            raise AllowRuleError(
                f"You already have {MAX_RULES_PER_OWNER} allow rules. "
                "Revoke one before adding another."
            )

        row = cdb.ToolAllowRule(
            id=str(uuid.uuid4()),
            owner=owner_key,
            tool_name=tool,
            match_kind=kind,
            pattern=stored_pattern,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _as_dict(row)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_rule(owner: Any, rule_id: Any) -> bool:
    """Revoke one of this owner's rules. False if they do not have it.

    Scoped by owner in the WHERE clause rather than checked after the read, so
    there is no path where a rule is loaded first and the ownership test is the
    thing that gets forgotten.
    """
    owner_key = normalize_owner(owner)
    key = str(rule_id).strip() if rule_id is not None else ""
    if not owner_key or not key:
        return False
    cdb = _database()
    db = cdb.SessionLocal()
    try:
        deleted = (
            db.query(cdb.ToolAllowRule)
            .filter(
                cdb.ToolAllowRule.owner == owner_key,
                cdb.ToolAllowRule.id == key,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        return bool(deleted)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class _OwnerAllowRules:
    """The `(tool_name, content) -> bool` callable for one owner.

    Holds a snapshot of that owner's rules, indexed by tool name, and refreshes
    it when :data:`SNAPSHOT_TTL_SECONDS` has passed. Never raises: the gate reads
    a raised exception as "no rule" already, but a store that cannot answer must
    not be able to make an agent run fail either.
    """

    __slots__ = ("_owner", "_by_tool", "_loaded_at")

    def __init__(self, owner: str) -> None:
        self._owner = owner
        self._by_tool: Optional[Dict[str, Tuple[Tuple[str, str, str], ...]]] = None
        self._loaded_at = 0.0

    def _load(self) -> Dict[str, Tuple[Tuple[str, str, str], ...]]:
        cdb = _database()
        db = cdb.SessionLocal()
        try:
            rows = (
                db.query(cdb.ToolAllowRule)
                .filter(cdb.ToolAllowRule.owner == self._owner)
                .limit(MAX_RULES_PER_OWNER)
                .all()
            )
            by_tool: Dict[str, List[Tuple[str, str, str]]] = {}
            for row in rows:
                tool = normalize_tool_name(row.tool_name)
                kind = normalize_match_kind(row.match_kind)
                if not tool or not kind:
                    # A row the matcher could not evaluate is skipped rather
                    # than guessed at.
                    continue
                by_tool.setdefault(tool, []).append(
                    (str(row.id), kind, normalize_pattern(row.pattern))
                )
            return {tool: tuple(rules) for tool, rules in by_tool.items()}
        finally:
            db.close()

    def _snapshot(self) -> Dict[str, Tuple[Tuple[str, str, str], ...]]:
        now = time.monotonic()
        if self._by_tool is not None and (now - self._loaded_at) < SNAPSHOT_TTL_SECONDS:
            return self._by_tool
        try:
            loaded = self._load()
        except Exception:
            # No rules, not the last rules that worked. A store that errors must
            # never become a store that allows, and an unreachable database is
            # exactly when a stale grant would be least visible.
            logger.debug("Allow-rule snapshot load failed", exc_info=True)
            loaded = {}
        self._by_tool = loaded
        self._loaded_at = now
        return loaded

    def _record_use(self, rule_id: str) -> None:
        """Stamp the rule that matched, so a person can see it is still in use.

        Recency only — see the column's note in `core/database.py` for why there
        is no counter. The match already happened and the rule already exists,
        so failing to write the stamp is not a reason to withhold the grant:
        this swallows everything and the caller still gets its True.
        """
        try:
            cdb = _database()
            db = cdb.SessionLocal()
            try:
                db.query(cdb.ToolAllowRule).filter(
                    cdb.ToolAllowRule.id == rule_id
                ).update(
                    {"last_used_at": cdb.utcnow_naive()},
                    synchronize_session=False,
                )
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("Allow-rule use not recorded", exc_info=True)

    def __call__(self, tool_name: Any, content: Any = None) -> bool:
        try:
            tool = normalize_tool_name(tool_name)
            if not tool:
                return False
            rules = self._snapshot().get(tool)
            if not rules:
                return False
            for rule_id, kind, pattern in rules:
                if rule_matches(kind, pattern, content):
                    self._record_use(rule_id)
                    return True
            return False
        except Exception:
            logger.debug("Allow-rule lookup failed", exc_info=True)
            return False


def allow_rule_lookup_for(
    *,
    owner: Any,
    session_id: Any = None,
) -> Optional[Callable[[Any, Any], bool]]:
    """The lookup `src/agent_loop.py` hands to `ToolRunSecurityContext`.

    Returns a callable answering ``lookup(tool_name, content) -> bool``, or
    ``None`` when there is no owner to scope rules to — which the gate reads as
    "no rules", so an ownerless run is gated exactly as it was before this
    module existed.

    ``session_id`` is accepted because the caller's contract passes it and is
    deliberately unused: rules are owner-scoped, so they outlive the chat that
    created them, stay listed after it is archived, and can be revoked from
    anywhere. A session-scoped rule would be a per-session grant that nothing
    lists once the session is gone — the complaint `P7-09` exists to answer.

    Builds the callable without touching the database: an owner with no rules
    should not cost a query at run start, and a store that is unreachable at
    run start should not be a run that fails to start.
    """
    owner_key = normalize_owner(owner)
    if not owner_key:
        return None
    return _OwnerAllowRules(owner_key)
