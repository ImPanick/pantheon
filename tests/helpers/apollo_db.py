# SPDX-License-Identifier: AGPL-3.0-or-later
"""A temp database for Apollo's tests, bound where Apollo's code reads it."""
from __future__ import annotations

import pytest


@pytest.fixture
def apollo_db(monkeypatch):
    """`SessionLocal` over a fresh temp sqlite with every table, bound onto
    `core.database`. Yields the session factory."""
    import core.database as database
    from tests.helpers.sqlite_db import make_temp_sqlite

    SessionLocal, engine, tmp = make_temp_sqlite(database.Base.metadata)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal)
    import routes.apollo_routes as apollo_routes
    monkeypatch.setattr(apollo_routes, "SessionLocal", SessionLocal)
    yield SessionLocal
    engine.dispose()
