# SPDX-License-Identifier: AGPL-3.0-or-later
# src/settings.py
"""Centralized settings and features management.

Single source of truth for reading/writing data/settings.json and data/features.json.
All modules should import from here instead of accessing files directly.
"""

import json
import time
import logging
from typing import Any, Callable

from src.constants import SETTINGS_FILE, FEATURES_FILE

logger = logging.getLogger(__name__)

# Keys retained in the raw settings store for compatibility and rollback, but
# deliberately unavailable through generic settings APIs or agent tools.  They
# must stay in ``DEFAULT_SETTINGS`` so old files continue to load without data
# loss; callers that present or mutate settings should use this set as a
# tombstone boundary.
RETIRED_SETTING_KEYS = frozenset({"default_model_fallbacks"})

# Tiny TTL cache for settings/features. get_setting() is called on hot paths
# (every chat, every preprocess); without this it re-parses the JSON each call.
# Picks up edits within _CACHE_TTL seconds, which is fine for human-edited config.
_CACHE_TTL = 2.0
_settings_cache: tuple[float, dict] | None = None
_features_cache: tuple[float, dict] | None = None

# Distinguishes "caller passed no default" from "caller passed None", which is
# a real default for several keys. See `setting_is_explicit`.
_UNSET = object()

def _invalidate_caches():
    global _settings_cache, _features_cache
    _settings_cache = None
    _features_cache = None

# ── Default values ──

