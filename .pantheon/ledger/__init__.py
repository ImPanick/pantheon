# SPDX-License-Identifier: AGPL-3.0-or-later
"""The evidence behind `LEDGER.md`.

`P19`. The ledger is **generated** from `claims.py` — it is never edited by hand,
because a hand-edited ledger is the second place every fact in
`.pantheon/ROADMAP.md` lives, and that is the defect `Law 13` names.

`source` is the other half of this package: how every checker reads the tree —
`tracked_files()` (each path once, `B571`) and the one comment blanker
(`B410`). Shared checker code lives here so there is one copy of it.
"""
