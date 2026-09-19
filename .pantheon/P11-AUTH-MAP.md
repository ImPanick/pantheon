# P11-AUTH-MAP — where authorization is decided, and by what

`P11-02b` and `P11-02d` ask for two tables and explicitly ask for nothing else:
*"produce the mapping before changing any of them"*, *"nothing here should be changed
before that exists."* This file is those two tables. No route's gating changed to
produce it.

**This file is checked.** `python3 .pantheon/check-auth-map.py` re-derives every
population below out of the source and fails when the two disagree — a site here that
is not in the tree, a site in the tree that is not here, a route whose gate is not what
this file claims, a tier total that does not add up. CI runs it. That is the whole
reason the file is worth writing: both rows above it carry corrections to counts that
drifted, and `Law 9` is that a row cannot be ticked on a claim nobody can re-check.

**There are no line numbers in these tables, deliberately.** A site is keyed by its
file and its enclosing function, which is unique for all 107 (the checker fails if that
stops being true) and survives an edit above it. A committed line number is the one
field that goes stale on every unrelated change, and a map that fails CI for a reason
that is not about auth is a map somebody deletes. `check-auth-map.py --list` prints the
live lines.

### What the two rows claimed, and what is actually there

| claim | row said | measured 2026-09-18 | why |
|---|---|---|---|
| `require_admin` sites | 103 (83 direct + 20 `Depends`) | **107** (87 direct + 20 `Depends`) | 82 direct calls answer to the name `require_admin`; `routes/webhook/webhook_routes.py` imports it as `_require_admin` and holds five more. Under the row's own literal scope the number is **102**, not 103 — the 83 was one too many before the alias is even considered. |
| files making no auth call | 15 | **6** | Nine of the fifteen do. The row already carried that correction and it is confirmed here. |
| routes in those files | 78 | **88** | `auth` is 35, not 29; `chat` is 12, not 8. Both files grew. |
| chat's admin check | `chat_routes.py:338/367` | `:481` and `:510` | 338 and 367 are `_candidate_index` and `_message_plain_text`. The function is right (`owner_is_admin_or_single_user`); the line numbers were carried, not counted — `Law 6`, in a correction whose subject was a carried number. |

### The finding that outranks both counts

`require_admin` is **not** the admin surface. It is the biggest of **four**
implementations of "is this person an admin", and a refactor that maps only the 107
below will walk past the other three:

| where | how | sites |
|---|---|---|
| `core/middleware.require_admin` | the real one: honours `auth_disabled()`, honours the internal-tool token, raises 403 | 107 |
| `routes/auth_routes.py` | `_get_current_user(request)` + `auth_manager.is_admin(user)`, written out inline | 22 of rule C's 43 — all but one a hard 403; the exception is the scrub decision in `GET /api/auth/settings` |
| `routes/shell_routes.py:_require_admin` | its own reimplementation, with its own rules — it also refuses the literal user `api`, which the real one does not | 1 of rule C's 43, called from 6 routes |
| `owner_is_admin_or_single_user` | a policy helper that answers the same question a different way | 8 of rule C's 43, across 6 files |

Only the first consults `auth_disabled()`. Measured by calling both with
`AUTH_ENABLED=false` and no session: `core.middleware.require_admin` returns, and
`routes/shell_routes.py:_require_admin` raises `403 Admin only`. `B543` is that.

Rule C of the checker counts the second and fourth rows directly — every `is_admin(...)`
and `owner_is_admin_or_single_user(...)` call outside `require_admin` itself — and ratchets
them. The count, and the share of it that is one file, are derived:

derived-others: 43 across 16 files, 22 in routes/auth_routes.py

It may fall as they move onto `P11-02`'s role model. It may not rise.

## A · every `require_admin` site (`P11-02b`)

Scope, stated because `Law 5` says a number without one is not a number: **every call to
`core.middleware.require_admin`, and every `Depends(require_admin)`, in tracked non-test
Python outside `.pantheon/`, resolved through `from … import require_admin as X`,
excluding the definition itself.** Derived by AST, not by grep. A grep for
`require_admin(` gets it wrong in both directions at once: it misses the five aliased
calls in `routes/webhook/webhook_routes.py`, and of the eleven `_require_admin(` lines
it does hit, six are `routes/shell_routes.py`'s own unrelated reimplementation.

The four tiers are `P11-02b`'s own question. A site is exactly one of them:

- **`superuser`** — genuinely owner-only. A credential, an execution surface, or the
  whole instance's data.
- **`operator`** — runs the instance. Needs all of it; needs none of the tier above.
- **`power-user`** — a capable user doing their own work, gated as if it were instance
  control.
- **`only-because-nothing-finer-existed`** — `require_admin` is standing in for an
  ownership check or a privilege key that does not exist. The fix is a data model, not
  an auth change.

derived: direct 95 · Depends 20 · total 115

### tier summary

| tier | sites |
|---|---|
| `superuser` | 43 |
| `operator` | 47 |
| `power-user` | 4 |
| `only-because-nothing-finer-existed` | 21 |

### `superuser` — **43 superuser sites.** A credential, an execution surface, or the whole instance's data. These stay `is_admin` under any role model — `P11-02` says so in its own words: *"keep `is_admin` as the superuser role rather than replacing it"*.