DEFAULT_SETTINGS = {
    # Agent email safety: when True, the MCP send_email / reply_to_email
    # tools don't SMTP directly. They stage the composed message into the
    # scheduled_emails table with status='agent_draft' and return a
    # pending_id + the rendered email so the user can review and approve
    # (or cancel) before it actually goes out. Default ON because models
    # have been observed inventing signatures and sending to real
    # recipients without confirmation.
    "agent_email_confirm": True,
    # A GitHub personal access token, read-only/public scope is enough. Empty by
    # default. Unauthenticated api.github.com allows 60 requests an hour per IP;
    # with a token it is 5,000. The skill importer walks a repository tree, so
    # without this an operator gets a handful of imports an hour and then a 403.
    # NOTE: the env fallback in `skill_importer._github_credentials` is reachable
    # only because this default is falsy — see the note there before copying the
    # pattern to a setting whose default is not.
    "github_token": "",
    # May Pantheon fetch a model from a third party on its own? Ships False
    # (`Law 16`). Until 2026-09-01 the local embedding model was downloaded from
    # HuggingFace on the **first chat message** of a fresh install, because the
    # fastembed lane was built unconditionally even when a local embedding
    # server was already answering. This is the switch that permits it, and the
    # answer to "why is memory unavailable" on a machine with no local
    # embedding server and no network.
    #
    # `B90`. Ships `None`, not `False`, and the difference is the whole row.
    # `load_settings` merges this dict on every read, so a shipped `False` and a
    # stored `False` are the same byte to every reader — which is why
    # `bool(get_setting(k, False)) or <env truthy>` could not see an operator's
    # deliberate *no* and `PANTHEON_ALLOW_MODEL_DOWNLOAD=1` won over it.
    # Measured 2026-09-15: stored `False`, effective `True`. `None` is the third
    # value that lets the flat dict hold the difference; `bool(None)` is `False`,
    # so nothing that reads this key with `bool()` changes. See
    # `env_backed_flag`.
    "allow_model_download": None,
    # Where the diagnostic bundle's "report this" link points (`P16-14`).
    #
    # Ships EMPTY, deliberately, and the emptiness is load-bearing twice over.
    # `get_setting` merges DEFAULT_SETTINGS on every read, so the
    # PANTHEON_ISSUE_TRACKER_URL fallback in `routes/diagnostics_routes.py`
    # would be dead code beneath a truthy default (`H06`, `B20`, and `P16-05`
    # from the other side). And a company making this their own private stack
    # (`D-2026-09-01-01`) wants their tracker, not this repo's; shipping an
    # address decides that for them.
    #
    # Empty means "the client offers the project's own issues page as a link".
    # That link is navigation the person clicks, never a request this server
    # makes — no bundle is transmitted anywhere by anything Pantheon runs.
    "issue_tracker_url": "",
    # May a failed SearXNG search retry with this instance's DEFAULT engines?
    # (`P16-10`.) Ships off. Pinning engines is a choice about who sees the
    # query; the retry that dropped the pin handed it to Google, DuckDuckGo and
    # Brave on the third attempt, silently. Off keeps the choice; on is one
    # switch away and the switch says what it does.
    #
    # `None` rather than `False` — `B90`, and see `allow_model_download` above
    # for why the third value is needed to hold *no* apart from *unset*.
    "searxng_widen_engines": None,
    # How many days of the events table to keep (`P14-01`). 0 = keep everything.
    #
    # Finite by default, because an append-only table with no ceiling is a
    # defect on somebody's home server rather than a feature — and 90 days
    # answers every question this phase asks ("what did last month cost",
    # "did that change help") without becoming the largest thing in the
    # database. Keeping everything is a choice someone makes, not one they
    # inherit by nobody having thought about it.
    #
    # SETTINGS-ONLY — there is no PANTHEON_EVENTS_RETENTION_DAYS, and the
    # omission is deliberate. `get_setting` merges DEFAULT_SETTINGS on every
    # read, so an env fallback beneath a TRUTHY default can never run: it is
    # unreachable the moment the default is 90 rather than 0 or "". That shape
    # was found dead twice already (`H06`, `B20`) and turned on exactly this
    # distinction in `P16-05`. It was registered in the env and all three
    # compose files here before the same check caught it a fourth time, and
    # removed rather than left as decoration. Retention is not a boot-time
    # concern; Settings is the place to change it.
    "events_retention_days": 90,
    # ── `P12` · limits that were constants ──────────────────────────────────
    #
    # `P12-06`. The per-client upload burst gate: at most N uploads in the last
    # W seconds, refused with a 429. It shipped as `3` inside
    # `UploadHandler.__init__` and a `10.0` default argument on
    # `count_recent_uploads`, and the 429 called it a concurrency limit — which
    # it has never been, because nothing decrements when an upload finishes.
    #
    # Both resolve through `src/limit_policy.py`: role profile → this setting →
    # environment → built-in default, per request, so a change takes effect
    # without a restart. `POST /api/auth/settings` clamps both to the bounds in
    # `src/upload_limits.py`, so the stored number and the effective number are
    # the same number.
    #
    # Deliberately NOT in `_SELF_RESTRAINT_KEYS`: these are throttles with no
    # approval semantics, the same reasoning that keeps `agent_max_rounds` and
    # `agent_max_tool_calls` out of that set.
    "upload_burst_limit": 3,
    "upload_burst_window_seconds": 10,
    # `P12-10`. How long an approval card stays answerable before it closes as
    # **denied**. It was `DEFAULT_APPROVAL_TTL_SECONDS`, a ten-minute constant,
    # and expiry recorded one `expired` event and decided nothing.
    #
    # `FORBIDDEN.md` Part 2 keeps "the approval store's seal, TTL, single-use
    # consumption and owner binding". Making the TTL settable is not lifting
    # it, and the floor is what keeps that true: `0` here is not "no timeout",
    # it is clamped to `MIN_APPROVAL_TTL_SECONDS`. A setting that can be typed
    # into an off switch is the control with an off switch.
    #
    # This one IS in `_SELF_RESTRAINT_KEYS` (`B42`): a longer deadline is a
    # card that stays answerable instead of closing denied, and a gate whose
    # purpose is "a human must confirm" cannot be adjustable through the
    # channel the gate exists to distrust.
    "approval_timeout_seconds": 600,
    # `P14-07`. The two ceilings on document indexing, in MiB. `0` on either
    # means no ceiling, which is a choice an operator can make and not one they
    # inherit.
    #
    # Measured before this row: one 419 MB file in a documents folder took the
    # process from 185 MB to 1,384 MB of RSS while it was chunked — the decoded
    # string plus a chunk list that overlaps and is therefore bigger than the
    # file. That is the PandaOS crash `P14-07` cites, in this tree, and nothing
    # capped it. 32 MiB is about four times the largest file in any real
    # document set measured here and costs ~105 MB at the same multiplier.
    #
    # `index_budget_mb` is the other half: the keyword index holds every chunk
    # for the life of the process (105 MB of notes measured at 131,200 chunks
    # and 137 MB of RSS) and had no ceiling at all. Past it a file is still
    # listed, with the reason and this setting's name on it.
    #
    # SETTINGS-ONLY, for the reason spelled out at `events_retention_days`
    # above: an env fallback beneath a truthy default is unreachable code.
    "index_max_file_mb": 32,
    "index_budget_mb": 256,
    # `P15-08`. The floor under a schedulable task, in minutes. `0` turns it off.
    #
    # The cron field is free text and only its SYNTAX was checked, so
    # `* * * * *` was accepted: 1,440 runs a day, each able to open IMAP, walk
    # the search providers and call a model API. `P15` exists because this
    # product got its owner's IP soft-banned in an afternoon, and this is that
    # afternoon on a timer. The product's own `check_email_urgency` shipped at
    # `*/15` and had to be walked back to hourly with a migration, so the
    # failure is not hypothetical here either.
    #
    # Five minutes is a floor, not a recommendation — 288 runs a day is still
    # more than any job this product ships. An operator whose tasks only touch
    # their own machines can lower it; what they cannot do is get a
    # minute-by-minute provider poll by not thinking about it (`Law 1`).
    #
    # SETTINGS-ONLY, for the reason spelled out at `events_retention_days`.
    "min_task_interval_minutes": 5,
    # Serve GET /metrics for a Prometheus scrape (`P16-12`). Ships OFF.
    #
    # Off is not shyness about telemetry — `Law 16` clause 4 explicitly permits
    # it, and a scrape has no destination to permit. Off because a monitoring
    # endpoint nobody configured is attack surface nobody asked for, and because
    # the operator turning it on is the same act as pointing something at it.
    #
    # Falsy, so PANTHEON_METRICS_ENABLED is genuinely reachable beneath it.
    #
    # `None` rather than `False` — `B90`. Reachable was never the problem here;
    # *unbeatable* was. See `allow_model_download` above.
    "metrics_enabled": None,
    # Push the same readings to the operator's OWN collector (`P16-19`).
    #
    # SHIPS EMPTY, AND EMPTY IS ENFORCED, NOT MERELY INTENDED:
    # `.pantheon/check-destinations.py` fails the build if a destination-shaped
    # key is truthy. This is the first legitimate outbound address in the
    # product, so it is the first place a well-meant default could land.
    #
    # The address IS the switch — there is no separate on/off boolean, because a
    # second control can disagree with the first and the failure it enables
    # (enabled, blank, operator waiting) is worse than the one it prevents.
    #
    # Falsy, so PANTHEON_OTLP_ENDPOINT beneath it is genuinely reachable (H06,
    # B20). Either the base URL or the full `/v1/metrics` one; both are taken.
    "otlp_endpoint": "",
    # Where this instance's Corresponding Source lives (`P0-17`, AGPL-3.0 §13).
    #
    # SHIPS EMPTY, AND EMPTY MEANS THE CONTROL DOES NOT RENDER. §13's
    # obligation attaches to whoever *offers* a modified version over a
    # network; until an operator does that there is nothing to offer, and a
    # link to a repository a stranger 404s on is an offer that cannot be
    # honoured — worse than no link, which is what `B25` cost once already.
    #
    # The address is the switch and there is no boolean beside it
    # (`D-2026-09-05-01`, `D-2026-09-08-06`). Not a destination in the
    # `Law 16` sense — nothing here is fetched, it is an href the user's own
    # browser follows — but it is `*_url`-shaped, so
    # `.pantheon/check-destinations.py` holds the empty default for us.
    #
    # Falsy, so PANTHEON_SOURCE_URL beneath it is genuinely reachable (H06, B20).
    "source_url": "",
    # Seconds between pushes. Floored at 10 in code — the loop is the one
    # request in the product that fires whether or not anyone is watching, and
    # a one-second metrics tick is a self-inflicted rate limit (`P15`).
    "otlp_interval_seconds": 60,
    # Headers the operator's collector requires, e.g. an API key. Values are
    # never logged; a metrics exporter that prints its own credentials into the
    # application log has moved the secret somewhere handled less carefully than
    # the settings store it came from.
    "otlp_headers": {},
    # OTLP resource attributes, merged over `service.name` and `service.version`.
    # This is where `service.instance.id` goes if several Pantheons report to
    # one collector — the product does not invent an identity for the operator.
    "otlp_resource_attributes": {},
    # Named network segments (`P16-16`). Ships EMPTY, and empty means "behave
    # exactly as before": nothing is declared, nothing is scoped, and every
    # existing path runs unchanged.
    #
    # A network the operator NAMED is a network they linked, so this is `Law 16`
    # working as intended rather than an exception to it — the law is about
    # defaults, not capability.
    #
    # [{"name": "lab", "cidrs": ["10.9.0.0/24"], "hosts": ["lab-gpu.lan"],
    #   "trust": "limited", "enabled": true, "notes": "…"}]
    "networks": [],
    # `P17-01`. Where the network agent listens, and the credential Pantheon
    # presents to it. **Both ship empty and that is the whole default**: with no
    # address there is no agent, nothing is called, and this changes nothing
    # (`Law 16` — we drop external dependence unless the user explicitly links
    # it, and a process on your own host is still something you linked).
    #
    # `netagent_url` is destination-shaped, so `check-destinations.py` requires
    # it to ship empty regardless — consent makes a destination lawful to USE,
    # never lawful to SHIP (`D-2026-08-31-01`).
    #
    # `netagent_token` ends in "token", so `_is_secret` already classifies it:
    # the agent may read the setting name and may never write the value, and
    # `scrub_settings` masks it for a non-admin. That is inherited rather than
    # declared, which is the point of the suffix rule.
    "netagent_url": "",
    "netagent_token": "",
    # `P17-11`. **Your** list, beside the agent's. The agent's nuclear denylist
    # is compiled into it, on the host, and nothing here can widen it — that is
    # the boundary. These two narrow what Pantheon will even ASK for, and are
    # checked before a command leaves the container.
    #
    # Both are plain substring patterns matched against a normalised command,
    # not regexes — the same call `src/tool_allow_rules.py` made, for the same
    # reason: a typo in a regex widens a security-shaped rule silently, and `.*`
    # is a very easy typo.
    #
    # `host_exec_allowlist`, when non-empty, wins: only those leading binaries
    # may run, and the denylist still applies inside them. Empty means "no
    # opinion", which is the shipped state for both.
    "host_exec_denylist": [],
    "host_exec_allowlist": [],
    # Eval suites (`P14-03`). Ships empty; a suite is a name plus a list of
    # receipts to replay and what to expect of each:
    #
    # [{"name": "regressions", "cases": [
    #     {"run_id": "…", "label": "tool loop finishes",
    #      "expect": {"contains": ["done"], "max_tool_failures": 0}}]}]
    #
    # In settings rather than a table, following `networks` — a handful of ids
    # and strings, edited rarely. `P14-06` is the row that decides the store
    # when a suite outgrows this, which is a decision to make on evidence rather
    # than to pre-empt.
    "eval_suites": [],
    # What to do with images in content the user did not write — model output, a
    # RAG document, an email. `ask` (default) renders a placeholder naming the
    # host until someone clicks; `proxy` fetches through /api/img automatically,
    # so the browser still never talks to the third party; `block` never fetches.
    #
    # `ask` is the default because a proxy alone only moves the beacon one hop:
    # the request still leaves the machine for content nobody chose. Mail is
    # full of tracking pixels and this is the setting that answers them.
    "remote_images": "ask",
    # How many scheduled tasks may hold the model slot at once. 1 preserves the
    # behaviour this was hardcoded to; the resolver in src/task_scheduler.py
    # clamps to [1, 16] and reads this layer between the env var and the
    # built-in default. Raising it lets DIFFERENT tasks overlap — a single task
    # still never runs twice concurrently, which `_executing` guarantees
    # separately. See P6-08.
    "task_concurrency_cap": 1,
    # ── The ten byte caps (`P12-01`) and the four throttles (`P12-05b`) ──
    #
    # All fourteen ship `None`, and `None` is the only value that means
    # "nothing is stored here — let the environment or the built-in default
    # answer". `B90` established the third value for booleans; an integer needs
    # it for the same reason, because `load_settings` merges this dict on every
    # read and a shipped number would make every layer beneath it unreachable
    # (`H06`, `B20`). Resolution is `settings.resolve_limit`:
    # **role profile → instance setting → env → built-in default.**
    #
    # The built-in defaults are NOT repeated here. Each number belongs to the
    # module that enforces it — `src/upload_limits.py`, `routes/backup_routes.py`,
    # `services/tts/tts_service.py`, `routes/auth_routes.py`,
    # `src/upload_handler.py` — and writing them a second time here is the
    # defect `B63` names ("the number belongs to the code that uses it").
    #
    # Each key is spelled as its environment variable minus the `PANTHEON_`
    # prefix, lowercased, so an operator who already knows the variable can
    # find the setting (`Law 15`) and `.pantheon/check-env-declared.py` can
    # match the two.
    "gallery_upload_max_bytes": None,
    "gallery_transform_upload_max_bytes": None,
    "memory_import_max_bytes": None,
    "personal_upload_max_bytes": None,
    "email_compose_upload_max_bytes": None,
    "stt_max_audio_bytes": None,
    "ics_max_bytes": None,
    "chat_upload_max_bytes": None,
    "backup_import_max_bytes": None,
    "tts_cache_max_bytes": None,
    # The throttles. `P12-05b`: these were literals — `15/60`, `3/300`, `3/300`
    # in `routes/auth_routes.py` and `self.upload_rate_limit = 60` in
    # `src/upload_handler.py` — so after every other row in this phase landed,
    # an operator still could not change a throttle without a rebuild. That is
    # the thing the owner asked for by name ("adding admin controls, such as
    # throttling and such").
    #
    # SETTINGS-ONLY. No `PANTHEON_*` variable is added for any of them: none
    # exists today, so `Law 1` requires nothing, and a new variable is a new
    # place the same number can be set (`Law 13`). The reasoning is
    # `events_retention_days`'.
    #
    # **There is no value meaning "off".** `FORBIDDEN.md` Part 2 lists the auth
    # rate limiters as a control that never lifts, so `resolve_limit` is called
    # with `minimum=1` and the panel cannot be talked down to zero. Making the
    # number policy is not the same act as removing the limiter, and the floor
    # is what keeps the two apart. The agent may read these and may not write
    # them — see `_SELF_RESTRAINT_KEYS` in `src/agent_tools/admin_tools.py`:
    # a credential-stuffing throttle that prompt injection can raise is not a
    # throttle.
    "auth_login_rate_limit": None,
    "auth_login_rate_window_seconds": None,
    "auth_signup_rate_limit": None,
    "auth_signup_rate_window_seconds": None,
    "auth_setup_rate_limit": None,
    "auth_setup_rate_window_seconds": None,
    "upload_rate_limit": None,
    "upload_rate_window_seconds": None,
    # How often the approval gate asks (P7-03). The values are `TrustRung` in
    # src/tool_capabilities.py; `resolve_trust_rung` in src/agent_loop.py reads
    # this layer and every run resolves it once at start. The default is what
    # every install already did — a clean run is never gated and the gate arms
    # once untrusted content enters — so shipping this key changes nothing until
    # someone moves it. A value that is not a rung resolves back to this default
    # rather than to the strictest rung; `coerce_trust_rung` argues that case.
    # Global, deliberately not in `_PER_USER_KEYS`: a per-user copy would let a
    # non-admin lower their own confirmation gate.
    "trust_rung": "gate_on_untrusted",
    "image_gen_enabled": False,
    "image_model": "",
    "image_quality": "medium",
    "vision_model": "",
    "vision_enabled": True,
    # Ordered fallback chain for the Vision model (image analysis, OCR, tagging).
    "vision_model_fallbacks": [],
    # Public base URL used to build clickable deep-links in outgoing alerts
    # (e.g., urgency alert email). Example: "https://chat.example.com"
    "app_public_url": "",
    "tts_enabled": True,
    "tts_provider": "disabled",
    "tts_model": "tts-1",
    "tts_voice": "alloy",
    "tts_speed": "1",
    "stt_enabled": False,
    "stt_provider": "disabled",
    "stt_model": "base",
    "stt_language": "",
    "search_provider": "searxng",
    # Empty by default as of 2026-08-31 (`Law 16`). This shipped as
    # `["duckduckgo"]` on the reasoning that it is free and needs no API key —
    # both true, and neither is the question. The question is whether a person
    # who installed a self-hosted product and typed a search expects the query
    # to leave their machine. On a native install SearXNG is not running at all,
    # so the primary provider always failed and **every search went to
    # DuckDuckGo** — scraped from an HTML endpoint under a spoofed desktop
    # user-agent, which is also how you get that IP blocked.
    #
    # Adding a fallback is one line in Settings and it is the user's line to add.
    "search_fallback_chain": [],
    "search_url": "",
    "search_result_count": 5,
    # SafeSearch level applied to every provider that exposes one.
    # "strict"   — apply the provider's strongest filtering level (default;
    #              keeps unrelated low-quality/spam recommendations out)
    # "moderate" — provider-default filtering behavior
    # "off"      — disable filtering entirely (advanced users only)
    #
    # Providers that honor this setting (translated to each provider's native
    # param in src/search/providers.py:_safesearch_for):
    #     SearXNG       safesearch=0/1/2 (JSON API, HTML scrape, news fallback)
    #     Brave Search  safesearch=off/moderate/strict
    #     DuckDuckGo    safesearch=off/moderate/on (library + HTML kp param)
    #     Google PSE    safe=active (omitted for "off"; PSE has no middle tier)
    #     Serper.dev    safe=active (omitted for "off"; proxies Google's `safe`)
    # Providers NOT touched: Tavily (no SafeSearch knob; filters at index time)
    # and any custom backend reached via search_url — they keep whatever the
    # backend itself decides, so operators stay in control of self-hosted /
    # niche search instances.
    "search_safesearch": "strict",
    "brave_api_key": "",
    "google_pse_key": "",
    "google_pse_cx": "",
    "tavily_api_key": "",
    "serper_api_key": "",
    "research_endpoint_id": "",
    "research_model": "",
    "research_search_provider": "",
    "research_max_tokens": 16384,
    "research_extraction_timeout_seconds": 90,
    # Lightweight planning/query LLM calls happen before any search starts.
    # Keep them separately tunable so slow local backends are not capped by
    # the old 30s/60s per-call defaults.
    "research_planning_timeout_seconds": 90,
    "research_query_timeout_seconds": 90,
    "research_extraction_concurrency": 3,
    # Hard wall-clock cap on a single deep-research run. The previous 600s
    # (10 min) default cut off slow local / edge LLMs mid-synthesis; 1800s
    # (30 min) is comfortable for most local setups while still bounding
    # runaway jobs. Set to 0 to disable the cap entirely (unlimited) — only
    # for very long deep-research runs, since a stalled job then runs an
    # unbounded model/API bill. Other values are bounded to [60, 86400].
    # Tune via Settings or by editing data/settings.json.
    "research_run_timeout_seconds": 1800,
    "agent_max_tool_calls": 0,
    "agent_max_rounds": 20,  # per-message agent step cap (clamped 1..200)
    # `P3-21` / `D-2026-09-08-02`. The local-inference `max_tokens` ceiling:
    # how many tokens THIS MACHINE is willing to generate for one reply when
    # inference is local. It is a property of the hardware, not of the preset —
    # the owner's words: "This is the machines defined max_tokens integer — it
    # can change if I put everything on stronger hardware instead of my gaming
    # pc." Until this key existed it was a literal inside
    # `src/agent_loop._resolve_local_lifts`, so the only way to answer "what
    # does this box actually do" was to edit source.
    #
    # A preset's own `max_tokens` is a FLOOR, never a cap: the effective value
    # is `max(preset, this)`, so raising a preset above the ceiling still
    # works and lowering the ceiling never truncates a preset that asked for
    # more. Set 0 to turn the lift off entirely and run presets at their own
    # numbers. Clamped to [0, 10_000_000]. No effect on cloud endpoints, which
    # never get the lift at all.
    "local_inference_max_tokens": 1_000_000,
    # Soft input-token budget for the agent loop. The DEFAULT value (6000) is the
    # "auto" sentinel: it means "scale the budget to the model's context window"
    # (#1230) — so long-context models aren't capped at 6000. Set ANY OTHER value
    # to enforce an explicit cap (clamped to the window only — hard_max does not
    # apply to explicit budgets, #1230); set 0 to disable soft-trimming. The
    # default is treated as auto because the settings-save path materializes
    # defaults, so a persisted 6000 can't be told apart from a deliberate 6000 —
    # to pin a budget near the default, use a nearby value (e.g. 5999).
    "agent_input_token_budget": 6000,
    # Ceiling on the *auto-derived* input budget; a configurable setting since #1273
    # (the merged #1230 left it a module constant). No effect on an explicit budget
    # — a deliberate value is honoured (#1230). Default matches
    # `src.context_budget.DEFAULT_HARD_MAX`; lower this for
    # cost-paranoid setups, raise it on premium APIs with very large windows you
    # want to actually use (e.g. 900_000 to fill a 1M-context model). See
    # `compute_input_token_budget`.
    "agent_input_token_hard_max": 200_000,
    "agent_stream_timeout_seconds": 300,
    # Extra directory roots that read_file / write_file may access, in
    # addition to the built-in project data/ and system temp dirs. Each
    # entry is an absolute path. Sensitive subpaths (.ssh, .gnupg, shell
    # rc files, SSH key files) are always blocked regardless of roots.
    # `H16`. `tool_path_extra_roots` IS declared and therefore settable
    # through the admin route — what it has never had is a control, and it is
    # not getting one. It widens where `read_file` / `write_file` may reach,
    # and `_resolve_tool_path` is one of the controls `FORBIDDEN.md` Part 2
    # says never lifts. The sensitive-basename block (`.ssh`, `.gnupg`, shell
    # rc files, key files) holds whatever roots are listed, so a UI would not
    # breach the boundary — but it would put "point the agent at my home
    # directory" one click away, and the row's own `Verify` allows
    # "documented as deliberately expert-only" for exactly this case. Edit
    # `data/settings.json`, or ask the agent, and know why you are doing it.
    "tool_path_extra_roots": [],
    # The four below were read by live code and **absent from this dict**, and
    # this dict is the allowlist: `POST /api/auth/settings` iterates
    # `for key in DEFAULT_SETTINGS`, so a key that is not here is silently
    # dropped from any save, and `manage_settings` refuses it. The only writer
    # was hand-editing JSON. Each is declared with the exact default its
    # reader already falls back to, so nothing changes behaviour today —
    # declaring them only makes them reachable. (`H16`)
    #
    # A fresh-context verifier that independently checks effectful turns
    # before accepting "done". Default OFF and staying off: on weak local
    # models it cannot judge from the action snapshot, false-rejects, and
    # forces a costly extra round on every effectful turn. Worth having on a
    # strong model, which is why it needs a switch.
    "agent_verifier_subagent": False,
    # The nightly skill audit: test and judge the least-recently-checked
    # skills, auto-fixing or escalating weak ones. Never deletes.
    "skill_audit_nightly": True,
    "skill_audit_hour": 2,      # local hour, spread across the following five minutes
    "skill_audit_batch": 8,     # skills per night; the library rotates
    "task_endpoint_id": "",
    "task_model": "",
    "default_endpoint_id": "",
    "default_model": "",
    # Optional prose style used only for normal document writing/editing.
    # Email replies use email_writing_style instead because greetings,
    # signatures, and mailbox identity rules are medium-specific.
    "document_writing_style": "",
    # Legacy ordered fallback chain for the default chat model. Values remain
    # stored for compatibility and rollback reference, but model routing no
    # longer reads this key.
    "default_model_fallbacks": [],
    # When True, non-admin users inherit the global default model/endpoint when
    # they have no personal defaults. When False, users only use their personal
    # defaults. Default is False.
    "share_defaults_with_users": False,
    "utility_endpoint_id": "",
    "utility_model": "",
    # Ordered fallback chain for the Utility model (summarization, naming,
    # tidy actions, etc.).
    "utility_model_fallbacks": [],
    "teacher_model": "",
    "teacher_enabled": False,
    "teacher_tier2_enabled": False,
    # Skills: minimum self-reported confidence for an auto-written (LLM-authored)
    # DRAFT skill to be injected into the agent prompt. Published skills always
    # qualify. Keeps low-confidence auto-skills out of context until they're
    # vetted/published. 0 disables the gate.
    "skill_autosave_min_confidence": 0.85,
    # Max relevant skills injected into the prompt for one request. The skills
    # library can grow beyond this; cleanup/retirement is an explicit review flow.
    "skill_max_injected": 3,
    # Reminders
    "reminder_channel": "browser",   # "browser" | "email" | "ntfy" | "webhook"
    "reminder_llm_synthesis": False,
    "reminder_llm_persona": "",
    "reminder_ntfy_topic": "Reminders",
    "reminder_email_to": "",
    # Generic outbound webhook channel: pick any saved Integration as the
    # target and supply a JSON payload template. Use {{title}} and {{message}}
    # as placeholders — they are JSON-escaped before substitution, so the
    # rendered string is always valid JSON. Works with Discord, Slack, Teams,
    # ntfy (JSON mode), or any service that accepts a POST with a JSON body.
    "reminder_webhook_integration_id": "",
    "reminder_webhook_payload_template": "",
    # Email triage scanner rules. Running/paused state and schedule live in
    # Tasks via the built-in `check_email_urgency` task.
    "urgent_email_prompt": (
        "Flag as urgent: explicit deadlines, time-sensitive requests, "
        "work-blocking issues, messages from people I report to, or anything "
        "where a delayed reply costs money/trust. Someone waiting outside, "
        "at the door, locked out, or unable to get in is urgent now. "
        "Newsletters, marketing, automated digests, and FYI-only updates are "
        "NOT urgent."
    ),
    # Keyboard shortcuts (action: key combination)
    "keybinds": {
        "search": "ctrl+k",
        "toggle_sidebar": "ctrl+b",
        "new_session": "ctrl+alt+n",
        "star_session": "ctrl+alt+s",
        "delete_session": "ctrl+alt+d",
        "admin_panel": "ctrl+shift+u",
        "cancel": "escape",
    },
}


