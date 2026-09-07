# SPDX-License-Identifier: AGPL-3.0-or-later
# services/shell/__init__.py
"""Shell service — safe command execution."""

from .service import ShellService, ShellResult

__all__ = ["ShellService", "ShellResult"]