| file | function | route | protects |
|---|---|---|---|
| `companion/routes.py` | `pair_page` | `GET /api/companion/pair` | the pairing form. A GET never mints; the comment says why — a `SameSite=Lax` cookie rides a top-level GET, so minting here would be CSRF-able |
| `companion/routes.py` | `pair_create` | `POST /api/companion/pair` | mints a chat-scoped API token for a LAN device. Issuing a credential in someone else's name |
| `routes/admin_wipe/admin_wipe_routes.py` | `wipe` | `DELETE /api/admin/wipe/{kind}` | destroys a whole category of stored data for every user at once |
| `routes/api_token_routes.py` | `delete_token` | `DELETE /api/tokens/{token_id}` | revokes anyone's credential |
| `routes/api_token_routes.py` | `list_tokens` | `GET /api/tokens` | the bearer-token inventory — prefixes, owners and scopes for every token on the instance |
| `routes/api_token_routes.py` | `token_profiles` | `GET /api/tokens/profiles` | the scope profiles a new token can be minted against |
| `routes/api_token_routes.py` | `update_token` | `PATCH /api/tokens/{token_id}` | re-scopes an existing credential |
| `routes/api_token_routes.py` | `create_token` | `POST /api/tokens` | mints a bearer credential. `FORBIDDEN.md` Part 2 lists `require_admin` under privilege escalation, and this is the route that escalates |
| `routes/backup_routes.py` | `export_data` | `GET /api/export` | one archive containing every user's memories, presets and skills |
| `routes/backup_routes.py` | `import_data` | `POST /api/import` | replaces them from an uploaded archive |
| `routes/cookbook_routes.py` | `get_cookbook_ssh_key` | `GET /api/cookbook/ssh-key` | reads the instance's SSH public key |
| `routes/cookbook_routes.py` | `kill_pid` | `POST /api/cookbook/kill-pid` | kills a process by pid on the serving host |
| `routes/cookbook_routes.py` | `server_setup` | `POST /api/cookbook/setup` | runs the remote-host setup — package installs over SSH |
| `routes/cookbook_routes.py` | `generate_cookbook_ssh_key` | `POST /api/cookbook/ssh-key` | generates the instance's SSH keypair |
| `routes/cookbook_routes.py` | `test_cookbook_ssh` | `POST /api/cookbook/test-ssh` | opens an SSH connection from the box to a named host |
| `routes/device_flow.py` | `device_cancel` | `POST /device/cancel` | abandons a pending flow |
| `routes/device_flow.py` | `device_poll` | `POST /device/poll` | polls it, and on success writes the endpoint and its credential |
| `routes/device_flow.py` | `device_start` | `POST /device/start` | begins an OAuth device login that ends in a provider credential stored on the instance. One site, two mounts: `/api/copilot` and `/api/chatgpt-subscription` |
| `routes/mcp/mcp_routes.py` | `delete_server` | `DELETE /api/mcp/servers/{server_id}` | removes one |
| `routes/mcp/mcp_routes.py` | `oauth_authorize` | `GET /api/mcp/oauth/authorize/{server_id}` | starts an OAuth flow against a third-party authorization server |
| `routes/mcp/mcp_routes.py` | `oauth_callback` | `GET /api/mcp/oauth/callback` | receives the code. `FORBIDDEN.md` Part 1 pins the redirect URI because external registrations are keyed on it |
| `routes/mcp/mcp_routes.py` | `list_servers` | `GET /api/mcp/servers` | the MCP server inventory, including each server's command line |
| `routes/mcp/mcp_routes.py` | `list_server_tools` | `GET /api/mcp/servers/{server_id}/tools` | one server's tools |
| `routes/mcp/mcp_routes.py` | `list_tools` | `GET /api/mcp/tools` | every MCP tool the agent can reach |
| `routes/mcp/mcp_routes.py` | `toggle_server` | `PATCH /api/mcp/servers/{server_id}` | enables or disables one |
| `routes/mcp/mcp_routes.py` | `update_disabled_tools` | `PATCH /api/mcp/servers/{server_id}/tools` | changes which of them the agent may call |
| `routes/mcp/mcp_routes.py` | `oauth_exchange` | `POST /api/mcp/oauth/exchange/{server_id}` | exchanges it for a stored token |
| `routes/mcp/mcp_routes.py` | `add_server` | `POST /api/mcp/servers` | adds one. An MCP server is a command this box will execute; `FORBIDDEN.md` Part 2 calls the validation around it the RCE control |
| `routes/mcp/mcp_routes.py` | `reconnect_server` | `POST /api/mcp/servers/{server_id}/reconnect` | re-launches one |
| `routes/mcp/mcp_routes.py` | `update_server` | `PUT /api/mcp/servers/{server_id}` | edits one in place — including the command line it executes, so this is `add_server`'s surface on an existing row. `P8-35` |
| `routes/mcp/mcp_routes.py` | `call_server_tool` | `POST /api/mcp/servers/{server_id}/call` | invokes one tool on one server. The reach is whatever the operator connected, which is the same argument `MCP_NAMESPACE_BLOCK_REASON` makes for refusing the namespace to non-admins. `P8-36` |
| `routes/session_routes.py` | `delete_all_sessions` | `DELETE /api/sessions/all` | deletes every chat session and message on the instance, and their gallery images with them |
| `routes/skills_routes.py` | `import_skill_from_url` | `POST /api/skills/import-from-url` | fetches a skill bundle over the network and installs it. A supply-chain decision; `FORBIDDEN.md` keeps the host allowlist and the IP-pinned transport under it |
| `routes/vault/vault_routes.py` | `get_config` | `GET /api/vault/config` | the credential vault's configuration |
| `routes/vault/vault_routes.py` | `save_config` | `POST /api/vault/config` | rewrites it |
| `routes/vault/vault_routes.py` | `lock` | `POST /api/vault/lock` | locks them |
| `routes/vault/vault_routes.py` | `login` | `POST /api/vault/login` | authenticates to the vault |
| `routes/vault/vault_routes.py` | `logout` | `POST /api/vault/logout` | ends the vault session |
| `routes/vault/vault_routes.py` | `unlock` | `POST /api/vault/unlock` | unlocks stored secrets for use |
| `routes/auth_routes.py` | `list_roles` | `GET /api/auth/roles` | the role catalogue, which is the map of who may do what. `P11-02` |
| `routes/auth_routes.py` | `upsert_role` | `PUT /api/auth/roles/{name}` | defines what a role grants — an escalation surface: a role is a privilege grant to everyone holding it. `P11-02` |
| `routes/auth_routes.py` | `remove_role` | `DELETE /api/auth/roles/{name}` | removes a role and revokes it from every user holding it. `P11-02` |
| `routes/auth_routes.py` | `set_user_role` | `PUT /api/auth/users/{username}/role` | grants somebody else a role. `P11-02` |

