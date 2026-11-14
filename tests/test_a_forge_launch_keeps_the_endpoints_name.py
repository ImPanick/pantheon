# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B2101`. A Forge launch renamed whatever endpoint sat at its address.

The Forge finds the endpoint by `base_url` alone and set `existing.name` to the
launched model's short name, over a name from Add Models, the server scan or
`manage_endpoints add`, and over a name the person gave it afterwards; and
Settings could only show the name. Now the Forge records the name it gave a row
(`forge_name`) and renames a row only while it still carries that name, and the
endpoints list in Settings renames a row in place through the PATCH route that
always took a name.

Driven (`Law 20`): the real `_auto_register_llm_endpoint` and
`_auto_register_image_endpoint` as the real `/api/model/serve` handler holds
them, over a temp database; nothing answers a probe.
"""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CMD = "llama-server -m /models/x.gguf --host 0.0.0.0 --port 8090"


@pytest.fixture
def endpoint_db(monkeypatch):
    import core.database as database
    import routes.model_routes as model_routes
    from tests.helpers.sqlite_db import make_temp_sqlite

    factory, engine, tmpfile = make_temp_sqlite(database.Base.metadata)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(model_routes, "_probe_endpoint", lambda *a, **k: None)
    yield factory
    engine.dispose()
    os.unlink(tmpfile.name)


def _held(name):
    from routes.cookbook_routes import setup_cookbook_routes

    serve = next(r.endpoint for r in setup_cookbook_routes().routes
                 if getattr(r, "path", "") == "/api/model/serve")
    return serve.__closure__[serve.__code__.co_freevars.index(name)].cell_contents


def _row(factory, ep_id):
    from core.database import ModelEndpoint

    with factory() as db:
        ep = db.get(ModelEndpoint, ep_id)
        return ep.name, ep.base_url


def _rename(factory, ep_id, name):
    from core.database import ModelEndpoint

    with factory() as db:
        db.get(ModelEndpoint, ep_id).name = name
        db.commit()


def test_a_launch_keeps_a_name_the_person_gave_and_still_names_its_own_rows(endpoint_db):
    from routes.cookbook_helpers import ServeRequest

    register = _held("_auto_register_llm_endpoint")
    ep_id = register(ServeRequest(repo_id="org/model-a", cmd=CMD), None)
    assert _row(endpoint_db, ep_id)[0] == "model-a"

    assert register(ServeRequest(repo_id="org/model-b", cmd=CMD), None) == ep_id
    assert _row(endpoint_db, ep_id)[0] == "model-b", "a name the Forge gave is still the Forge's"

    _rename(endpoint_db, ep_id, "GPU box")
    assert register(ServeRequest(repo_id="org/model-c", cmd=CMD), None) == ep_id
    assert _row(endpoint_db, ep_id)[0] == "GPU box"


def test_a_launch_on_an_endpoint_the_forge_never_named_leaves_its_name(endpoint_db):
    from core.database import ModelEndpoint
    from routes.cookbook_helpers import ServeRequest

    register = _held("_auto_register_llm_endpoint")
    ep_id = register(ServeRequest(repo_id="org/model-a", cmd=CMD), None)
    base = _row(endpoint_db, ep_id)[1]
    with endpoint_db() as db:
        db.delete(db.get(ModelEndpoint, ep_id))
        db.add(ModelEndpoint(id="scan-1", name="llama.cpp (localhost:8090)", base_url=base,
                             is_enabled=True, endpoint_kind="local"))
        db.commit()

    assert register(ServeRequest(repo_id="org/model-b", cmd=CMD), None) == "scan-1"
    assert _row(endpoint_db, "scan-1")[0] == "llama.cpp (localhost:8090)"


def test_an_image_launch_keeps_the_persons_name_too(endpoint_db):
    from routes.cookbook_helpers import ServeRequest

    register = _held("_auto_register_image_endpoint")
    req = ServeRequest(repo_id="org/pix", cmd="python scripts/diffusion_server.py --port 8191")
    ep_id = register(req, None)
    assert ep_id and _row(endpoint_db, ep_id)[0] == "pix (image)"
    _rename(endpoint_db, ep_id, "Studio")
    assert register(ServeRequest(repo_id="org/pix2", cmd=req.cmd), None) == ep_id
    assert _row(endpoint_db, ep_id)[0] == "Studio"


def test_settings_can_rename_an_endpoint_in_place():
    src = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    row = src[src.index('data-adm-ep-id="${ep.id}"'):]
    row = row[:row.index("mcp-tools-panel")]
    assert 'data-adm-rename-ep="${ep.id}"' in row and 'data-adm-ep-name="${ep.id}"' in row
    handler = src[src.index("queryAll('[data-adm-rename-ep]')"):]
    handler = handler[:handler.index("queryAll('[data-adm-ep-tools]')")]
    assert "method: 'PATCH'" in handler and "JSON.stringify({ name })" in handler