# The nullable integer limits, with the bounds every layer is held to.
#
# `P11-02` moved this here from a local inside `POST /api/auth/settings`, where
# it was spelled `_NULLABLE_INT_RANGES`, because a second reader arrived: a
# role is a named set of overrides and it has to refuse the same keys the
# settings route refuses, or an operator can put a byte cap in a role that the
# settings panel would have rejected. Two lists answering "which settings keys
# are limits" is the fork in the maintenance path `Law 14` exists to stop, and
# the route still validates through this dict under its own name.
#
# **The floor is 1 on every one of them and there is no value meaning *off*.**
# `FORBIDDEN.md` Part 2 keeps the upload caps and the auth rate limiters as
# controls that never lift; a cap of zero rejects every upload while reading as
# a configured limit. The ceilings are sanity rather than policy — a terabyte
# cap and a day-long throttle window are past the point where the number is a
# decision rather than a typo.
_GIB = 1024 ** 3
LIMIT_RANGES: dict[str, tuple[int, int]] = {
    "gallery_upload_max_bytes": (1, 1024 * _GIB),
    "gallery_transform_upload_max_bytes": (1, 1024 * _GIB),
    "memory_import_max_bytes": (1, 1024 * _GIB),
    "personal_upload_max_bytes": (1, 1024 * _GIB),
    "email_compose_upload_max_bytes": (1, 1024 * _GIB),
    "stt_max_audio_bytes": (1, 1024 * _GIB),
    "ics_max_bytes": (1, 1024 * _GIB),
    "chat_upload_max_bytes": (1, 1024 * _GIB),
    "backup_import_max_bytes": (1, 1024 * _GIB),
    "tts_cache_max_bytes": (1, 1024 * _GIB),
    "auth_login_rate_limit": (1, 100_000),
    "auth_login_rate_window_seconds": (1, 86_400),
    "auth_signup_rate_limit": (1, 100_000),
    "auth_signup_rate_window_seconds": (1, 86_400),
    "auth_setup_rate_limit": (1, 100_000),
    "auth_setup_rate_window_seconds": (1, 86_400),
    "upload_rate_limit": (1, 100_000),
    "upload_rate_window_seconds": (1, 86_400),
}