### `operator` — **47 operator sites.** Running the box: endpoints, models, probes, logs, webhooks, storage. A person who keeps the instance up needs all of it and needs none of the tier above. This is the tier that makes a role model worth building, because today the only way to hand someone the operator's job is to hand them the owner's.

| file | function | route | protects |
|---|---|---|---|
| `routes/codex_routes.py` | `_require_cookbook_scope` | `—` | not a route: the helper nine Codex cookbook routes call. It demands the scope from a bearer token and admin from a cookie session, and its docstring is the clearest statement in the tree of why cookbook is gated — host topology, task logs, tmux commands, model-serving controls |
| `routes/cookbook_routes.py` | `list_gpus` | `GET /api/cookbook/gpus` | host GPU inventory. Compare `GET /api/hwfit/system`, which answers the same question with no gate at all — see `B541` |
| `routes/cookbook_routes.py` | `get_cookbook_state` | `GET /api/cookbook/state` | the serve-state file: which models are up, on which hosts |
| `routes/cookbook_routes.py` | `cookbook_tasks_status` | `GET /api/cookbook/tasks/status` | progress of in-flight downloads and serves |
| `routes/cookbook_routes.py` | `model_cached` | `GET /api/model/cached` | what is already on disk |
| `routes/cookbook_routes.py` | `save_cookbook_state` | `POST /api/cookbook/state` | rewrites it. `FORBIDDEN.md` blocks the agent's generic `app_api` from this pair after it wiped the file once |
| `routes/cookbook_routes.py` | `model_download` | `POST /api/model/download` | pulls model weights onto the host's disk |
| `routes/cookbook_routes.py` | `model_serve` | `POST /api/model/serve` | starts a model server in tmux |
| `routes/diagnostics_routes.py` | `get_database_stats` | `GET /api/db/stats` | row counts |
| `routes/diagnostics_routes.py` | `get_diagnostic_bundle` | `GET /api/diagnostics/bundle` | the redacted support bundle |
| `routes/diagnostics_routes.py` | `list_evals` | `GET /api/diagnostics/evals` | the eval suites this build ships |
| `routes/diagnostics_routes.py` | `get_diagnostics_logs` | `GET /api/diagnostics/logs` | server logs, which carry every user's activity |
| `routes/diagnostics_routes.py` | `get_self_check` | `GET /api/diagnostics/self-check` | the boot self-check |
| `routes/diagnostics_routes.py` | `get_service_health` | `GET /api/diagnostics/services` | which subsystems answered |
| `routes/diagnostics_routes.py` | `get_rag_stats` | `GET /api/rag/stats` | collection sizes |
| `routes/diagnostics_routes.py` | `test_youtube` | `GET /api/test/youtube` | a connectivity probe |
| `routes/diagnostics_routes.py` | `prometheus_metrics` | `GET /metrics` | the Prometheus scrape endpoint. `Law 16` clause 4 makes this the operator's to point where they like, which is exactly the operator tier |
| `routes/diagnostics_routes.py` | `run_eval` | `POST /api/diagnostics/evals/{name}/run` | runs one; it costs the instance's model budget |
| `routes/diagnostics_routes.py` | `test_research` | `POST /api/test-research` | a research-pipeline probe that spends model budget |
| `routes/embedding_routes.py` | `setup_embedding_routes` | `—` | not a route: a router-level `dependencies=[Depends(require_admin)]` covering every route under `/api/embeddings`. One site, whole-surface reach — the shape `P11-02`'s refactor should prefer |
| `routes/model_routes.py` | `delete_model_endpoint` | `DELETE /api/model-endpoints/{ep_id}` | deletes it |
| `routes/model_routes.py` | `discover_local` | `GET /api/discover` | LAN/local discovery, which makes outbound connections |
| `routes/model_routes.py` | `probe_local_endpoints` | `GET /api/model-endpoints/probe-local` | scans loopback ports for local model servers |
| `routes/model_routes.py` | `probe_endpoint_models` | `GET /api/model-endpoints/{ep_id}/probe` | asks one endpoint what it serves |
| `routes/model_routes.py` | `ping_endpoints` | `GET /api/ping` | reachability of every configured endpoint |
| `routes/model_routes.py` | `probe_models` | `GET /api/probe` | probes them all |
| `routes/model_routes.py` | `toggle_model_endpoint` | `PATCH /api/model-endpoints/{ep_id}` | enables or disables an endpoint for everyone |
| `routes/model_routes.py` | `update_hidden_models` | `PATCH /api/model-endpoints/{ep_id}/models` | changes what every user sees in the picker |
| `routes/model_routes.py` | `create_model_endpoint` | `POST /api/model-endpoints` | creates one, storing a provider API key |
| `routes/model_routes.py` | `test_model_endpoint` | `POST /api/model-endpoints/test` | tests a candidate endpoint, spending a call |
| `routes/model_routes.py` | `probe_selected` | `POST /api/probe-selected` | probes a chosen subset |
| `routes/model_routes.py` | `update_tools` | `POST /api/tools` | the instance-wide tool enablement map |
| `routes/personal_routes.py` | `delete_file_from_rag` | `DELETE /api/personal/file` | drops one file from the index |
| `routes/personal_routes.py` | `remove_directory_from_rag` | `DELETE /api/personal/remove_directory` | un-points it |
| `routes/personal_routes.py` | `add_directory_to_rag` | `POST /api/personal/add_directory` | points the indexer at a host directory — filesystem reach, not document management |
| `routes/personal_routes.py` | `api_personal_reload` | `POST /api/personal/reload` | re-indexes the whole corpus |
| `routes/skills_routes.py` | `list_builtin_skills` | `GET /api/skills/builtin` | the inventory of every built-in tool the agent has, with the first 240 characters of the instruction block each one is given. Gated by `P2-21` on 2026-09-18; until then it made no auth call at all, beside the PUT and DELETE below it |
| `routes/skills_routes.py` | `get_builtin_skill` | `GET /api/skills/builtin/{name}` | the whole instruction block, override included — the same text the model is given. The read half of the pair below, gated at the same height for the same reason |
| `routes/skills_routes.py` | `reset_builtin_override` | `DELETE /api/skills/builtin/{name}` | puts it back |
| `routes/skills_routes.py` | `set_builtin_override` | `PUT /api/skills/builtin/{name}` | rewrites a built-in skill's text for every user's agent |
| `routes/upload_routes.py` | `upload_stats` | `GET /api/upload/stats` | aggregate upload storage |
| `routes/upload_routes.py` | `manual_cleanup` | `POST /api/upload/cleanup` | deletes expired uploads across all owners |
| `routes/webhook/webhook_routes.py` | `delete_webhook` | `DELETE /api/webhooks/{webhook_id}` | removes one |
| `routes/webhook/webhook_routes.py` | `list_webhooks` | `GET /api/webhooks` | the outbound webhook inventory. All five reach `require_admin` under the alias `_require_admin`, which is why a grep for `require_admin(` finds none of them |
| `routes/webhook/webhook_routes.py` | `toggle_webhook` | `PATCH /api/webhooks/{webhook_id}` | enables or disables one |
| `routes/webhook/webhook_routes.py` | `create_webhook` | `POST /api/webhooks` | adds an outbound destination the instance will POST to |
| `routes/webhook/webhook_routes.py` | `test_webhook` | `POST /api/webhooks/{webhook_id}/test` | fires a test delivery |

