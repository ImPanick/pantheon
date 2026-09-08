# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test that APIKeyManager.save() uses atomic write to prevent data loss."""
import os
import json
import pytest
from unittest.mock import patch, mock_open
from src.api_key_manager import APIKeyManager


def _tmp_siblings(directory):
    return sorted(p.name for p in directory.iterdir() if ".tmp" in p.name)


def test_save_creates_atomic_tmp_file(tmp_path):
    """Verify save() writes to a temp file and replaces atomically."""
    mgr = APIKeyManager(str(tmp_path))
    mgr.save("openai", "sk-test")

    # The final file should exist with the correct content
    assert os.path.exists(mgr.api_keys_file)
    with open(mgr.api_keys_file, "r", encoding="utf-8") as f:
        keys = json.load(f)
    assert "openai" in keys

    # No temp sibling may remain after a successful save. `P3-16` moved this
    # from `core/atomic_io`, whose temp name carries a random suffix — two
    # concurrent savers must not race for one rename target — so the check is
    # "nothing left behind" rather than one hard-coded filename.
    assert _tmp_siblings(tmp_path) == []


def test_save_preserves_existing_keys_atomically(tmp_path):
    """Verify atomic save doesn't corrupt other providers' keys."""
    mgr = APIKeyManager(str(tmp_path))
    mgr.save("openai", "sk-openai")
    mgr.save("anthropic", "sk-anthropic")

    loaded = mgr.load()
    assert loaded["openai"] == "sk-openai"
    assert loaded["anthropic"] == "sk-anthropic"


def test_save_preserves_original_on_write_failure(tmp_path):
    """If the temp file write fails, the original keys file must survive intact."""
    mgr = APIKeyManager(str(tmp_path))
    mgr.save("openai", "sk-original")

    # Now attempt a save that will fail during json.dump
    with patch("builtins.open", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            mgr.save("anthropic", "sk-new")

    # Original file must still be intact with the original key
    loaded = mgr.load()
    assert loaded == {"openai": "sk-original"}
    assert "anthropic" not in loaded


def test_save_cleans_up_tmp_on_failure(tmp_path):
    """Temp file should be removed if the write fails."""
    mgr = APIKeyManager(str(tmp_path))
    mgr.save("openai", "sk-original")

    # Force a failure after the temp file is opened
    original_open = open

    def failing_open(*args, **kwargs):
        f = original_open(*args, **kwargs)
        # `.tmp.` rather than a trailing `.tmp`: `P3-16` routed this through
        # `core/atomic_io`, whose temp name is `<path>.tmp.<uuid>`. Matched on
        # the old spelling this injected no failure at all, and the test passed
        # by asserting that a file which was never created does not exist.
        if args and isinstance(args[0], str) and ".tmp." in args[0]:
            f.close()
            raise OSError("simulated write failure")
        return f

    with patch("builtins.open", side_effect=failing_open):
        with pytest.raises(OSError):
            mgr.save("anthropic", "sk-new")

    # Whatever temp file it used must be gone.
    assert _tmp_siblings(tmp_path) == []

    # Original should be intact
    loaded = mgr.load()
    assert loaded == {"openai": "sk-original"}