def without_retired_settings(settings: dict) -> dict:
    """Return a shallow copy suitable for generic settings interfaces."""
    if not isinstance(settings, dict):
        return {}
    return {
        key: value
        for key, value in settings.items()
        if key not in RETIRED_SETTING_KEYS
    }

DEFAULT_FEATURES = {
    "web_search": True,
    "web_fetch": True,
    "deep_research": False,
    "memory": True,
    "document_editor": True,
    "rag": True,
    "sensitive_filter": True,
    "gallery": True,
}


# ── Settings (data/settings.json) ──

def load_settings() -> dict:
    """Load settings merged with defaults. Always returns a complete dict."""
    global _settings_cache
    now = time.monotonic()
    if _settings_cache and (now - _settings_cache[0]) < _CACHE_TTL:
        return _settings_cache[1]
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError("settings must be an object")
        merged = {**DEFAULT_SETTINGS, **saved}
    except FileNotFoundError:
        merged = dict(DEFAULT_SETTINGS)
    except (PermissionError, json.JSONDecodeError, ValueError) as exc:
        # `P3-16`. The file is there and could not be read, which is a
        # different thing from "no settings have been saved yet" — and the
        # difference matters because nearly every writer in this codebase is
        # `s = load_settings(); s[key] = value; save_settings(s)`. Returning
        # defaults from here and letting that run persists the defaults over
        # the operator's real configuration, credentials included. Callers keep
        # working on defaults so the app stays up; `save_settings` refuses to
        # write while the file is in this state.
        #
        # Deliberately not cached. A two-second-old set of defaults that
        # outlives the operator's repair is exactly long enough for the next
        # save to find a readable file and write the defaults into it.
        logger.error(
            "settings.json exists but could not be read (%s: %s) — running on "
            "defaults, and saves are refused until it can be read",
            exc.__class__.__name__, exc,
        )
        return dict(DEFAULT_SETTINGS)
    _settings_cache = (now, merged)
    return merged