### `power-user` — **4 power-user sites.** Reads a capable user needs in order to work, gated as if they were instance control. All four are the model picker's inventory: a non-admin can be given `allowed_models` in `DEFAULT_PRIVILEGES` today and still cannot see which endpoints exist.

| file | function | route | protects |
|---|---|---|---|
| `routes/model_routes.py` | `list_model_endpoints` | `GET /api/model-endpoints` | the endpoint list with keys masked. Same argument: choosing a model is a user act gated as an operator one |
| `routes/model_routes.py` | `get_endpoint_dependents` | `GET /api/model-endpoints/{ep_id}/dependents` | what would break if an endpoint went away |
| `routes/model_routes.py` | `list_endpoint_models` | `GET /api/model-endpoints/{ep_id}/models` | the cached model list for one endpoint |
| `routes/model_routes.py` | `providers` | `GET /api/providers` | the provider catalogue — static, no instance data. A non-admin who may pick a model needs this and cannot have it |

### `only-because-nothing-finer-existed` — **21 only-because-nothing-finer-existed sites.** The gate is on the shape of the store, not on the act. Contacts, presets and the personal index are one shared file with no owner column, and the receipts are per-run data with no owner scope — so "admin" is standing in for an ownership check nobody has written. These are the rows `P11-02` should retire, and retiring them is a data-model change, not an auth change.

