# Changelog

All notable changes to Pantheon. Modifications relative to upstream Odysseus are
listed under **Diverged from Odysseus**, which satisfies AGPL-3.0 §5(a).

---

## [Unreleased]

### Diverged from Odysseus

Forked from `pewdiepie-archdaemon/odysseus` @ `b4d1293` (branch `dev`) on 2026-08-24.

#### Before the fork was named — local customisation (branch `custom`)
- Guardrail caps are lifted when inference runs on local, self-hosted
  infrastructure, and kept when the active model is a cloud provider. Gated on a
  per-request context variable set from the active endpoint, with env overrides.
- The degenerate-stream phrase-loop guard is env-gated and defaults off. It was
  firing on legitimate structured output — repeated bar-chart rows normalise to
  the same phrase and trip their own guard.
- Output truncation, web-fetch caps, filesystem read caps and agent round limits
  are lifted under local inference.
- The RAG MCP server gained `add_text` and `search` actions; it was previously
  write-crippled to directory registration only.
- Agent prompts gained explicit working-memory guidance so the model uses the
  RAG, memory and notes systems that already existed.
- Model-probe requests now carry the endpoint's auth token.

#### Renamed
- Project renamed to Pantheon. Env prefix, storage keys, vector collections,
  session cookie, outbound headers, CLI scripts, service names and identifiers
  all follow. See `.pantheon/ROADMAP.md` P0.

#### Added
- `.pantheon/` — the Frontier Elevation programme: roadmap, working agreement,
  do-not-touch list, deferred decisions, and per-area handoff notes.

<!-- `B25` / `D-2026-09-08-06`. A line here once read "Source link in the UI
     footer, per AGPL-3.0 §13." It never shipped. A changelog is what a
     stranger reads to audit AGPL conformance, so a false compliance claim is
     worse while this repo is private, not better — nobody can check it. The
     link is `P0-17`; it is built and left dark against a repository URL that
     ships empty, and it goes back in this file when it renders. -->

#### Changed — read this before upgrading

`B96`. **Two environment switches meant the opposite of what an operator typed,
and both are corrected. If you set either to a disabling value, this upgrade
changes what your host does.**

- **`AUTH_ENABLED`** — until now, only the literal `false` disabled
  authentication. `AUTH_ENABLED=0`, `=no` and `=off` left authentication
  **enabled**, with nothing logged and nothing in `.env.example` saying so. All
  four spellings disable it now. **If you are running with `AUTH_ENABLED=0`
  believing auth is off, it has been on, and after this upgrade it will be off —
  your instance will answer without a login.** Set `AUTH_ENABLED=true`, or unset
  it, to keep authentication. The value is also logged as a warning at the first
  check, naming the change.
- **`PANTHEON_SINGLE_USER`** — until now, only the literal `0` turned
  single-user mode off, and *it did not work either*: the value was computed at
  import into a module constant nothing read (`B150`). Unauthenticated calendar
  requests were written under `PANTHEON_FALLBACK_OWNER` regardless of what this
  was set to. It is consulted now, and `0`, `false`, `no` and `off` all turn it
  off, which makes an unauthenticated calendar request a `401` instead of a
  write under the fallback owner. **If you set this to any of those values and
  rely on the fallback owner, unset it.**

Both are the direction an operator reading `.env.example` already expected, and
neither is a sweep: the other seven switches `B91` held stay held, because
widening them would loosen a control rather than honour an intent.

#### Added
- `B95`. The three settings that could previously only be changed by
  hand-writing `data/settings.json` — `allow_model_download` (the `Law 16` gate
  on fetching a model from HuggingFace), `searxng_widen_engines` and
  `metrics_enabled` — now have controls in **Settings → System**. Each is
  three-state: *yes*, *no*, or *use the environment variable or the default*,
  and the panel says which of those three layers is answering on this host.

#### Fixed
_(populated as P1 onward lands; `B24`, `P1-12` and `P1-14` are in and
belong here the next time this section is written out.)_

---

## Upstream

For changes prior to the fork, see the Odysseus repository.