def save_settings(settings: dict):
    """Persist settings to disk (atomic; see core.atomic_io).

    `preserve_unreadable`: this file holds credentials a person typed and is
    written by ~20 read-modify-write call sites. `P3-16`.
    """
    from core.atomic_io import atomic_write_json
    atomic_write_json(SETTINGS_FILE, settings, indent=2, preserve_unreadable=True)
    _invalidate_caches()


def get_setting(key: str, default: Any = None) -> Any:
    """Read a single setting value."""
    return load_settings().get(key, default)


def setting_is_explicit(key: str, *, default: Any = _UNSET) -> bool:
    """True if ``key`` in the saved file is a deliberate operator choice.

    This is the two-signal version of the question `is_setting_overridden` and
    `context_budget.budget_is_explicit` each answer with one signal, and it
    exists because neither signal is sufficient on its own:

    * **Presence** alone is wrong *after* a save. `POST /api/auth/settings`
      does `current = load_settings()` — which merges `DEFAULT_SETTINGS` — and
      writes the whole dict back, so one admin save materialises **every**
      default into `settings.json`. Every key is then "present", including the
      ones nobody has ever looked at. (`H06` and this docstring both said
      "~200"; `B20` re-drove it on an empty data directory and counted 89 —
      the count that matters is `len(DEFAULT_SETTINGS)`, which a test now
      asserts rather than a comment claiming a number that rots.)
    * **Value** alone is wrong *before* a save. With no file at all,
      `get_setting(key, None)` still returns the shipped default, because the
      merge happens on every read. A caller comparing to the default cannot
      tell "no file" from "someone typed the default".

    Presence AND a non-default value is the honest answer: it is true only when
    the file says something, and says something other than what we ship.

    The cost is stated rather than hidden: **an operator who deliberately
    chooses the default value is indistinguishable from a materialised
    default**, and a lower layer will win. That is a property of storing
    settings as a flat merged dict, not of this function, and it is the same
    limit `agent_input_token_budget` documents in `DEFAULT_SETTINGS` ("to pin a
    budget near the default, use a nearby value"). It only bites when a lower
    layer is *also* configured — i.e. the operator set an env var and then
    picked the default in the UI — and in that case honouring the environment
    is the better of two guesses, because the environment is the only one of
    the two we know was typed on purpose.

    ``default`` may be passed for keys outside ``DEFAULT_SETTINGS``; otherwise
    the shipped default is used, and an unknown key with no default is never
    explicit.
    """
    if default is _UNSET:
        if key not in DEFAULT_SETTINGS:
            return False
        default = DEFAULT_SETTINGS[key]
    if not is_setting_overridden(key):
        return False
    return load_settings().get(key) != default