| file | function | route | protects |
|---|---|---|---|
| `routes/contacts/contacts_routes.py` | `clear_contacts` | `DELETE /api/contacts/clear` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `delete_contact` | `DELETE /api/contacts/{uid}` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `get_config` | `GET /api/contacts/config` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `export_contacts` | `GET /api/contacts/export` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `list_contacts` | `GET /api/contacts/list` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `search_contacts` | `GET /api/contacts/search` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `add_contact` | `POST /api/contacts/add` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `import_vcf` | `POST /api/contacts/import` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `update_config` | `PUT /api/contacts/config` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/contacts/contacts_routes.py` | `edit_contact` | `PUT /api/contacts/{uid}` | one shared address book with no owner column. Every route in this file is a router-level `Depends(require_admin)`; the gate is on the store's shape, not on the act |
| `routes/diagnostics_routes.py` | `diff_two_receipts` | `GET /api/diagnostics/diff/{before_id}/{after_id}` | diffs two runs — ownership |
| `routes/diagnostics_routes.py` | `get_receipt` | `GET /api/diagnostics/receipt/{run_id}` | one run's receipt. A receipt belongs to whoever made the run; admin is standing in for an owner column |
| `routes/diagnostics_routes.py` | `export_receipt` | `GET /api/diagnostics/receipt/{run_id}/export` | exports one — ownership |
| `routes/diagnostics_routes.py` | `get_rerun_plan` | `GET /api/diagnostics/rerun/{run_id}` | what re-running that run would do — same ownership question |
| `routes/diagnostics_routes.py` | `get_usage` | `GET /api/diagnostics/usage` | token and cost usage. Per-run data with no owner scope, so a second user can neither see their own nor be kept from everyone else's |
| `routes/diagnostics_routes.py` | `do_rerun` | `POST /api/diagnostics/rerun/{run_id}` | re-runs it. Ownership again, and this one acts |
| `routes/personal_routes.py` | `api_personal_list` | `GET /api/personal` | lists the indexed personal documents. One shared index with no owner column, so admin is standing in for ownership |
| `routes/preset_routes.py` | `delete_user_template` | `DELETE /api/presets/templates/{template_id}` | same file, same reason |
| `routes/preset_routes.py` | `update_custom_preset` | `POST /api/presets/custom` | saves a persona into the single shared presets file. A second user cannot have one of their own, so admin is the only available answer |
| `routes/preset_routes.py` | `save_group_presets` | `POST /api/presets/groups` | same file, same reason |
| `routes/preset_routes.py` | `save_user_template` | `POST /api/presets/templates` | same file, same reason |

## B · what gates the fifteen quiet route files (`P11-02d`)

One row per route, **88 routes across the fifteen files**. Six of the fifteen make no
auth call of their own; the other nine do, which is what `P11-02d` already says and
what this confirms.

The `gate` column is derived, never asserted, and reads as a chain:

- **`middleware`** — `AuthMiddleware` in `app.py` and nothing else. A session or a
  bearer token is required; **any** signed-in user gets through.
- **`exempt`** — the path is in `AUTH_EXEMPT_EXACT` (or matches a pattern or the
  `/static` prefix), so no authentication is required at all. `_is_auth_exempt` takes
  **one argument and it is the path**: an exemption covers every method on that path,
  which is `B542`.
- **`+ name`** — the handler reaches that auth function, directly or through a helper
  in the same module, or the router carries it as a `Depends`. Reachability, because
  the call is usually one helper away: `assistant_routes.py` calls `get_current_user`
  from a one-line `_owner()` and a per-handler grep reports all six of its routes as
  ungated.

The `intended` column is a verdict and must begin `yes` or `no`. A `no` must name a
`Bxxx`; the checker fails on one that does not, so a hole cannot sit in this table
unfiled. **There are seven `no`s and they are `B540`, `B541` and `B542`.**

#### `routes/assistant_routes.py`

Every handler reaches `get_current_user` through a one-line `_owner()` helper. A per-handler grep sees none of them, which is how six gated routes were counted as unknowns.

routes: 6

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/assistant/session` | `get_assistant_session` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `GET /api/assistant/settings` | `get_assistant_settings` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `PATCH /api/assistant/settings` | `update_assistant_settings` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `POST /api/assistant/run/{task_id}` | `run_check_in_now` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `GET /api/assistant/run-status/{task_id}` | `run_status` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `GET /api/assistant/available-timezones` | `list_timezones` | `middleware` | yes — a static list of zone names; there is nothing here to scope. |

#### `routes/auth_routes.py`

The largest file in the fifteen and the one that matters most. Every row below whose gate ends `+ is_admin` is admin-gated **by hand** — `_get_current_user` + `auth_manager.is_admin`, written out — rather than by `require_admin`. That is why a `require_admin` audit sees nothing in this file, and why `B543` exists.

**The four role routes at the bottom are the exception, deliberately** (`P11-02`). They gate with `core.middleware.require_admin`, which is the only one of the four implementations that consults `auth_disabled()` — the hand-rolled one refuses the single operator of an auth-disabled box. They are also the reason § A's superuser tier moved from 37 to 41 and this file's count from 35 to 39. Rule C's ratchet did not move: `require_admin` is not one of the gates it counts, which is the point.

routes: 39

