# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P2-18` — the feature-flag story, re-measured, and the one part still live.

The row reads: *"`deep_research` defaults off, the frontend hides four buttons,
and **no server route checks it**. Either enforce server-side or delete the
three flags with zero consumers. Flip `deep_research` on."*

**Three of those four clauses are dead, measured 2026-09-19:**

* *"no server route checks it"* — false since `H05` (2026-09-07). Four routers
  carry `require_feature` as a router-level dependency, research among them,
  and `feature_disabled_tools` removes the research tools from the agent.
  `D-2026-08-26-06` also decided **"no server-side enforcement"**; `H05` is
  newer, better evidenced, and overruled it for the reason the flag exists —
  the agent could call the tool regardless. The decision line is superseded and
  is reported rather than quietly ignored.
* *"delete the three flags with zero consumers"* — void. `web_fetch`, `memory`
  and `rag` all have consumers now.
* *"the frontend hides four buttons"* — was already refuted by
  `P2-CORRECTED`; the count is re-measured below rather than restated.

**What was live is the default**, and it stopped being cosmetic the moment
`H05` landed. This file is what makes the flip mean something: a test that
only asserts a constant is a test of a constant.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_two_shipped_defaults_no_longer_disagree():
    """The actual contradiction. The product shipped a per-user privilege
    granting research to everybody and an instance flag taking it from
    everybody, and the instance flag won."""
    from core.auth import DEFAULT_PRIVILEGES
    from src.settings import DEFAULT_FEATURES

    assert DEFAULT_PRIVILEGES["can_use_research"] is True
    assert DEFAULT_FEATURES["deep_research"] is True


def test_a_fresh_install_leaves_the_research_tools_with_the_agent():
    """The half the row is really about: a flag the model does not honour is a
    label. On the shipped defaults it now honours all eight by removing
    nothing."""
    from src.settings import DEFAULT_FEATURES
    from src.tool_security import feature_disabled_tools

    assert feature_disabled_tools(dict(DEFAULT_FEATURES)) == set()
    off = dict(DEFAULT_FEATURES, deep_research=False)
    assert feature_disabled_tools(off) == {"trigger_research", "manage_research"}


def test_the_http_gate_passes_on_the_shipped_defaults_and_refuses_when_off(monkeypatch):
    """Driven, not grepped (`Law 20`): the dependency is called."""
    from fastapi import HTTPException

    import src.feature_gate as fg
    from src.settings import DEFAULT_FEATURES

    guard = fg.require_feature("deep_research", label="Deep research")

    monkeypatch.setattr("src.settings.load_features", lambda: dict(DEFAULT_FEATURES))
    assert guard() is None

    monkeypatch.setattr("src.settings.load_features",
                        lambda: dict(DEFAULT_FEATURES, deep_research=False))
    with pytest.raises(HTTPException) as exc:
        guard()
    assert exc.value.status_code == 403
    # Names who can undo it — off must not read as broken — and, since
    # `P23-03`, where (Doc 2 § 5 rule 7).
    assert "an admin can turn it back on in settings → agent tools" in exc.value.detail.lower()


def test_the_research_router_carries_the_gate_for_every_route_it_has():
    """`H05` mounted it on the ROUTER, and that is the claim worth pinning: a
    route added to this file tomorrow inherits the gate instead of having to
    remember it. Read off the built router object, not the source text."""
    import routes.research.research_routes as rr

    router = rr.setup_research_routes(research_handler=None, session_manager=None)
    names = {
        getattr(getattr(d, "dependency", None), "__name__", "")
        for d in (router.dependencies or [])
    }
    assert "require_feature_deep_research" in names, names
    assert router.routes, "a router-level gate over no routes proves nothing"


def test_the_frontend_names_four_ids_and_one_of_them_does_not_exist():
    """*"The frontend hides four buttons"*, re-measured. Until `P23-03` it named
    four, and `overflow-research-btn` was in none of the markup — the
    refutation `P2-CORRECTED` recorded. The one visibility table
    (`static/js/ui_visibility.js` `TOOL_VISIBILITY`) names the doors it hides
    now, read off the running module; every one of them is in the page, and
    the rail twin the old map missed for the person's column is among them."""
    import json as _json
    import shutil as _shutil
    import subprocess as _sp
    if not _shutil.which("node"):
        pytest.skip("node binary not on PATH")
    uri = (ROOT / "static" / "js" / "ui_visibility.js").as_uri()
    proc = _sp.run(["node", "--input-type=module", "-e",
                    f"const V = await import({_json.dumps(uri)});"
                    "const d = V.TOOL_VISIBILITY.research;"
                    "console.log(JSON.stringify([...d.doors, ...d.composer, ...d.quiet]));"],
                   capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    ids = _json.loads(proc.stdout)
    assert set(ids) == {"tool-research-btn", "rail-research", "research-toggle-btn"}, ids

    html = "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((ROOT / "static").glob("*.html")))
    missing = [i for i in ids if f'id="{i}"' not in html]
    assert missing == [], missing
