# SPDX-License-Identifier: AGPL-3.0-or-later
"""`audit-P2-onboarding`. The settings walkthrough must consider BOTH the
viewer's permissions and what is already configured.

GPT-6.1's UX audit (2026-10-24): *"Restricted-user settings displayed 'Add a
model first' despite model-setup controls being unavailable to that user. A
configured model was already selectable."*

The fix lives in `_cmdTourSettings` (`slashCommands.js`): the opener and the
model-setup steps are built from `window._isAdmin` (model endpoints and AI
defaults are admin-managed) and `_hasConfiguredModels()`. A non-admin is never
pointed at controls they cannot use, and "Add a model first" is shown only when
no model is configured yet.

Verified by lifting the `_cmdTourSettings` body and running the step-building
head of it under node with the three relevant states, rather than asserting on
a grep — the control flow is the thing under test.
"""

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "static" / "js" / "slashCommands.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _opener_and_model_steps(is_admin: bool, has_models: bool):
    """Run the real opener/modelSteps computation with these two states."""
    src = _SRC.read_text(encoding="utf-8")
    start = src.index("const canAddModels = !!window._isAdmin;")
    block = src[start:src.index("  const steps = [", start)]
    # Stub what the block reads: window._isAdmin and _hasConfiguredModels.
    js = textwrap.dedent(f"""
    const window = {{ _isAdmin: {str(is_admin).lower()} }};
    const _clickNav = () => {{}};
    async function _hasConfiguredModels() {{ return {str(has_models).lower()}; }}
    async function main() {{
      {block}
      console.log(JSON.stringify({{ opener, modelSteps: modelSteps.length }}));
    }}
    main();
    """)
    out = subprocess.run(["node", "--input-type=module", "-e", js],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    import json
    return json.loads(out.stdout.strip())


def test_a_restricted_user_is_not_told_to_add_a_model():
    got = _opener_and_model_steps(is_admin=False, has_models=True)
    assert "Add a model first" not in got["opener"]
    assert "managed by an admin" in got["opener"]
    assert got["modelSteps"] == 0, "a non-admin is never pointed at model-setup controls"


def test_a_restricted_user_with_no_model_still_is_not_pointed_at_controls():
    got = _opener_and_model_steps(is_admin=False, has_models=False)
    assert "Add a model first" not in got["opener"]
    assert got["modelSteps"] == 0


def test_an_admin_with_a_model_already_set_up_is_not_told_to_add_one():
    got = _opener_and_model_steps(is_admin=True, has_models=True)
    assert "Add a model first" not in got["opener"]
    assert "already have a model" in got["opener"]
    assert got["modelSteps"] > 0, "an admin still gets the model-setup walkthrough"


def test_an_admin_with_no_model_is_told_to_add_one():
    got = _opener_and_model_steps(is_admin=True, has_models=False)
    assert "Add a model first" in got["opener"]
    assert got["modelSteps"] > 0
