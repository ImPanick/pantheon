# SPDX-License-Identifier: AGPL-3.0-or-later
import os

from src.constants import DATA_DIR, PERSONAL_DIR, UPLOAD_DIR

# Cross-platform OS flag, exposed here so callers can `from src.config import
# IS_WINDOWS`. Defined locally (a trivial `os.name == "nt"`) rather than imported
# from core.platform_compat, to keep this dependency-light config module from
# dragging in the whole core/__init__ + llm_core import chain. The platform
# *helper functions* (safe_chmod, pid_alive, find_bash, ...) live solely in
# core.platform_compat — that remains their single source of truth. Keep platform
# branches as small inline `if IS_WINDOWS:` deltas (never parallel *_windows.py
# files) so they stay easy to integrate with upstream changes.
IS_WINDOWS = os.name == "nt"

# ── `B550`: the second settings system, removed on its audit ─────────────────
#
# This module held `AppConfig` — `DataConfig` (11 fields), `LLMConfig` (8),
# `SearchConfig` (9) and `SecurityConfig` (6), pydantic `BaseSettings` bound to
# the `DATA_*`, `LLM_*`, `SEARCH_*` and `SECURITY_*` environment prefixes, plus
# `debug` and `log_level` — and a global `config = AppConfig()`.
#
# **The audit** (2026-10-26, AST over every tracked non-test `.py`; the test
# `tests/test_the_second_settings_system_is_gone.py` re-runs it): attribute
# reads `config.data|llm|search|security` — **7 sites, all inside this file**:
# the four directory paths in `create_directories()` and `llm.default_host` /
# `llm.openai_api_key` in `validate_config()`, whose two branches were both
# `pass`. The one importer outside, `app.py`, passed `config` to
# `setup_search_routes`, whose body referenced the parameter zero times. No
# `config.debug` / `config.log_level` read anywhere. `git grep -w` for each of
# the 34 `PREFIX_FIELD` environment names outside this file found them only in
# the tracker. So 36 declared fields configured nothing, four environment
# prefixes an operator could set did nothing (`P17-09`'s failure at the scale of
# a module) — and worse than nothing: a malformed `LLM_REQUEST_TIMEOUT` or
# `DATA_MAX_UPLOAD_SIZE` in the environment failed pydantic validation at import
# and stopped the app booting, for a value nothing would have read. Two of the
# dead fields were byte caps (`data.max_upload_size`, `security.max_file_size`,
# 10 MB each) that read as upload ceilings and enforced none; the live ones are
# `src/upload_limits.py`'s. `P2-03` deleted two zero-reader blocks from this file
# on the same evidence (`allowed_extensions`, `dangerous_file_types`), and
# `B562` labelled `SecurityConfig` before this row removed it.
#
# What ran stays: importing this module (as `app.py` does) still creates the data
# directories, from `src.constants` — the paths every reader actually uses.


def create_directories():
    """Create required directories if they don't exist.

    `B550`: the same four directories as before, read from `src.constants`
    rather than from the removed `DataConfig` copy of them. The `runbook`
    folder has no reader either; it is still made, because existing installs
    have one and a person may have put files in it (`Law 1`).
    """
    for directory in (DATA_DIR, UPLOAD_DIR, PERSONAL_DIR,
                      os.path.join(PERSONAL_DIR, "runbook")):
        os.makedirs(directory, exist_ok=True)


create_directories()