| route | handler | gate | intended |
|---|---|---|---|
| `POST /api/auth/setup` | `first_run_setup` | `exempt` | yes — first-run account creation; it must work before anyone can log in. Rate-limited 3/300. |
| `POST /api/auth/signup` | `signup` | `exempt` | yes — signup, and it refuses when open signup is off. Rate-limited 3/300. |
| `POST /api/auth/login` | `login` | `exempt` | yes — the login route. Rate-limited 15/60; `FORBIDDEN.md` Part 2 keeps that limiter. |
| `POST /api/auth/logout` | `logout` | `exempt` | yes — clearing your own cookie cannot require the cookie to be valid. |
| `GET /api/auth/status` | `auth_status` | `exempt` | yes — the login page asks whether setup is needed. |
| `GET /api/auth/policy` | `auth_policy` | `middleware` | yes — password policy, behind the session. Not exempt, and does not need to be. |
| `POST /api/auth/change-password` | `change_password` | `middleware + _get_current_user` | yes — self-service; it changes only the caller's own password. |
| `POST /api/auth/2fa/setup` | `totp_setup` | `middleware + _get_current_user` | yes — self-service TOTP enrolment for the caller. |
| `POST /api/auth/2fa/confirm` | `totp_confirm` | `middleware + _get_current_user` | yes — self-service. |
| `POST /api/auth/2fa/disable` | `totp_disable` | `middleware + _get_current_user` | yes — self-service. |
| `GET /api/auth/2fa/status` | `totp_status` | `middleware + _get_current_user` | yes — self-service. |
| `GET /api/auth/users` | `list_users` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `POST /api/auth/users` | `admin_create_user` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `PUT /api/auth/users/{username}/privileges` | `update_user_privileges` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `PUT /api/auth/users/{username}/rename` | `rename_user` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/roles` | `list_roles` | `middleware + require_admin` | yes — the role catalogue plus the two key registries a panel needs to render an editor. `P11-02`. |
| `PUT /api/auth/roles/{name}` | `upsert_role` | `middleware + get_current_user + require_admin` | yes — defining a role is granting a privilege to everyone who holds it. `P11-02`. |
| `DELETE /api/auth/roles/{name}` | `remove_role` | `middleware + get_current_user + require_admin` | yes — deleting a role revokes it from every user holding it, in one write. `P11-02`. |
| `PUT /api/auth/users/{username}/role` | `set_user_role` | `middleware + get_current_user + require_admin` | yes — assigning somebody else's role. `P11-02`. |
| `PUT /api/auth/users/{username}/admin` | `set_user_admin` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `POST /api/auth/signup-toggle` | `toggle_signup` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `PUT /api/auth/open-signup` | `set_signup_enabled` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `DELETE /api/auth/users` | `admin_delete_user` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/features` | `get_features` | `exempt` | yes — the feature flags the pre-login page renders from. Read only, no secrets. |
| `POST /api/auth/features` | `set_features` | `exempt + _get_current_user + is_admin` | no — `B542`. The exemption is matched on path alone, so the **write** is exempt too; only the handler's own `is_admin` stands between an unauthenticated caller and the instance's feature flags. |
| `GET /api/auth/settings` | `get_settings` | `exempt + _get_current_user + is_admin` | yes — exempt on purpose, and it scrubs: an admin gets the full set, everyone else a copy with secrets blanked. The scrub is the control, and it is in the handler where it belongs. |
| `POST /api/auth/networks/check` | `check_networks` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/networks/agent` | `network_agent_health` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/networks/guard` | `host_guard_rules` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/networks/devices` | `network_devices` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `POST /api/auth/networks/devices/name` | `name_network_device` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/settings/flag-sources` | `settings_flag_sources` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `POST /api/auth/settings` | `set_settings` | `exempt + _get_current_user + is_admin` | no — `B542`. Same path-only exemption, and this one writes every app setting, credentials included. |
| `GET /api/auth/integrations` | `list_integrations_route` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `GET /api/auth/integrations/presets` | `list_presets` | `exempt` | yes — preset templates with `api_key` stripped in the comprehension; nothing instance-specific. |
| `POST /api/auth/integrations` | `create_integration` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `PUT /api/auth/integrations/{integration_id}` | `update_integration_route` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `DELETE /api/auth/integrations/{integration_id}` | `delete_integration_route` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |
| `POST /api/auth/integrations/{integration_id}/test` | `test_integration_route` | `middleware + _get_current_user + is_admin` | yes — admin is right for this. The *mechanism* is not: it is hand-rolled rather than `require_admin`, so no `require_admin` audit sees it. `B543`. |

#### `routes/chat_routes.py`

The router carries `dependencies=[Depends(require_chat_api_token_scope)]`, so every route below gets it whether or not the handler mentions auth, and every session route reaches `_verify_session_owner` (imported from `routes/session_routes.py`). `P11-02d` named `chat_routes.py:338/367` as the admin check; those two lines are `_candidate_index` and `_message_plain_text`. The real admin check is `owner_is_admin_or_single_user` at 481 and 510, reached only from `chat_stream`, and it gates workspace binding rather than the route.

routes: 14