def env_backed(settings: dict, key: str, env_name: str, default: str = "") -> str:
    """A stored string, falling back to the environment when it is *blank*.

    `settings.get(key, os.environ.get(env, ""))` is the idiom this replaces and
    it does not do this: a dict default fires only on **absence**, and the UI
    writes `""` for a cleared field rather than dropping the key. One save of a
    blank box therefore masks the environment permanently, with no error and
    nothing in the settings file that looks wrong — the operator sees their own
    empty string.

    Blank means unset here. An operator who wants a credential *off* on a host
    whose environment still defines it should unset it in the environment,
    which is where it was set; the UI cannot unset a variable in the process
    environment and must not pretend it can.

    Takes the dict rather than reading it so the two callers that parse
    `settings.json` themselves (contacts, email) can use the same rule as the
    ones going through `load_settings`.
    """
    import os
    stored = settings.get(key)
    if isinstance(stored, str) and stored.strip():
        return stored
    if not isinstance(stored, str) and stored not in (None, ""):
        # A non-string that is not empty (an int port, a bool) is a real value.
        return stored
    return os.environ.get(env_name) or default


_warned_stored_no: set[str] = set()


def _warn_stored_no_beats_env(key: str, env_name: str) -> None:
    """Say so, once, when a stored `False` is the reason an env var lost.

    `B90`'s `Law 1` cost, made visible rather than argued away. Before
    2026-09-15 these keys shipped `False`, so one admin save materialised a
    `False` that nobody chose, and the environment beat it. Now a stored `False`
    wins — which is the fix — but on an install carrying such a materialised
    `False` **and** a truthy variable, the behaviour changes at upgrade.

    That is exactly the pair this fires on, so it is silent on every install
    that is not affected. A migration would have been the alternative and there
    is no mechanism for one: `data/settings.json` carries no schema version, and
    a materialised `False` is byte-identical to a chosen one, so a rewrite would
    have had to guess at intent for the one case where intent is the question.
    Telling the operator which layer answered is the honest half of the
    `public_origin.source_of` answer `B90` weighed, kept where it costs nothing.
    """
    if key in _warned_stored_no:
        return
    from src.env_flags import env_truthy
    import os
    if env_truthy(os.environ.get(env_name)) is not True:
        return
    _warned_stored_no.add(key)
    logger.warning(
        "%s is set in the environment and %s is stored false in settings.json — "
        "the stored value wins (`B90`). Before 2026-09-15 the environment won "
        "here, including over a false nobody chose. To let %s decide again, "
        "remove %s from data/settings.json.",
        env_name, key, env_name, key,
    )


def env_backed_flag(settings: dict, key: str, env_name: str,
                    default: bool = False) -> bool:
    """`env_backed` for a boolean: stored choice → environment → default.

    `B90`. Three keys resolved as `bool(get_setting(K, False)) or <env truthy>`
    and an `or` is one-way: `metrics_enabled`, `searxng_widen_engines` and
    `allow_model_download` all stored `False` and all three measured effective
    `True` on a host whose environment set them. The operator's *off* was not
    overridden loudly — it was not read at all.

    `setting_is_explicit` is the wrong tool and that is not a defect in it: the
    stored `False` **was** the shipped default, so presence-and-a-non-default-
    value is correctly `False`. The fix had to be in the storage shape, and it
    is: those three keys now ship `None`. `env_backed` already resolves stored →
    environment → default in exactly the order the rest of this tree documents,
    and already returns a stored `False` in preference to the environment — this
    is that function with the one thing it cannot do, which is decide what an
    environment *string* means. `bool("false")` is `True`; the coercion belongs
    to `env_flags.env_truthy` and not to an eleventh inline spelling (`B91`).

    So this is not a third layering rule. It is `env_backed` plus the shared
    vocabulary, and the reason it is a function rather than two lines at each of
    the three call sites is that two lines at each of three call sites is how
    this row was written in the first place (`Law 13`).
    """
    return _resolve_env_backed_flag(settings, key, env_name, default)[0]


def env_backed_flag_source(settings: dict, key: str, env_name: str,
                           default: bool = False) -> str:
    """Which layer answered `env_backed_flag`: `"settings"`, `"environment"`
    or `"default"`.

    `B95`. The panel cannot honestly offer a three-state control without this.
    All three of these keys ship `None` (`B90`), so the control has to express
    *use the environment or the default*, *yes* and *no* — and the first of
    those three is a different sentence depending on whether a variable is
    actually set on this host. `PANTHEON_ALLOW_MODEL_DOWNLOAD=1` in a compose
    file means "unset" reads as **yes**, and a panel that says "unset" without
    saying so is telling an operator their `Law 16` gate is shut when it is open.

    Same answer shape as `routes/contacts/contacts_routes._carddav_sources`,
    which reports `"settings"` / `"environment"` / `""` per field for exactly
    this reason, and the half of `public_origin.source_of` that `B90`
    deliberately took only the logging of. `"default"` rather than `""` because
    a boolean always has an answer — there is no "unconfigured" state where the
    flag is neither on nor off.

    Derived from the same resolution as the value, not transcribed beside it: a
    second copy of the layering rule is how `B90` happened (`Law 13`).
    """
    return _resolve_env_backed_flag(settings, key, env_name, default)[1]


