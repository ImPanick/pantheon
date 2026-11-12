# SPDX-License-Identifier: AGPL-3.0-or-later
"""`DATA_DIR/mcp_oauth` is an install record, like `DATA_DIR/ssh`.

It holds the Gmail OAuth client secret and refresh token (`MCP_OAUTH_DIR`).
`_is_install_record` guarded the data directory's top-level files and `ssh/`
only, so `read_file` resolved the refresh token and `grep`/`glob` listed it.
"""
import pytest


def test_mcp_oauth_is_refused_like_ssh(tmp_path, monkeypatch):
    import src.constants as constants
    import src.tool_execution as te

    data = tmp_path / "data"
    (data / "ssh").mkdir(parents=True)
    (data / "mcp_oauth").mkdir()
    (data / "ssh" / "config").write_text("Host x")
    (data / "mcp_oauth" / "credentials.json").write_text('{"refresh_token": "1//secret"}')
    monkeypatch.setattr(constants, "DATA_DIR", str(data))
    with pytest.raises(ValueError):
        te._resolve_tool_path(str(data / "ssh" / "config"))
    with pytest.raises(ValueError):
        te._resolve_tool_path(str(data / "mcp_oauth" / "credentials.json"))
    with pytest.raises(ValueError):
        te._resolve_tool_path(str(data / "mcp_oauth"))
