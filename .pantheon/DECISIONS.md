# DECISIONS — settled, with the reasoning that settled them

Recorded so no agent re-litigates them and no reviewer flags them as oversights.
Each entry names what was decided, what it costs, and what would reopen it.

---

## D-2026-08-26-01 · P2-01 — delete `is_safe_file_type` entirely

**Decided:** delete the function and its call site whole. Both blocklists go: the
9 blocked MIME types *and* the 9 blocked extensions
(`.exe .dll .bat .cmd .vbs .ps1 .jsp .asp .aspx`).

**Why this is defensible and not just permissive.** The scouts verified all four
load-bearing facts against the source:

- **Nothing on the server executes an upload.** No exec path touches `UPLOAD_DIR`,
  and `UPLOAD_DIR` is not a static mount — `app.py:509` mounts only `/static`.
- Every download that names a file carries `Content-Disposition: attachment`.
- `X-Content-Type-Options: nosniff` is set, and the app CSP applies.
- `.svg` — the one genuine stored-XSS vector in this area — was **never** in either
  blocklist, so the check was not buying what it appeared to buy.

**What this costs, stated plainly.** Two things the check really did do, and now
does not:

1. The extension blocklist is libmagic-independent, so it caught `.exe` on every
   install regardless of whether python-magic was present. That goes away.
2. The `?thumb=1` branch (`routes/upload_routes.py:402`) passes no `filename=`, so it
   emits **no** `Content-Disposition` at all. "Every download carries attachment" is
   true of the named-file path, not that one.

Accepted deliberately. This is a single-admin box on a home LAN with no other users,
where the operator uploading a `.exe` is the operator who owns the machine.

**What would reopen this.** A second user account. Any route that serves an upload
without forcing disposition. Any exec path that reaches `UPLOAD_DIR`. If Pantheon
ever grows a multi-user or hosted mode, this decision is void and the check comes
back — stronger than upstream's, with `.svg` in it.

**Not in scope.** `P2-24`'s font-upload allowlist stays and gets stronger: those
files land under the static mount and are served with no forced disposition. That is
the genuine exception, and it is not affected by this decision.

---

## D-2026-08-26-02 · R-06 — stay private, close the licence gaps, flip public when ready

**Decided:** the repo stays private. `P0-14 … P0-27` — the notices, the credits and
the AGPL §13 source link — close first. Public comes after, on our timing.

**What that means for the build loop.** Agents cannot clone the fork, so until the
flip:

```
agents → read /work/base (upstream at b4d1293) → produce patches
       → cybertooth applies → commit → push
```

The desktop bridge stays on the critical path for writes. It has dropped three
times, so every batch of agent work lands as a reviewable patch rather than a live
edit, and nothing is left half-applied when the link goes.

**Why this is the right order anyway.** The §13 source link is not paperwork — it is
the one obligation that attaches the moment other people can reach the software.
Publishing first and fixing after would mean shipping the fork in exactly the state
the audit was written to prevent.

**What would reopen this.** Nothing in the plan. The flip is a P0 completion event,
not a decision to revisit.

---

## D-2026-08-26-03 · The themes stay, and so do the animated backgrounds

**Decided:** Odysseus's theme system is kept intact — all 16 built-in themes, the 8 custom
slots, and the per-theme animated backgrounds. This is a **keep**, and it constrains
everything downstream that touches colour.

**What is protected, precisely.**

- The 16 entries in `THEMES` (`static/js/theme.js:11`) and their `bg / fg / panel / border
  / red` values. Tune a value if it is genuinely wrong; do not restyle a theme wholesale
  and do not remove one.
- `THEME_DEFAULT_PATTERN` — the map that gives each theme its own background. This is the
  feature that makes the themes feel authored rather than recoloured: `midnight` gets
  rain, `cyberpunk` gets synapse, `forest` gets petals, `ocean` gets constellations,
  `terminal` gets perlin-flow, `retrowave` gets embers, `cute` gets sparkles.
- The 8 patterns and their machinery: `_BG_CLASSES`, `_CANVAS_PATTERNS`, the seven
  `createElement('canvas')` animators, the `bg-pattern-*` classes and the `*-canvas`
  element ids. `dots` is the CSS-only one (`style.css:209`); the other seven are canvas.
- The per-theme controls layered on top: `--bg-effect-color`, `--bg-effect-intensity`,
  `--bg-effect-size`, and the frosted toggle.

**What this cost — and it was worth finding.** `P1-01`, the headline task of the entire
token phase, was written as *"define `--accent` in `:root`"*. Auditing it against this
decision showed it would have destroyed the thing being protected:

Of the 799 `var(--accent…)` sites in `style.css`, **508 are `var(--accent, var(--red))`**.
They resolve today to the theme's own `red`, which `applyTheme()` sets at
`static/js/theme.js:263`. A `:root` definition beats a fallback — so all 508 would have
flipped to one global colour, and all 16 themes would have converged on it in one commit.
The task would have reported success. Every screenshot would have looked deliberate.

`P1-01` now sets `--accent` **per theme**, seeded from that theme's `red`, one line inside
`applyTheme()`. The 508 fallback sites resolve to exactly what they resolve to now, the
bare sites resolve for the first time, and each theme keeps its identity. Strictly better
than the original plan, and it costs less.

**Still allowed.** `P10-04` (contrast audit across all 16 themes) and `P10-05`
(reduced-motion guard over the 7 animators) both stand. A reduced-motion guard **respects
an operating-system setting** — it does not disable the feature, and an agent that reads
it that way has misread it. New themes may be added; new patterns may be added.

**What would reopen this.** Nothing. This is a product decision, not a technical one.

