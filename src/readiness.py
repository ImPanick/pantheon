# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ithaca anchor — local-instance readiness / integrity self-check.

Beyond ``/api/health``'s liveness ping, this confirms the self-hosted instance is
whole and at home: the database is reachable, the data directory is present and
writable, and storage is local-first. Served by ``GET /api/ready`` and suitable
for an orchestrator readiness probe (200 only when every critical check passes).
"""

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

# How many saved secrets per encrypted column are tried against the key, and for
# how long a verdict stands. A wrong key fails every row alike, so a few rows say
# it; the cache keeps a 30-second health probe from decrypting images forever.
_SECRETS_SAMPLE = 5
_SECRETS_TTL_S = 60.0
_secrets_cache: Dict[str, object] = {}
_secrets_lock = threading.Lock()


def _key_written(path: str) -> Optional[str]:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc).isoformat(timespec="minutes")
    except OSError:
        return None


def check_secrets(fresh: bool = False) -> Dict[str, object]:
    """Can this process read the secrets it has saved?

    Every `EncryptedText` column (provider API keys, mail passwords, OAuth
    tokens, MCP env) is sealed with `data/.app_key`. If that file is unreadable,
    or is not the key those rows were sealed with, each of them reads as "" and
    the first sign is a provider refusing a keyless request. This tries a few
    saved values per column with the key as it is now and fails readiness when
    any can't be opened, naming the columns, so a deploy stops on it instead.
    """
    with _secrets_lock:
        cached = _secrets_cache.get("result")
        if not fresh and cached and time.monotonic() - float(_secrets_cache.get("at", 0)) < _SECRETS_TTL_S:
            return dict(cached)  # type: ignore[arg-type]

    from cryptography.fernet import InvalidToken
    from sqlalchemy import text as sql_text
    from sqlalchemy.exc import SQLAlchemyError

    from core.database import Base, EncryptedText, engine
    from src import secret_storage

    key_path = str(secret_storage._KEY_PATH)
    result: Dict[str, object] = {"ok": True, "key_file": key_path}
    try:
        fernet = secret_storage._get_fernet()
    except secret_storage.KeyUnavailable as e:
        result.update(ok=False, error=str(e))
    else:
        checked = 0
        bad: Dict[str, int] = {}
        with engine.connect() as conn:
            for table in Base.metadata.sorted_tables:
                for col in table.columns:
                    if not isinstance(col.type, EncryptedText):
                        continue
                    try:
                        rows = conn.execute(sql_text(
                            f'SELECT "{col.name}" FROM "{table.name}" '
                            f'WHERE "{col.name}" LIKE :p ORDER BY length("{col.name}") LIMIT :n'
                        ), {"p": "enc:%", "n": _SECRETS_SAMPLE}).fetchall()
                    except SQLAlchemyError:
                        continue  # table not made yet on this database
                    for (value,) in rows:
                        checked += 1
                        try:
                            fernet.decrypt(str(value)[4:].encode("ascii"))
                        except (InvalidToken, ValueError):
                            name = f"{table.name}.{col.name}"
                            bad[name] = bad.get(name, 0) + 1
        result["checked"] = checked
        if bad:
            written = _key_written(key_path)
            result.update(
                ok=False,
                undecryptable=bad,
                key_written=written,
                error=(
                    f"Saved secrets in {', '.join(sorted(bad))} can't be decrypted with "
                    f"{key_path}{f' (last written {written} UTC)' if written else ''}. "
                    "That key is not the one they were saved with: it was replaced or "
                    "regenerated, or this database came from another data folder. "
                    "Restore the original .app_key and restart, or enter those secrets again."
                ),
            )
    with _secrets_lock:
        _secrets_cache["result"] = dict(result)
        _secrets_cache["at"] = time.monotonic()
    return result


def check_readiness(auth_manager=None) -> Dict[str, object]:
    """Run the readiness checks and return a JSON-serialisable report.

    ``ready`` is True only when every critical check passes: database, data_dir,
    secrets, and (when the app's ``auth_manager`` is passed) accounts.
    ``local_first`` is informational — a remote database is a valid deployment, so
    it never fails readiness, it only reports whether storage stays on this host.
    """
    from core.constants import APP_VERSION, DATA_DIR
    from core.database import DATABASE_URL, engine
    from sqlalchemy import text as sql_text

    checks: Dict[str, Dict[str, object]] = {}

    # Database reachable — the simplest honest probe that the engine is live.
    try:
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as e:
        checks["database"] = {"ok": False, "error": str(e)}

    # Data directory present and writable — home must be able to hold its own data.
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        probe = os.path.join(DATA_DIR, f".ready_probe_{uuid.uuid4().hex}")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        checks["data_dir"] = {"ok": True, "path": DATA_DIR}
    except Exception as e:
        checks["data_dir"] = {"ok": False, "error": str(e)}

    # Accounts readable — `P3-16`: an unreadable auth.json is no users in memory,
    # so nobody can sign in. A deploy that lands in that state is not ready.
    if auth_manager is not None:
        err = getattr(auth_manager, "load_error", None)
        if err and auth_manager.retry_load():
            err = None
        checks["accounts"] = {"ok": not err} if not err else {
            "ok": False,
            "error": f"{auth_manager.auth_path} could not be read ({err}). Nobody can "
                     "sign in; the accounts in it are untouched and nothing writes to it "
                     "until it can be read.",
        }

    # Saved secrets readable with the key on disk.
    if checks["database"].get("ok"):
        try:
            checks["secrets"] = check_secrets()
        except Exception as e:
            checks["secrets"] = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}

    # Local-first: storage stays on the home machine (informational, never fatal).
    local_first = (
        DATABASE_URL.startswith("sqlite")
        or "localhost" in DATABASE_URL
        or "127.0.0.1" in DATABASE_URL
    )
    checks["local_first"] = {"ok": True, "local": local_first}

    ready = all(bool(c.get("ok")) for c in checks.values())
    return {
        "ready": ready,
        "version": APP_VERSION,
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(),
    }
