# SPDX-License-Identifier: AGPL-3.0-or-later
"""`P24` · Agents — the hall of hireable agents.

An agent is one file that describes a job (`AGENT.md`, `manifest.py`); a hire is
one row saying who switched it on and with what (`hires.py`). A run of a hire is
an ordinary task run whose slot carries the agent's tools, skills, inputs and
notebook (`runtime.py`). The catalogue is two layers, shipped and per person
(`catalogue.py`). `D-2026-10-22-01` holds the owner's calls.
"""
