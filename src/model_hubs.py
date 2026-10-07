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
