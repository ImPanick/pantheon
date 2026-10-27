# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B471` — "Forge" is this product's serving subsystem; Stable Diffusion WebUI
Forge, the third-party image backend it detects, is always spelled out, and
from one place.

`D-2026-08-26-05` renamed the Cookbook to the Forge, and the owner has kept the
noun since. The collision the row found was real: the process detector listed
the backend as `"Forge WebUI"`, and the gallery's img2img refusal named it
`SD-Forge` beside *"Serve a diffusion model in Forge → Launch"* — two
spellings, each chosen at its call site, which is the defect class (`Law 13`).
Now `src/image_model_ids.SD_FORGE_LABEL` is the one spelling and both read it.

Measured while doing it: the detector matched A1111's `webui.sh` needle before
Forge's entry was reached — SD WebUI Forge launches through its own
`webui.sh` — so a running SD WebUI Forge was reported as "A1111 WebUI". Its
entry comes first now.
"""
import ast
import re
import subprocess
from pathlib import Path

import pytest

from src.image_model_ids import SD_FORGE_LABEL
from src.tools.cookbook import model_process_label

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("cmdline,label", [
    ("python /opt/stable-diffusion-webui-forge/launch.py --listen", SD_FORGE_LABEL),
    ("bash /home/ana/stable-diffusion-webui-forge/webui.sh --api", SD_FORGE_LABEL),
    ("bash /home/ana/stable-diffusion-webui/webui.sh --api", "A1111 WebUI"),
    ("python -m vllm.entrypoints.openai.api_server --model q", "vLLM"),
    ("/usr/bin/sshd -D", ""),
])
def test_the_detector_names_each_backend_once_and_right(cmdline, label):
    assert model_process_label(cmdline) == label


def test_the_gallery_refusal_names_the_backend_and_the_subsystem_apart(monkeypatch):
    """The sentence a person reads when image generation has just refused:
    the backend by its full name, the subsystem as the door."""
    source = (ROOT / "routes" / "gallery" / "gallery_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    refusals = [node for node in ast.walk(tree)
                if isinstance(node, ast.JoinedStr)
                and "Harmonize needs a diffusion server" in ast.unparse(node)]
    assert len(refusals) == 1
    text = eval(compile(ast.Expression(refusals[0]), "gallery", "eval"),  # noqa: S307
                {"SD_FORGE_LABEL": SD_FORGE_LABEL})
    assert SD_FORGE_LABEL in text and "Serve a diffusion model in Forge → Launch." in text
    assert "SD-Forge" not in text


def _string_constants(rel: str) -> list:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_no_shipped_string_spells_the_backend_another_way():
    """Every Python string the product ships: the backend's name appears as
    `SD_FORGE_LABEL` in its one home and nowhere else, and neither of the old
    spellings survives."""
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    shipped = [f for f in files if f.startswith(("src/", "routes/", "services/", "core/"))
               or f in ("app.py",)]
    other = re.compile(r"Forge WebUI|SD-Forge")   # the labels; the process needles are lower-case paths
    spelled, homes = [], []
    for rel in shipped:
        for value in _string_constants(rel):
            if other.search(value):
                spelled.append((rel, value[:80]))
            if value == SD_FORGE_LABEL:
                homes.append(rel)
    assert spelled == []
    assert homes == ["src/image_model_ids.py"]