def _resolve_env_backed_flag(settings: dict, key: str, env_name: str,
                             default: bool) -> tuple[bool, str]:
    """The one resolution. Returns `(effective, source)`.

    Private because callers want one or the other and asking for both by name
    reads better at the call site; it is one function so the value and the
    story about the value can never disagree (`B95`).
    """
    from src.env_flags import env_flag, env_truthy
    stored = settings.get(key)
    if isinstance(stored, bool):
        # A stored bool is a typed choice out of `settings.json`. It outranks
        # the environment — the order every other layer pair in this tree
        # documents, and the one `env_backed` already implements for strings.
        if not stored:
            _warn_stored_no_beats_env(key, env_name)
        return stored, "settings"
    if stored is not None and not isinstance(stored, str):
        return bool(stored), "settings"
    # A string in a boolean slot is somebody hand-editing the file. Judge it by
    # the same vocabulary the environment is judged by rather than by
    # truthiness, or `"false"` reads as yes.
    answer = env_truthy(stored) if isinstance(stored, str) else None
    if answer is not None:
        return answer, "settings"
    import os
    if env_truthy(os.environ.get(env_name)) is not None:
        return env_flag(env_name, default), "environment"
    return env_flag(env_name, default), "default"


# The keys whose value is `stored choice → environment → default`, with the
# variable that answers for each and the shipped answer when nothing does.
#
# `B95`. A registry rather than three pairs of strings repeated at three call
# sites and then a fourth time in the panel: the panel has to enumerate them —
# it cannot ask "which settings are env-backed flags?" of a flat dict — and an
# enumeration that lives in JavaScript is the layering rule in a second place
# (`Law 13`). The three resolvers keep spelling their own key and variable at
# the call site, because a resolver that looked its own name up in a table
# would be harder to read than the pair it replaced; this table is checked
# against them by a test rather than by being their only source.
ENV_BACKED_FLAGS = {
    "allow_model_download": ("PANTHEON_ALLOW_MODEL_DOWNLOAD", False),
    "searxng_widen_engines": ("SEARXNG_WIDEN_ENGINES", False),
    "metrics_enabled": ("PANTHEON_METRICS_ENABLED", False),
}


def env_backed_flag_report(settings: dict | None = None) -> dict:
    """Every tri-state flag, with the layer that answered and what it answered.

    `B95`. One call for the whole panel, because three round trips to learn
    three answers to the same question is three chances to render half of them.
    `env_set` is reported separately from `source`: a host can define the
    variable and still be answered by `settings`, and an operator deciding
    whether to clear their stored choice needs to know what is underneath it.
    """
    import os
    if settings is None:
        settings = load_settings()
    out = {}
    for key, (env_name, default) in ENV_BACKED_FLAGS.items():
        effective, source = _resolve_env_backed_flag(settings, key, env_name, default)
        from src.env_flags import env_truthy
        raw = os.environ.get(env_name)
        out[key] = {
            "effective": effective,
            "source": source,
            "env_name": env_name,
            "env_set": env_truthy(raw) is not None,
            "env_says": env_truthy(raw),
            "default": default,
            "stored": settings.get(key),
        }
    return out


def is_setting_overridden(key: str) -> bool:
    """True if ``key`` is explicitly present in the saved settings file.

    ``load_settings`` merges DEFAULT_SETTINGS with the saved file, so a value
    equal to its default is indistinguishable from "never set" via get_setting.
    Callers that must distinguish an explicit user choice from a default read
    the raw saved file via this. (Note: a materialized default is also "present",
    so value-sensitive callers should compare against the default — see
    ``context_budget.budget_is_explicit``.)
    """
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return isinstance(saved, dict) and key in saved
    except (FileNotFoundError, json.JSONDecodeError):
        return False



# ── Layered numeric limits (`P12-01`) ──────────────────────────────────────
#
# **role profile → instance setting → env → built-in default.** That order is
# `P12-01`'s, and `FORBIDDEN.md` Part 2 restates it over the upload byte caps
# ("the environment variable is the *override*, not the place a new limit
# goes"). It already existed once, spelled out by hand in
# `src/task_scheduler.resolve_task_concurrency_cap` for a single key; this is
# that resolution lifted to where the settings store lives, so the second,
# third and eleventh limit extend one rule instead of copying it (`Law 14`).
#
# Three things are deliberate here and each cost something to learn:
#
# * **`setting_is_explicit`, never `get_setting(key) is not None`.** `H06`:
#   `load_settings` merges `DEFAULT_SETTINGS` on *every* read, so a truthy
#   shipped default makes every layer below it unreachable code. That is how
#   `PANTHEON_TASK_CONCURRENCY_CAP` never worked on any install.
# * **A limit key ships `None`.** `B90`, applied to integers: `None` is the
#   third value a flat merged dict needs to tell *unset* from *an operator
#   typed this*. It also keeps the env leg genuinely reachable, which is what
#   `.pantheon/check-env-declared.py` fails the build over.
# * **A value that will not parse falls through with a warning; it does not
#   raise.** These resolve per request. The import-time constants in
#   `src/upload_limits.py` still fail fast on a bad environment value, so a
#   broken env var stops the process at boot rather than at an upload — this
#   leg is what answers once the process is already up.
#
# `minimum` is a floor, not decoration: `FORBIDDEN.md` Part 2 lists the auth
# rate limiters as a control that never lifts, so the throttle keys resolve
# through here with `minimum=1` and there is no value meaning *off*.

# The role layer is a registered function rather than a body to be filled in.
# `P11-02` builds roles as named overlays on `DEFAULT_PRIVILEGES`; when it
# lands it calls `set_role_limit_provider` once at start-up and every limit in
# the product inherits the layer in that one edit. The alternative — adding the
# layer at each call site once roles exist — is the second scaffolding `Law 14`
# exists to prevent, and `P12-02` (limit profiles attached to roles) is the row
# that fills this in.
#
# A registry rather than a constant `None` because it is also how a test drives
# the layer: the layer being unreachable and the layer answering `None` are two
# different states, and only one of them can be verified.

RoleLimitProvider = Callable[[str, Any], Any]

_role_limit_provider: RoleLimitProvider | None = None


def set_role_limit_provider(provider: RoleLimitProvider | None) -> None:
    """Install the function that answers "what does this owner's role say?".

    Nothing installs one today, which is the honest state of the layer and is
    said out loud on the `P12` rows rather than left for a reader to discover:
    **every limit here is resolvable per role and no role can currently set
    one**, because there are no roles.
    """
    global _role_limit_provider
    _role_limit_provider = provider


def clear_role_limit_provider() -> None:
    """Remove the provider. Tests use this; so does a role system being torn
    down. It differs from `set_role_limit_provider(None)` only in saying what
    it means at the call site."""
    set_role_limit_provider(None)


def role_limit_provider() -> RoleLimitProvider | None:
    """The installed provider, or `None`."""
    return _role_limit_provider


