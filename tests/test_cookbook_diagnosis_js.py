# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
DIAGNOSIS_JS = ROOT / "static" / "js" / "cookbook-diagnosis.js"


def test_repair_kernels_pip_spec_is_shell_quoted():
    source = DIAGNOSIS_JS.read_text(encoding="utf-8")

    assert '"kernels<0.15"' in source
    assert " --break-system-packages kernels<0.15" not in source


def test_sglang_native_dependency_diagnosis_is_exposed_to_browser():
    source = DIAGNOSIS_JS.read_text(encoding="utf-8")

    assert r"Python\.h" in source
    assert r"libnuma\.so\.1" in source
    assert "SGLang native kernel/runtime" in source
    assert "libnuma-dev python3.12-dev build-essential" in source
    assert "sglang-kernel" in source


# ── B1929: the card names an NVIDIA driver too old for the build, not a failed engine ──
#
# PyPI's torch and vLLM builds now target CUDA 13, which needs NVIDIA driver 580
# or newer. The card shows the browser's own diagnosis first (cookbookRunning.js),
# so the driver entry in routes/cookbook_helpers.py needs its twin here, ahead of
# "Engine core initialization failed", which the same vLLM output prints too and
# which offered --enforce-eager and a shorter context, neither of which helps. The
# card's own capture joins the rows tmux wrapped (-J), as the status route's does,
# or the words are split at the pane's 80 columns. cookbook-diagnosis.js imports
# DOM helpers and cannot load under node, so ERROR_PATTERNS and _diagnose are cut
# out of the source and run on their own; no fix's action is called. Ported from
# upstream Odysseus a797cee0 (#6727/#6728), which changed only the server side.

RUNNING_JS = ROOT / "static" / "js" / "cookbookRunning.js"
DRIVER = "The installed PyTorch/vLLM build needs a newer NVIDIA driver than this server has."
OLD_DRIVER_OUTPUTS = [
    "(EngineCore pid=1) ERROR [core.py:1433] RuntimeError: The NVIDIA driver on your system is too old "
    "(found version 12080). Please update your GPU driver by downloading and installing a new version\n"
    "Traceback (most recent call last):\n"
    "RuntimeError: Engine core initialization failed. See root cause above. Failed core proc(s): {}\n",
    "RuntimeError: get_cuda_view_from_cpu_tensor, /workspace/csrc/libtorch_stable/cuda_view.cu:38, "
    "cudaHostGetDevicePointer failed: CUDA driver version is insufficient for CUDA runtime version\n"
    "Traceback (most recent call last):\n",
]


def _diagnose_in_node(texts):
    if shutil.which("node") is None:
        pytest.skip("node binary not on PATH")
    source = DIAGNOSIS_JS.read_text(encoding="utf-8")
    start = source.index("export const ERROR_PATTERNS = [")
    fn = source.index("export function _diagnose(")
    end = source.index("\n}\n", fn) + 3
    code = (source[start:fn].replace("export const", "const", 1)
            + source[fn:end].replace("export function", "function", 1))
    script = code + (
        f"\nconsole.log(JSON.stringify({json.dumps(texts)}.map((text) => {{"
        " const d = _diagnose(text);"
        " return d && { message: d.message, fixes: (d.fixes || []).map((f) => f.label) }; })));"
    )
    res = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_the_card_diagnoses_torch_and_vllm_on_an_old_nvidia_driver_as_the_driver():
    for diagnosis in _diagnose_in_node(OLD_DRIVER_OUTPUTS):
        assert diagnosis == {"message": DRIVER, "fixes": []}


def test_the_cards_capture_joins_the_rows_tmux_wrapped_and_still_reads_500_lines_on_windows():
    source = RUNNING_JS.read_text(encoding="utf-8")
    (capture,) = re.findall(r"_tmuxCmd\(task, `(capture-pane [^`]*)`\)", source)
    assert capture.split()[3:] == ["-p", "-J", "-S", "-500"]
    # A Windows task has no tmux: its translation reads only the line count.
    win = source[source.index("function _winSessionCmd("):source.index("function _winPowerShellCmd(")]
    (line_count,) = re.findall(r"tmuxArgs\.match\(/(.+?)/\)", win)
    assert re.search(line_count, capture).group(1) == "500"
