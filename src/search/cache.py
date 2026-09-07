# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compatibility wrapper for the canonical services.search.cache module.

``src.search.cache`` stays importable for older agent/deep-research code, but the
implementation now lives in ``services.search.cache`` so the two cannot drift.
"""

import sys

from services.search import cache as _cache

sys.modules[__name__] = _cache