def role_limit(key: str, owner: str | None = None) -> Any:
    """What this owner's role profile says about `key`, or `None`.

    Never raises: a role system that throws must not take an upload route or an
    approval card down with it. The layer below answers instead.

    `owner` is the authenticated username, the same argument `get_user_setting`
    takes, so the eventual lookup has what it needs without a signature change.
    """
    provider = _role_limit_provider
    if provider is None:
        return None
    try:
        return provider(str(key or ""), owner)
    except Exception as exc:
        logger.warning("role limit provider failed for %s: %s", key, exc)
        return None


def _coerce_limit(raw: Any, *, source: str, minimum: int,
                  maximum: int | None, label: str) -> tuple[int, bool] | None:
    """Parse one candidate into `(value, was_clamped)`.

    `None` means 'not set / unusable — try the next layer'.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # `True` is an int in Python and a byte cap of 1 is not what anyone
        # meant. Refuse rather than silently cap every upload at one byte.
        logger.warning("Ignoring %s %s %r — not an integer", source, label, raw)
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Ignoring %s %s %r — not an integer", source, label, raw)
        return None
    clamped = max(minimum, value if maximum is None else min(value, maximum))
    if clamped != value:
        logger.warning(
            "%s %d from %s clamped to %d (allowed %d..%s)",
            label, value, source, clamped, minimum,
            "unbounded" if maximum is None else maximum,
        )
    # The flag rather than only the number, because "30 because you asked for
    # 30" and "30 because you asked for 0 and the floor is 30" are two
    # different answers and an operator setting a limit is entitled to know
    # which one they got (`Law 10`).
    return clamped, clamped != value


def resolve_limit(key: str, default: int, *, env_name: str | None = None,
                  owner: str | None = None, minimum: int = 1,
                  maximum: int | None = None,
                  label: str | None = None) -> tuple[int, str]:
    """Return `(value, source)` for one numeric limit.

    `source` is `"role profile"`, `"instance setting"`, the environment
    variable's own name, or `"built-in default"` — the same four answers
    `resolve_task_concurrency_cap` has returned since `P6-08`, because a
    caller that has to translate between two vocabularies will eventually
    translate one of them wrong.

    `env_name` is optional. A limit with no environment variable is not an
    oversight: `events_retention_days`, `index_max_file_mb` and
    `min_task_interval_minutes` all ship settings-only on the reasoning in
    `DEFAULT_SETTINGS`, and a new variable is a new place the same number can
    be set (`Law 13`). Pass one only where the variable already exists and
    `Law 1` requires it to keep working.
    """
    value, source, _clamped = resolve_limit_detail(
        key, default, env_name=env_name, owner=owner, minimum=minimum,
        maximum=maximum, label=label)
    return value, source


def resolve_limit_detail(key: str, default: int, *,
                         env_name: str | None = None,
                         owner: str | None = None, minimum: int = 1,
                         maximum: int | None = None,
                         label: str | None = None) -> tuple[int, str, bool]:
    """`resolve_limit`, plus whether the answer was clamped to the bounds.

    One implementation, two arities. Most callers want the number and do not
    care that 0 became 1; the settings route and the approval store do care,
    because *"saved"* and *"saved as something else"* are different things to
    tell an operator. Splitting it into a second resolver would be the second
    form of one thing (`Law 14`), so the detail is the implementation and
    `resolve_limit` drops the third value.
    """
    import os
    label = label or key
    role = _coerce_limit(role_limit(key, owner), source="role profile",
                         minimum=minimum, maximum=maximum, label=label)
    if role is not None:
        return role[0], "role profile", role[1]

    try:
        if setting_is_explicit(key):
            stored = _coerce_limit(load_settings().get(key),
                                   source="instance setting", minimum=minimum,
                                   maximum=maximum, label=label)
            if stored is not None:
                return stored[0], "instance setting", stored[1]
    except Exception:
        logger.debug("%s: settings read failed", label, exc_info=True)

    if env_name:
        from_env = _coerce_limit(os.environ.get(env_name), source=env_name,
                                 minimum=minimum, maximum=maximum, label=label)
        if from_env is not None:
            return from_env[0], env_name, from_env[1]

    # The built-in default goes through the same bounds as every other layer.
    # It has never been out of them, and a default that silently sits below its
    # own floor is exactly the kind of thing this tracker finds two rows later.
    fallback = _coerce_limit(default, source="built-in default",
                             minimum=minimum, maximum=maximum, label=label)
    if fallback is None:
        raise ValueError(f"{key}: built-in default must be an integer")
    return fallback[0], "built-in default", fallback[1]


# Per-user settings (user prefs override the global admin default). Used for
# keys that a user is allowed to choose individually — currently the vision
# model + image-generation model. The owner argument is the authed username
# resolved by FastAPI deps; an empty/None owner falls through to the global.
_PER_USER_KEYS = {
    "vision_model", "vision_enabled", "vision_model_fallbacks",
    "image_model", "image_gen_enabled", "image_quality",
    # Default chat endpoint / model — without per-user resolution every new
    # account inherited whatever the most-recent admin picked, which then
    # got injected into the chat composer on first open.
    "default_endpoint_id", "default_model",
    "utility_endpoint_id", "utility_model", "utility_model_fallbacks",
    "research_endpoint_id", "research_model",
}


def get_user_setting(key: str, owner: str = "", default: Any = None) -> Any:
    """Resolve `key` from the caller's per-user prefs first, falling back to
    the global setting. Only the small whitelist in `_PER_USER_KEYS` is
    eligible — for any other key this is equivalent to `get_setting(key)`.

    Falls back gracefully if the prefs module can't be imported (cycle/early
    boot) — admin-global settings keep working.
    """
    if owner and key in _PER_USER_KEYS:
        try:
            from routes.prefs_routes import _load_for_user
            prefs = _load_for_user(owner) or {}
            if key in prefs and prefs[key] not in (None, ""):
                return prefs[key]
        except Exception:
            pass
    return get_setting(key, default)


# ── Features (data/features.json) ──

def load_features() -> dict:
    """Load feature flags merged with defaults."""
    global _features_cache
    now = time.monotonic()
    if _features_cache and (now - _features_cache[0]) < _CACHE_TTL:
        return _features_cache[1]
    try:
        with open(FEATURES_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            raise ValueError("features must be an object")
        merged = {**DEFAULT_FEATURES, **saved}
    except FileNotFoundError:
        merged = dict(DEFAULT_FEATURES)
    except (PermissionError, json.JSONDecodeError, ValueError) as exc:
        # `P3-16`, same reasoning as `load_settings`. An admin who has switched
        # features off has expressed something that defaults cannot reproduce,
        # and `H05` is this project's record of what happens when a feature the
        # admin disabled comes back on by itself.
        logger.error(
            "features.json exists but could not be read (%s: %s) — running on "
            "defaults, and saves are refused until it can be read",
            exc.__class__.__name__, exc,
        )
        return dict(DEFAULT_FEATURES)
    _features_cache = (now, merged)
    return merged


def save_features(features: dict):
    """Persist feature flags to disk (atomic). `preserve_unreadable`: `P3-16`."""
    from core.atomic_io import atomic_write_json
    atomic_write_json(FEATURES_FILE, features, indent=2, preserve_unreadable=True)
    _invalidate_caches()
