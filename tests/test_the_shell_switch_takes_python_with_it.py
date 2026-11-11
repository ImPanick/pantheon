# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P17-11`: the chat's shell switch is the one switch for "may the agent run
commands". `python` runs an unsandboxed subprocess (`os.system`,
`subprocess.run`), so with the shell off it is withheld too."""
import pytest


@pytest.mark.asyncio
async def test_shell_off_withholds_python(monkeypatch):
    from tests.test_the_desktop_goes_with_the_shell import _disabled

    disabled = await _disabled(monkeypatch, allow_bash="false")
    assert {"bash", "host_shell", "computer", "shell_with_login", "python"} <= set(disabled)


def test_a_promotion_without_the_shell_withholds_python():
    from routes.chat_helpers import escalation_withholds

    withheld = escalation_withholds(promoted=True, workspace_intent=True, allow_browser=False,
                                    browser_tools=(), shell_granted=False)
    assert "python" in withheld
