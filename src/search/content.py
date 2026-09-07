# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compatibility wrapper for the canonical services.search.content module.

``src.search.content`` stays importable for older agent/deep-research code, but the
implementation now lives in ``services.search.content`` so the two cannot drift.
"""

import sys

from services.search import content as _content

sys.modules[__name__] = _content
