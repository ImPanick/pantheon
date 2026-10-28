# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P23-07` (`PERF-M-15`): the `AuthManager` a policy check asks.

Five checks built their own `AuthManager()` per call — `auth.json` and
`sessions.json` read, three migrations run, two INFO lines logged. Measured by
the perf audit on `9560d50`: 91 constructions in a 3.3 s seed, 20 within 14 ms
of one workflow save. The app already holds one (`app.py`,
`app.state.auth_manager`) and every write to the user database goes through it,
so it is the current answer; the app registers it in `core.auth`.

Three answers, and the last two are what every check did before:
  * the app's manager, when one is registered;
  * a fresh read of the file, where no app registered one (another process,
    a script);
  * whatever `core.auth.AuthManager` is now, when it is not the class the
    registered one was built from — a test's fake or a stubbed `core.auth`.

`core.auth` is read here at call time, by attribute, and not imported by name
at the call sites: a `core.auth` that carries only `AuthManager` (several tests
install exactly that) must keep working, and a name imported from it would
fail inside each check's `except` and read as "not an admin".
"""


def shared_auth_manager():
    from core import auth
    factory = auth.AuthManager
    shared = getattr(auth, "_SHARED_AUTH_MANAGER", None)
    if shared is not None and type(shared) is factory:
        return shared
    return factory()


def first_admin():
    """The install's first admin — the account setup made — or `None` before
    setup (or when the user database cannot be read).

    `B1639`. The owner a record from before per-account ownership is given:
    `integrations.migrate_to_accounts` (`P27-02`) gives a connection nobody
    named one to this account, and a Knowledge-index folder listed before its
    owner was recorded is re-read under it. One answer, asked in one place."""
    try:
        users = shared_auth_manager().list_users()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("No admin list to name an owner from (%s)", exc)
        return None
    return next((u["username"] for u in users if u.get("is_admin")), None)
