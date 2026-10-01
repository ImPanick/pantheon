# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P20-06` — the sentence beside the network mode is what is true.

`static/js/workstation.js` under node, in the panel harness
`tests/test_the_workstation_panel_js.py` built (the page's own markup, the
shipped escaper, a recorded `fetch`). The server works out one word for the
network (`src/workstation_access.network_view`); this pins that the panel says
each one, and never says more than the word: *enforced* only when the gate
holds it, *only while sudo is off* when root can lift it, *not enforced* when
nothing holds it — with what to do — and nothing at all about a choice that
was not saved, because the server has not said anything about it yet.
"""
from __future__ import annotations

import pytest

from test_the_workstation_panel_js import (  # noqa: F401 — `sandbox` is a fixture
    ADMIN_UP, SETTINGS, _panel, _serving, sandbox)

INTERNET = "The internet, but not your local network."
FULL = ("The internet and your local network. Something an agent reads could steer it to "
        "devices on your LAN.")


def _effect(sandbox, network, chosen="internet", script_extra=""):
    status = {**ADMIN_UP, "settings": {**SETTINGS, "network": chosen}}
    if network is not None:
        status["network"] = network
    out = _panel(sandbox, _serving("st") + """
        await mod.open();
        """ + script_extra + """
        console.log(JSON.stringify(read()));
    """, st=status)
    return out["networkEffect"]


def _view(state, chosen="internet", in_force="internet", enforcement="gate"):
    return {"chosen": chosen, "in_force": in_force, "enforcement": enforcement, "state": state}


@pytest.mark.parametrize("state,enforcement,sentence", [
    ("enforced", "gate",
     "Enforced outside the workstation, so it holds even for an agent using sudo."),
    ("enforced_sudo_off", "accounts", "Enforced for workstation accounts. It holds while sudo is off."),
    ("liftable", "accounts",
     "Enforced only while sudo is off — and sudo is on, so an agent can lift it."),
])
def test_a_held_mode_says_who_holds_it_and_whether_sudo_lifts_it(sandbox, state, enforcement,
                                                                 sentence):
    assert _effect(sandbox, _view(state, enforcement=enforcement)) == f"{INTERNET} {sentence}"


def test_a_container_without_its_gate_is_told_what_to_do(sandbox):
    text = _effect(sandbox, _view("needs_recreate", in_force=None, enforcement="none"))
    assert text == (f"{INTERNET} Not enforced: this workstation was started without its network "
                    "gate. Recreate it with the current workstation overlay (docker compose up -d) "
                    "to enforce it.")


def test_a_machine_that_holds_nothing_is_not_sent_to_docker(sandbox):
    text = _effect(sandbox, _view("not_enforced", in_force=None, enforcement="none"))
    assert text == (f"{INTERNET} Not enforced: this workstation cannot hold a network mode, so it "
                    "has whatever network its machine gives it.")
    assert "docker" not in text.lower()


def test_a_mode_not_yet_in_force_names_the_one_that_is(sandbox):
    text = _effect(sandbox, _view("pending", chosen="none", in_force="internet"), chosen="none")
    assert text == ("No network at all. Installing software from the internet will fail. "
                    "Not in force yet: the workstation is still held at “Internet only”.")


def test_unknown_claims_nothing(sandbox):
    sentence = "Whether it is in force is checked when the workstation answers."
    assert _effect(sandbox, None) == f"{INTERNET} {sentence}"
    assert _effect(sandbox, _view("unknown", in_force=None, enforcement=None)) == \
        f"{INTERNET} {sentence}"


@pytest.mark.parametrize("network", [None, _view("unknown", chosen="full", in_force=None,
                                                  enforcement=None),
                                     _view("unrestricted", chosen="full", in_force="full")])
def test_full_restricts_nothing_so_it_says_only_what_it_is(sandbox, network):
    assert _effect(sandbox, network, chosen="full") == FULL


def test_a_choice_not_yet_saved_is_not_described_by_the_last_ones_state(sandbox):
    """The select moved, the save has not answered: the state the server sent
    was about *internet*, and must not be read out under *none*."""
    text = _effect(sandbox, _view("enforced"), script_extra="""
        byId('ws-network').value = 'none';
        mod._test.renderEffects(
          { ...%s, network: 'internet' }, null, %s);
    """ % (SETTINGS_JS, VIEW_JS))
    assert text == ("No network at all. Installing software from the internet will fail. "
                    "Whether it is in force is checked when the workstation answers.")


SETTINGS_JS = "{ url: 'http://workstation:7040', url_source: 'environment', token_present: true, " \
              "token_source: 'pairing', backend: 'container' }"
VIEW_JS = "{ chosen: 'internet', in_force: 'internet', enforcement: 'gate', state: 'enforced' }"


def test_a_saved_mode_is_described_by_the_answer_the_save_brings_back(sandbox):
    """Change the select: the save is followed by a check, and the check's
    answer — the mode pushed to the gate — is what the sentence then says."""
    after = {**ADMIN_UP, "settings": {**SETTINGS, "network": "none"},
             "network": _view("enforced", chosen="none", in_force="none")}
    out = _panel(sandbox, """
        let saved = false;
        respond((call) => {
          if (call.url === '/api/auth/settings') { saved = true; return { status: 200, body: {} }; }
          return { status: 200, body: saved ? after : before };
        });
        await mod.open();
        byId('ws-network').value = 'none';
        byId('ws-network').dispatchEvent({ type: 'change' });
        await settle();
        console.log(JSON.stringify(read()));
    """, before={**ADMIN_UP, "network": _view("enforced")}, after=after)
    assert out["network"] == "none"
    assert out["networkEffect"] == ("No network at all. Installing software from the internet "
                                    "will fail. Enforced outside the workstation, so it holds "
                                    "even for an agent using sudo.")
