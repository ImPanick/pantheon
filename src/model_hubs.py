# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B1229` — may the Forge reach Hugging Face and the Ollama library?

Measured on `299bd50`: opening the Forge on a fresh install, with nothing
switched on, sent `refresh_catalog=1` and the server walked up to 40 pages of
`huggingface.co/api/collections` (`P15-05`'s budget) beside the answer, and the
same open asked `/api/cookbook/ollama/library`, which fetched
`ollama.com/search`. `Law 16`'s test is exactly that install: nothing should
reach the public internet. The owner's ruling, 2026-10-07: *"hugging face
should be toggleable inside the admin settings, along with how the LLM is
served etc."*

So one instance setting, `forge_model_hubs`, shipped off, and this module is
the one place anything asks it (`Law 7`). It gates every request the Forge
makes to those two hosts — the catalog refresh, the image collections, the
trending list, the GGUF file list, the agent's model lookup, the Ollama
library — and a download a person starts by hand, which says so and names the
switch instead of reaching out. Off, the Forge lists the models it already
knows: the bundled catalog, the last refresh it made, and what is on disk.

`OutboundHostLimiter` is untouched (`FORBIDDEN.md` Part 2): with the switch on,
every one of these calls is paced exactly as before.
"""
from __future__ import annotations

SETTING = "forge_model_hubs"

# The hosts the switch governs, by name. The panel and the tests read this;
# the call sites name their own URLs as they always did.
HOSTS = ("huggingface.co", "ollama.com")

# What a person reads when something the switch governs is refused: what
# happened, then what to do, naming the control by its label (Doc 2 § 5, 7).
OFF_SENTENCE = ("Hugging Face and Ollama are off. "
                "An admin turns them on in Settings → Forge.")


class ModelHubsOff(RuntimeError):
    """Raised by a lookup that would have reached a model hub with the switch off."""

    def __init__(self) -> None:
        super().__init__(OFF_SENTENCE)


def allowed() -> bool:
    """True only when an admin has switched the hubs on.

    `is True`, not truthiness: the POST route stores only booleans for this key,
    and a hand-edited `"false"` in `settings.json` must not read as yes.
    """
    from src.settings import get_setting

    return get_setting(SETTING, False) is True


def require() -> None:
    """Raise `ModelHubsOff` unless the hubs are on."""
    if not allowed():
        raise ModelHubsOff()


# ── `B1259`: a serve with the switch off fetches nothing ───────────────────
#
# The owner, 2026-10-07 (`D-2026-10-07-02` §1): *"With the Forge's hub switch
# off, serving a model that is not on disk does not let the engine fetch it."*
# `B1229` gated every lookup and every download, but a serve names a model and
# the engine fetches what it does not have: `vllm serve <repo>`, SGLang and
# `mlx_lm.server` download from Hugging Face, `llama-server -hf <repo>` does,
# `ollama pull`/`ollama run` pull from ollama.com. Off, two things hold:
#
#   * a command whose only job is to fetch — llama.cpp's hub flags, Ollama's
#     `pull`/`run` — is refused before a script exists, with `OFF_SENTENCE`;
#   * every other serve script runs with the hubs' own offline switches
#     exported (`HF_HUB_OFFLINE=1` and its two siblings), and a repo id the
#     command names that is not in this machine's Hugging Face cache stops the
#     script before the engine starts, saying so.
#
# On, nothing here runs: a serve behaves exactly as before.

import os as _os
import re as _re
import shlex as _shlex

# llama.cpp (`llama-server`, `llama-cli`) and llama-cpp-python's server: the
# flags that name a remote model for the engine to download.
SERVE_FETCH_FLAGS = frozenset({
    "-hf", "--hf-repo", "-hfr", "-hff", "--hf-file",
    "-hfd", "-hfrd", "--hf-repo-draft", "-hfv", "-hfrv", "--hf-repo-v",
    "-hffv", "--hf-file-v", "-mu", "--model-url", "--hf_model_repo_id",
})

# The environment the Hugging Face libraries read to stay off the network
# (`huggingface_hub`, `transformers`, `datasets`) — what vLLM, SGLang, MLX and
# the diffusers servers load models through.
OFFLINE_ENV = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")

_HF_REPO_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def _tokens(cmd: str) -> list:
    try:
        return _shlex.split(cmd or "")
    except ValueError:
        return (cmd or "").split()


def serve_fetches(cmd: str) -> bool:
    """Whether a serve command asks its engine to fetch a model by itself."""
    tokens = _tokens(cmd)
    for i, tok in enumerate(tokens):
        if tok.split("=", 1)[0] in SERVE_FETCH_FLAGS:
            return True
        if _os.path.basename(tok) == "ollama" and i + 1 < len(tokens) and tokens[i + 1] in ("pull", "run"):
            return True
    return False


def names_hub_repo(cmd: str, repo_id: str) -> bool:
    """Whether `cmd` hands `repo_id` to its engine as a hub id — the bare token
    (`vllm serve org/name`, `--model-path org/name`, `--model=org/name`), not a
    path on disk that happens to contain it."""
    repo_id = (repo_id or "").strip()
    if not _HF_REPO_RE.match(repo_id):
        return False
    for tok in _tokens(cmd):
        if tok == repo_id or (tok.startswith("-") and tok.split("=", 1)[-1] == repo_id and "=" in tok):
            return True
    return False


def offline_runner_lines(cmd: str, repo_id: str) -> list:
    """The bash lines a serve script runs with the switch off."""
    lines = [
        "# `B1259`: Hugging Face and Ollama are off (Settings → Forge), so the",
        "# engine reads only what is on this machine.",
        *(f"export {name}=1" for name in OFFLINE_ENV),
    ]
    if names_hub_repo(cmd, repo_id):
        cache_dir = "models--" + repo_id.strip().replace("/", "--")
        lines += [
            '_pan_hub="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"',
            f'if [ -z "$PANTHEON_PREFLIGHT_EXIT" ] && [ ! -d "$_pan_hub/{cache_dir}" ]; then',
            f"  echo {_shlex.quote(repo_id.strip() + ' is not on this machine. ' + OFF_SENTENCE)}",
            "  PANTHEON_PREFLIGHT_EXIT=1",
            "fi",
        ]
    return lines


def _ps_text(text: str) -> str:
    """A PowerShell double-quoted string that says `text` whatever code page
    reads the script. The serve script is written as UTF-8 without a BOM, which
    Windows PowerShell 5.1 reads as the ANSI code page, so the sentence's "→"
    would print as "â†’"; each non-ASCII character is spelled `$([char]0x…)`.
    `` ` ``, `$` and `"` are escaped with a backtick."""
    out = []
    for ch in text:
        if ch in '`$"':
            out.append("`" + ch)
        elif ord(ch) > 0x7E or ord(ch) < 0x20:
            out.append(f"$([char]0x{ord(ch):04X})")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def offline_powershell_lines(cmd: str = "", repo_id: str = "") -> list:
    """The PowerShell lines a Windows serve script runs with the switch off.

    `B1267`: the same stop as `offline_runner_lines`. With only the three
    `*_OFFLINE` variables, a serve naming a repo that is not in the cache was
    still refused — by `huggingface_hub` itself — but the person read the
    engine's offline traceback instead of the switch's sentence. So the cache
    is looked for where `huggingface_hub` looks on Windows (`HF_HUB_CACHE`,
    else `HF_HOME\\hub`, else `~\\.cache\\huggingface\\hub` — the bash lines'
    order), and a repo that is not there stops the script before the engine
    starts, with the exit line the Forge reads (`=== Process exited with code
    1 ===`). `cmd`/`repo_id` default empty so a caller that passes neither
    keeps the old three lines (`Law 1`).
    """
    lines = [f"$env:{name} = '1'" for name in OFFLINE_ENV]
    if names_hub_repo(cmd, repo_id):
        cache_dir = "models--" + repo_id.strip().replace("/", "--")
        said = _ps_text(repo_id.strip() + " is not on this machine. " + OFF_SENTENCE)
        lines += [
            "# `B1259`/`B1267`: Hugging Face and Ollama are off (Settings > Forge), so the",
            "# engine reads only what is on this machine.",
            "$_panHub = if ($env:HF_HUB_CACHE) { $env:HF_HUB_CACHE } "
            "elseif ($env:HF_HOME) { Join-Path $env:HF_HOME 'hub' } "
            "else { Join-Path $HOME '.cache\\huggingface\\hub' }",
            f"if (-not (Test-Path -LiteralPath (Join-Path $_panHub '{cache_dir}'))) {{",
            f"  Write-Host {said}",
            "  Write-Host ''",
            "  Write-Host '=== Process exited with code 1 ==='",
            "  exit 1",
            "}",
        ]
    return lines