| route | handler | gate | intended |
|---|---|---|---|
| `POST /api/chat` | `chat_endpoint` | `middleware + _verify_session_owner + effective_user + owner_filter + require_api_token_scope + require_chat_api_token_scope` | yes — token scope, then `effective_user`, then `owner_filter` on every row it reads. |
| `POST /api/chat_stream` | `chat_stream` | `middleware + _verify_session_owner + effective_user + get_current_user + owner_filter + owner_is_admin_or_single_user + require_api_token_scope + require_chat_api_token_scope` | yes — the same, plus `owner_is_admin_or_single_user` before any workspace is bound. |
| `GET /api/chat/resume/{session_id}` | `chat_resume` | `middleware + _verify_session_owner + require_chat_api_token_scope` | yes — `_verify_session_owner` refuses another user's session, and refuses "not yours" and "no such session" identically. |
| `POST /api/chat/stop/{session_id}` | `chat_stop` | `middleware + _verify_session_owner + require_chat_api_token_scope` | yes — `_verify_session_owner` refuses another user's session, and refuses "not yours" and "no such session" identically. |
| `POST /api/chat/steer/{session_id}` | `chat_steer` | `middleware + _verify_session_owner + require_chat_api_token_scope` | yes — `_verify_session_owner` refuses another user's session, and refuses "not yours" and "no such session" identically. |
| `GET /api/chat/stream_status/{session_id}` | `chat_stream_status` | `middleware + _verify_session_owner + require_chat_api_token_scope` | yes — `_verify_session_owner` refuses another user's session, and refuses "not yours" and "no such session" identically. |
| `POST /api/inject_context/{session_id}` | `inject_context` | `middleware + _verify_session_owner + require_chat_api_token_scope` | yes — `_verify_session_owner` refuses another user's session, and refuses "not yours" and "no such session" identically. |
| `GET /api/search` | `search_messages` | `middleware + effective_user + require_chat_api_token_scope` | yes — `effective_user`, and the query is filtered to that owner's messages. |
| `POST /api/rewrite` | `rewrite_message` | `middleware + _verify_session_owner + require_chat_api_token_scope` | yes — `_verify_session_owner` refuses another user's session, and refuses "not yours" and "no such session" identically. |
| `GET /api/tool-allow-rules` | `list_tool_allow_rules` | `middleware + require_chat_api_token_scope + require_user + storage_owner_for_request` | yes — `require_user` 403s a bearer token outright, then `storage_owner_for_request` scopes the rows. |
| `POST /api/tool-allow-rules` | `create_tool_allow_rule` | `middleware + require_chat_api_token_scope + require_user + storage_owner_for_request` | yes — same pair, and these rules decide what the agent may run without asking. |
| `DELETE /api/tool-allow-rules/{rule_id}` | `delete_tool_allow_rule` | `middleware + require_chat_api_token_scope + require_user + storage_owner_for_request` | yes — same pair. |
| `GET /api/tool-approval-grants/{session_id}` | `list_tool_approval_grants` | `middleware + _verify_session_owner + require_chat_api_token_scope + require_user` | yes (`P7-09`) — `require_user` 403s a bearer token, then `_verify_session_owner` refuses another owner's chat and refuses "not yours" and "no such session" identically, so the listing cannot be used to probe which chats exist. |
| `DELETE /api/tool-approval-grants/{session_id}` | `revoke_tool_approval_grants` | `middleware + _verify_session_owner + require_chat_api_token_scope + require_user` | yes (`P7-09`) — the same pair. Revoking is a tightening, but listing is not, and both doors are the same door. |

#### `routes/cleanup/cleanup_routes.py`

routes: 2

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/cleanup/preview` | `cleanup_preview` | `middleware + get_current_user` | yes — `get_cleanup_preview(owner=user)`; a caller sees only their own sessions. |
| `POST /api/cleanup` | `cleanup_endpoint` | `middleware + get_current_user` | yes — `cleanup_sessions(owner=user)`; it archives and deletes only the caller's own. |

#### `routes/compare/compare_routes.py`

routes: 5

| route | handler | gate | intended |
|---|---|---|---|
| `POST /api/compare/start` | `start_comparison` | `middleware + owner_filter` | yes — `owner_filter` resolves the endpoints it is allowed to use; a chat-scoped token cannot borrow another owner's provider key. |
| `POST /api/compare/{comp_id}/vote` | `vote_comparison` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `POST /api/compare/record` | `record_comparison` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `GET /api/compare/history` | `list_comparisons` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `DELETE /api/compare/{comp_id}` | `delete_comparison` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |

#### `routes/editor_draft_routes.py`

routes: 5

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/editor-drafts` | `list_drafts` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `GET /api/editor-drafts/{draft_id}` | `get_draft` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `POST /api/editor-drafts` | `create_draft` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `PUT /api/editor-drafts/{draft_id}` | `update_draft` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `DELETE /api/editor-drafts/{draft_id}` | `delete_draft` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |

#### `routes/emoji_routes.py`

routes: 1

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/emoji/{code}.svg` | `emoji_svg` | `middleware` | yes — vendored OpenMoji bytes that ship with the product, re-sanitised on the way out. Login-gated by the middleware and nothing finer is owed. |

#### `routes/font_routes.py`

routes: 1

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/fonts/custom` | `list_custom_fonts` | `middleware` | yes — the filenames under `static/fonts/custom`, which `AUTH_EXEMPT_PREFIXES` already serves to the same audience. Login is the right bar. |

#### `routes/hwfit_routes.py`

All four take `host` and `ssh_port` and run hardware detection over SSH against them. `GET /api/cookbook/gpus` answers the same question behind `require_admin`, and `routes/codex_routes.py:114` writes down why. See `B541`.

routes: 4

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/hwfit/system` | `get_system` | `middleware` | no — `B541`. `?host=user@server` makes the instance open SSH to a host the caller names; `GET /api/cookbook/gpus` asks the same question behind `require_admin`. |
| `GET /api/hwfit/models` | `get_models` | `middleware` | no — `B541`. Same `host`/`ssh_port` pair, same detection path. |
| `GET /api/hwfit/profiles` | `get_serve_profiles` | `middleware` | no — `B541`. Same. |
| `GET /api/hwfit/image-models` | `get_image_models` | `middleware` | no — `B541`. Same. |

#### `routes/prefs_routes.py`

routes: 3

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/prefs` | `get_all_prefs` | `middleware + get_current_user` | yes — keyed by caller inside one shared prefs file; `check-config-writes.py` already classes that file `guarded`. |
| `GET /api/prefs/{key}` | `get_pref` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `PUT /api/prefs/{key}` | `set_pref` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |

