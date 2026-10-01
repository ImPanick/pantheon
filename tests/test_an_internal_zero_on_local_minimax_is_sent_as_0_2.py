# SPDX-License-Identifier: AGPL-3.0-or-later
"""`B936` — a 0 asked for by an internal caller is sent to a local MiniMax as 0.2.

The local MiniMax profile wrote `min(float(t or 0.2), 0.2)`, so a falsy 0 read
as *missing*: mail triage (`routes/email_pollers.py`, `temperature=0`),
calendar parsing (`0.0`) and the research and tool-selection classifiers asked
for greedy decoding and a local MiniMax was sent 0.2. `P2-13` left it byte for
byte, because every path nobody chose had to stay as it was, and said so.

**Decided, and kept** (`llm_core._minimax_profile_temperature`): the callers
that ask for 0 are unattended internal jobs, greedy decoding is the classic
repetition-loop trigger the profile exists to stop, and the failure is a loop
on the owner's GPU running to `max_tokens` with nobody watching. What changed
is that it is a stated rule rather than an `or`, and that it is no longer
silent — the run receipt records the 0.2 that was sent (`B933`). A person who
chooses 0 is honoured, as every chosen temperature is (`P2-13`), and off the
local MiniMax profile a 0 is sent as 0.

These tests pin the decision on the wire, through the three entry points with
only the socket faked (`Law 20`). They pass on the tree before the row — the
decision keeps its behaviour — and the mutation that makes the other choice
(`is None`) reddens them.
"""
import pytest

from test_a_receipt_records_what_the_model_was_sent import (  # noqa: E402
    LOCAL, MINIMAX, _llm_call, _llm_call_async, _stream_llm, every_socket, wire,  # noqa: F401
)

DOORS = [_llm_call, _llm_call_async, _stream_llm]
IDS = ["llm_call", "llm_call_async", "stream_llm"]
CHOSEN = frozenset({"temperature"})


def _sent(socket):
    (_url, payload), = socket.sent
    return payload


@pytest.mark.parametrize("door", DOORS, ids=IDS)
@pytest.mark.parametrize("zero", [0, 0.0], ids=["int", "float"])
def test_an_internal_zero_is_sent_as_the_profiles_0_2(every_socket, door, zero):
    door(LOCAL, MINIMAX, temperature=zero, max_tokens=200)
    assert _sent(every_socket)["temperature"] == 0.2


@pytest.mark.parametrize("door", DOORS, ids=IDS)
def test_a_zero_the_person_chose_is_sent_as_zero(every_socket, door):
    door(LOCAL, MINIMAX, temperature=0.0, max_tokens=200, explicit_params=CHOSEN)
    assert _sent(every_socket)["temperature"] == 0.0


@pytest.mark.parametrize("asked,sent", [(0.1, 0.1), (0.2, 0.2), (0.7, 0.2), (1.0, 0.2)],
                         ids=["under", "at", "over", "default"])
def test_anything_above_zero_is_held_to_at_most_0_2(every_socket, asked, sent):
    _llm_call(LOCAL, MINIMAX, temperature=asked, max_tokens=200)
    assert _sent(every_socket)["temperature"] == sent


@pytest.mark.parametrize("url,model", [
    ("https://api.minimax.io/v1/chat/completions", MINIMAX),
    (LOCAL, "qwen2.5-7b-instruct"),
], ids=["cloud-minimax", "local-other-model"])
def test_off_the_local_minimax_profile_a_zero_is_sent_as_zero(every_socket, url, model):
    _llm_call(url, model, temperature=0, max_tokens=200)
    assert _sent(every_socket)["temperature"] == 0
