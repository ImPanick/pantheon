# SPDX-License-Identifier: AGPL-3.0-or-later
# services/__init__.py
"""Service packages the chat core uses: search, memory and skills, hwfit,
faces, speech, YouTube.

`B1470`. This file used to import five facade classes — `SearchService`,
`DocsService`, `ResearchService`, `MemoryService`, `ShellService` — eagerly, on
every `services.*` import. Nothing in the product used any of them (each had a
canonical implementation in `src/` that the routes call), and `services/research/`
was a diverged copy of `src/research_handler.py`. They are gone; import the
submodule you need.
"""