#### `routes/search/search_routes.py`

`services/search/core.py:60` calls `GET /api/search/config` *"the unauthenticated `GET /api/search/config` route"*. It is not unauthenticated — the path is in neither `AUTH_EXEMPT_EXACT` nor the `/static` prefix, so AuthMiddleware requires a session. The scrubbing that comment justifies is right and worth keeping; the sentence about who can reach it is wrong.

routes: 4

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/search/config` | `get_search_settings` | `middleware` | yes — login-gated, and `get_search_config` strips every string-valued credential before returning. The docstring calling this route unauthenticated is wrong; the scrub it justifies is not. |
| `POST /api/search` | `do_web_search` | `middleware` | yes — any signed-in user may search. It spends the operator's provider quota with no per-user ceiling, which is `P12-05`'s job and not a hole: the limiter this needs does not exist yet for anyone. |
| `GET /api/search/providers` | `list_search_providers` | `middleware` | yes — provider ids and an `available` boolean; key *presence*, never a key. |
| `POST /api/search/query` | `search_with_provider` | `middleware` | yes — as `POST /api/search`, with the provider named. Same `P12-05` note. |

#### `routes/signature_routes.py`

routes: 3

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/signatures` | `list_signatures` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |
| `POST /api/signatures` | `create_signature` | `middleware + get_current_user` | yes — owner-scoped, and the PNG magic and size caps `FORBIDDEN.md` Part 2 lists are enforced in the handler. |
| `DELETE /api/signatures/{sig_id}` | `delete_signature` | `middleware + get_current_user` | yes — owner-scoped; the handler resolves the caller and filters on it. |

#### `routes/stt_routes.py`

routes: 2

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/stt/stats` | `get_stt_stats` | `middleware` | yes — counters for a local service; no per-user data in them. |
| `POST /api/stt/transcribe` | `transcribe_audio` | `middleware` | yes — a signed-in user transcribing their own audio, capped by `STT_MAX_AUDIO_BYTES`. |

#### `routes/tts_routes.py`

routes: 3

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/tts/stats` | `get_tts_stats` | `middleware` | yes — counters for a local service. |
| `POST /api/tts/synthesize` | `synthesize_speech` | `middleware` | yes — a signed-in user synthesising their own text. |
| `POST /api/tts/clear-cache` | `clear_tts_cache` | `middleware` | no — `B540`. An instance-wide mutation with no privilege check, while the same act on uploads (`POST /api/upload/cleanup`) is `require_admin`. |

#### `routes/workspace_routes.py`

The only file of the fifteen that makes a real privilege decision of its own: both routes refuse a caller `owner_is_admin_or_single_user` says no to, which is an admin check spelled a fourth way (`B543`).

routes: 2

| route | handler | gate | intended |
|---|---|---|---|
| `GET /api/workspace/browse` | `browse` | `middleware + get_current_user + owner_is_admin_or_single_user` | yes — refused unless `owner_is_admin_or_single_user`; browsing the host filesystem is correctly the strictest gate in these fifteen files. |
| `GET /api/workspace/vet` | `vet` | `middleware + get_current_user + owner_is_admin_or_single_user` | yes — same gate, same reason. |

## C · what this map is for

`P11-02` keeps `is_admin` as the superuser role *"because 103 call sites depend on it
and rewriting them all at once is how this goes wrong."* That reasoning holds at 107,
and the tables above say which of the 107 the rewrite can actually leave alone.

**Re-measured 2026-09-18 after `P11-02` landed: 111, not 107**, and the four new ones are
`P11-02`'s own role-management routes. They are gated with `require_admin` rather than
this file's hand-rolled pattern, so the population that this map covers grew by exactly
the number of admin decisions added — which is the behaviour the map was built to give.
The paragraph above is about the 107 that predate roles; the counts below are live.

- **43 superuser sites do not move.** They are already right.
- **47 operator sites are the phase's return.** Today the only way to let someone keep
  the instance up is to make them the owner. An `operator` overlay on
  `DEFAULT_PRIVILEGES` retires 47 gates without touching a single one of the 37.
- **4 power-user sites are one privilege key.** `allowed_models` already exists in
  `DEFAULT_PRIVILEGES`; a user who has it still cannot list the endpoints it names.
- **21 only-because-nothing-finer-existed sites are not an auth job at all.** Contacts,
  presets and the personal index need an owner column; the diagnostics receipts need an
  owner scope. Changing the gate before the store has an owner would swap one wrong
  answer for another.

And before any of it: **the other three admin gates in § A's preamble.** `P11-02c`
already exists for the `_ADMIN_TOOLS` name collision *"one grep away from a serious
mistake during an RBAC refactor"*. These are the same hazard in a different spelling,
and `B543` is filed for them.

## What this file does not cover

- `require_privilege` (**17** call sites, same scope) and `owner_filter` (**32**).
  Different questions — "may this kind of person" and "whose row is this" — and `P11`'s
  preamble already counts both, at 16 and 32. The 32 reproduces; the 16 is one short.
- The other route files. § B is the fifteen `P11-02d` names and no more; the tree has
  far more routes than 88.
- Anything about whether a gate *works*. This is a map of where the decisions are taken,
  not an audit of each decision's logic.
