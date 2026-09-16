# Changelog

All notable changes to Pantheon. Modifications relative to upstream Odysseus are
listed under **Diverged from Odysseus**, which satisfies AGPL-3.0 §5(a).

**Upgrading an existing instance?** Read
[Changed — read this before upgrading](#changed--read-this-before-upgrading) first. It is
the only section that can change what your host does without you editing anything: three
switches — `AUTH_ENABLED`, `PANTHEON_SINGLE_USER` and the `use_rag` field on
`POST /api/chat_stream` — used to ignore values meaning *no*, and now honour them.

---

## [Unreleased]

### Diverged from Odysseus

Forked from `pewdiepie-archdaemon/odysseus` @ `b4d1293` (branch `dev`) on 2026-08-24.

#### Before the fork was named — local customisation (branch `custom`)

The five changes below were made on one machine, under the working name *Cybertooth*,
before this became a named fork. They are what the fork was started to keep. The detail
as it was written at the time — with every stale path and variable name corrected and
dated rather than rewritten — is in [`CYBERTOOTH_CHANGES.md`](CYBERTOOTH_CHANGES.md).

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
- `B95`. The three settings that could previously only be changed by
  hand-writing `data/settings.json` — `allow_model_download` (the `Law 16` gate
  on fetching a model from HuggingFace), `searxng_widen_engines` and
  `metrics_enabled` — now have controls in **Settings → System**. Each is
  three-state: *yes*, *no*, or *use the environment variable or the default*,
  and the panel says which of those three layers is answering on this host.

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

`B152`. **`use_rag=0` meant *yes*, on the chat API. If you send `use_rag` with a
value meaning no, this upgrade changes what you get back.**

- **`use_rag`**, the form field on `POST /api/chat_stream`, is the one field in
  this API that defaults **on**, and until now only the literal `false` turned
  retrieval off. `use_rag=0`, `use_rag=no` and `use_rag=off` all turned
  retrieval **on** — a caller asked for retrieval to be skipped and got it
  anyway, with nothing logged and nothing in the API saying so. All four
  spellings turn it off now, which is the same eight-word vocabulary
  `compare_mode`, `incognito`, `plan_mode` and `no_memory` on the same request
  already read.
- **The default has not changed and is not going to.** Omitting `use_rag`, or
  sending it blank, or sending a word nobody recognises, still means *yes*:
  a default answers when the field did not say, and it was never a licence to
  overrule a caller who did say. That distinction is the whole change.
- **Pantheon's own web UI is unaffected.** It sends the literal `'false'` and
  nothing else, so this can only reach a hand-written API client. The first
  affected call logs a warning naming the value.

#### Fixed
_(populated as P1 onward lands; `B24`, `P1-12` and `P1-14` are in and
belong here the next time this section is written out.)_

---

## Upstream

For changes prior to the fork, see the Odysseus repository.
