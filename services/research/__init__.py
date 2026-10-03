# SPDX-License-Identifier: AGPL-3.0-or-later
# Apache-2.0 §4(b) change notice. This file is part of the Deep Research
# pipeline adapted from Tongyi DeepResearch (Alibaba-NLP / Tongyi Lab),
# licensed Apache-2.0. It is NOT Tongyi's original: it has been changed.
# Changed by Odysseus. Pantheon has added this notice and the SPDX line above
# (`P0-18`) and changed nothing else (measured against the fork point,
# 2026-08-27; no Pantheon row has touched it since).
#
# Upstream licence text (Tongyi DeepResearch): licenses/DeepResearch-Apache-2.0.txt
# Attribution: CREDITS.md
# This file as distributed in Pantheon: AGPL-3.0-or-later, see LICENSE.

# services/research/__init__.py
"""Research service — deep research with LLM-in-the-loop."""

from .service import ResearchService, ResearchResult, ResearchSource
from .research_handler import ResearchHandler

__all__ = [
    "ResearchService",
    "ResearchResult",
    "ResearchSource",
    "ResearchHandler",
]
