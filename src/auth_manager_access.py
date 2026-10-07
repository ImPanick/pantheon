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
