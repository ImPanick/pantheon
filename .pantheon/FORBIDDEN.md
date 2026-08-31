# FORBIDDEN — names that do not move, controls that do not lift

Two lists. Both are absolute. If a task seems to require breaking one, stop and ask.

---

## PART 1 — Names that cannot be renamed

Renaming any of these breaks behaviour silently, fails CI, or resets stored user data.
Style them freely. Do not rename them.

| Name | Why |
|---|---|
| `.list-item` | Queried by the accessibility shim **and** the drag-sort module, and styled throughout. Rows also *contain* nested buttons, which is why the shim declines `role="button"` on them. Change the tag, keep the class. |
| `.send-btn` | **Eight modules mutate it** across five states. Any composer rework must reproduce the state machine exactly. |
| `.msg` · `.msg-user` · `.msg-ai` · `.body` | Load-bearing across six modules, plus the censor, the arrow-up recall, and the text-to-speech injector. |
| `.thinking-section` · `data-thinking-id` | The delegated toggle, the streaming renderer's skip rule, Escape-to-close, and the content-hash persistence observer. |
| `.agent-thread-*` | Six drifted markup copies plus the interrupt cleanup paths. **Unify (P4-01) before renaming anything.** |
| `.ask-user-card` · `.ask-user-*` | **Two CI tests assert literal source strings** from this file, including exact class assignments and event-dispatch lines. See `DEFERRED.md` D-01. |
| `.minimized-dock-chip` · `data-modal-id` | The modal auto-wire map, swipe-dismiss and tab-down all key off these. |
| `data-ui-key` values | Persisted preference keys for 30 visibility toggles. A rename silently resets what users have hidden. |
| `#search-overlay` · `#search-input` · `#search-results` | Must stay in the DOM even after the command palette supersedes them — five call sites including the rail button and `/find`. |
| `ADV_KEYS` + `computeAdvancedDefaults()` | Any new theme token must extend **both in lockstep**, or all 16 themes break. |
| `.skill-md-editor` + its guard shape | A CI test greps for the literal guard in two functions. |
| Frontmatter keys + the four `##` headings | The on-disk skill contract. `## Steps` must keep parsing as `procedure`. |
| A skill's `name` | It is the identity, the filename **and** the API id. Two independent guards enforce never-rename-on-save, pinned by a test. |
| `mcp__{server_id}__{tool_name}` | Persisted in a server's disabled-tool list and in scheduled-task output targets. |
| Built-in MCP server ids | `image_gen` · `memory` · `rag` · `email` · `builtin_browser`. Hardcoded in four places. |
| The 16 built-in email tool names | Four gates derive from one registry, cross-checked by a test. |
| `call_tool` envelope keys | `stdout` · `stderr` · `exit_code` · `images` · `untrusted_content`. |
| The MCP OAuth redirect URI | Registered with external authorization servers via dynamic client registration — changing it invalidates every existing registration. |
| The webhook URL shape | `/api/tasks/{task_id}/webhook/{token}`. Pinned by an auth-exempt regex **and** by a test asserting the literal source string. |
| Task/run enum values | `task_type`, `trigger_type`, `schedule`, task `status`, run `status`, `output_target` prefixes — all stored in rows. |
| All 18 built-in action keys | Stored in rows and joined against six separate maps. |
| Every `legacy_names` / `old_cron_expressions` entry | The sole migration join key for pre-rename rows. Renaming one orphans a user's task into "user-created" and it stops being revertable. |
| The 7 event names | Stored in `trigger_event`; changing one silently disables every task using it. |
| `ADMIN_ONLY_TASK_ACTIONS` | Asserted by a test; gates enforced at five sites. |
| The approval cache-buster string | **Must be bumped across all six approval-path modules together**, or a browser pairs new code with a cached interceptor and the approval click lands on the New-chat branch. |
| `static/lib/**` | `.gitattributes` requires byte-identical bundles so upstream licence banners survive. Never reformat. |

### The theme system — protected by decision, not by fragility

`DECISIONS.md` D-2026-08-26-03 keeps Odysseus's themes and their animated backgrounds.
These names carry that decision. Restyle around them; do not rename or remove them.

**The theme editor is protected too, and by the owner's own words (2026-08-30):**

> *"One genuinely awesome thing I have found is the theme creator that's built into the
> platform. This is genuinely awesome, and we should ensure it stays functional. It is also
> the location where you enable the glass panels too. Can even export and import different
> themes too."*

So the editor is not merely styling that happens to work — it is a feature the owner uses and
values, and **anything that changes what a theme stores has to keep it whole.** Concretely:

```
ADV_KEYS                  the advanced-colour picker's schema — static/js/theme.js
computeAdvancedDefaults   its default provider; the two move in lockstep or 16 themes break
applyFrostedGlass         the frosted-glass toggle · body.theme-frosted
theme-frosted-toggle      the checkbox that drives it
theme-import-area · theme-import-go · theme-export  the export/import controls
```

**A theme's stored options are one list in four places** — `saveCustomTheme`, `save`, the
exporter and the importer. `tests/test_theme_export_round_trip_js.py` holds them equal, using
the owner's own exported theme as its fixture. That test exists because they had already
drifted: the exporter wrote four of seven, so **the frosted-glass state did not survive an
export/import round trip**, and a tuned background pattern came back at its defaults. Nothing
failed loudly — the file imported cleanly and simply produced a different theme.

Add an option to what a theme stores and you add it to all four, or the test fails.

```
THEMES                    the 16 built-in entries — static/js/theme.js:11
THEME_DEFAULT_PATTERN     which background each theme gets. This map IS the feature.
_BG_CLASSES               the 8 bg-pattern-* class names
_CANVAS_PATTERNS          pattern → init-function registry

bg-pattern-dots           the CSS-only one — style.css:209
bg-pattern-rain           bg-pattern-synapse        bg-pattern-constellations
bg-pattern-perlin-flow    bg-pattern-petals         bg-pattern-sparkles
bg-pattern-embers

rain-canvas               synapse-canvas            constellations-canvas
perlin-flow-canvas        petals-canvas             sparkles-canvas
embers-canvas

--bg-effect-color   --bg-effect-intensity   --bg-effect-size
odysseus-theme / odysseus-custom-themes     (renamed to pantheon-* by P0-04; the KEYS
                                             stay one-to-one, the values are unchanged)
```

**`--accent` must never be defined in `:root`.** **535** of the **813** `var(--accent…)` sites
in `style.css` are `var(--accent, var(--red))` and resolve to the active theme's `red`. A
`:root` definition beats the fallback and collapses all 16 themes onto one colour. Set it
per theme inside **`applyColors()`** instead — see `P1-01`, which was rewritten for exactly
this reason after being written the wrong way round. *(Re-measured 2026-08-28; it was 508, then 521, now 535 — `static/style.css` grows, so derive it rather than quoting this line. `applyTheme()` does not exist. `--red` is set at
three sites — `theme.js:263`, `index.html:29`, `login.html:54` — and all three need the new
line, or the login page never gets an accent and every cold load flashes.)*

**A reduced-motion guard is not a removal.** `P10-05` adds one over the seven canvas
animators. It respects an operating-system setting. The animation stays.

### The app-API blocklist — two entries with no test behind them

`_APP_API_BLOCKLIST_METHOD_PATH` in `src/tools/system.py` refuses a set of `(method, path)`
pairs to the generic `app_api` tool. Every entry carries its reason in a comment beside it or
in the group above it, and that documentation predates the fork — `P2-26` closed on 2026-08-31
having verified the two tuples **byte-identical to the fork baseline**, 2,375 characters, no
drift either way.

**Two of those entries are protected here because nothing else protects them:**

    ("POST",   "/api/cookbook/state")
    ("DELETE", "/api/cookbook/state")

They exist because the agent was **observed** wiping `cookbook_state.json` — presets *and*
tasks — by POSTing `{"tasks": []}`, which overwrote the whole file. **No test pins either
one.** That combination — real incident behind them, no test in front of them — makes them
the pair most likely to be removed by someone tidying a list they believe is over-long, and
the least likely to be caught when it happens.

Do not remove them. Do not narrow them to `POST`. If the list is ever refactored, these two
survive the refactor, and the incident comment survives with them. Widening the tool's reach
here is not a feature; it is the same data loss a second time. `P2-26` is closed, and a closed
row cannot keep saying this, which is why it says it here instead.

### Renames that ARE happening (P0) — and what they cost

These are deliberate, one-time, and documented as a break. Everything else above stays.

`ODYSSEUS_*` env prefix (99 names) · 113 browser-storage keys · 6 vector collections
(**orphans all memories, RAG and tool index — migrate, don't rename**) · session cookie ·
6 outbound headers · 4 user-agents · data dir · systemd unit · compose service and
container user · SearXNG sentinel · macOS bundle id (**OS treats it as a different app**) ·
service-worker cache · PWA manifest · 19 CLI scripts (**user crontabs break**) ·
2 Swift executables · 3 DOM events · 2 integration plugin ids.

---

## PART 2 — Security controls that never lift

The un-nerf pass (P2) is safe **because** these stay. The test is whether anything the
restriction blocks is ever *executed or rendered*. For uploads, nothing is — which is
why that block goes. For everything below, something is.

| Control | Property it holds |
|---|---|
| Email inline-image `image/` check | **The single most load-bearing type check in the repo.** The only route serving sender-controlled bytes with an inline disposition **and** a sender-chosen content type. Without it, a crafted email part with `Content-Type: text/html` becomes a same-origin HTML page. |
| `Content-Disposition: attachment` on uploads | **The reason the extension blocklist is unnecessary.** Never pass `inline` here. |
| `UPLOAD_RESPONSE_HEADERS` nosniff + the global nosniff and CSP | MIME sniffing, XSS. |
| Gallery `IMAGE_EXTS` excluding `svg`, and the chat→gallery extension coercion | Stored XSS on the **inline-served** generated-image path. Do not add `svg`. |
| `GENERATED_IMAGE_RE` + the fixed MIME map | Path traversal and inline-serve MIME control on a public-ish route. |
| MCP command / arg / env validation | **RCE via prompt injection.** Closes a reported issue; pinned by 10 tests. Do not weaken to make a Creator convenient. |
| `_resolve_tool_path` + sensitive-basename list | Credential exfiltration (`.env`, `.ssh`, `id_rsa`) and `authorized_keys` write. |
| `_resolve_mcp_oauth_path` jail | Arbitrary file write as the app user. |
| `_validate_serve_cmd` metachar gate | Command injection into a tmux-executed wrapper. |
| The five SSRF validators + pinned-IP transports | Cloud-metadata and internal-network SSRF. |
| The nh3 report sanitiser | XSS under the relaxed CSP on report pages. |
| The two email HTML sanitisers | DOM XSS from received mail; live script shipped to recipients. |
| `OutboundHostLimiter` on every third-party call | **The user's access to services they depend on.** See below — this one is not a security control and is here anyway. |

### The outbound limiter has no off switch, and must not grow one

`src/rate_limiter.OutboundHostLimiter` is not a security control. It is in this file
because it protects something a security control cannot give back: **the user's standing
with a third party.** A ban is not served by Pantheon and cannot be lifted by Pantheon.

It exists because on 2026-08-31 the owner was soft-banned by GitHub by his own product,
importing a skill. His words were the whole brief:

> *"We need to ensure ALL api communications and Polling is being rate limited to not be
> banned, or trigger abuse detections."*

**What never lifts:**

- **No global bypass.** Not a `PANTHEON_DISABLE_RATE_LIMIT`, not a `paced=False`, not a
  debug flag. Someone will want one, because pacing makes an import take eleven seconds
  instead of two, and eleven seconds is the correct price. A bypass exists to be left on.
- **The floors do not go to zero.** `_AUTHENTICATED_FLOOR` is `0.2s` and a token does not
  remove it: a token raises your *quota*, and abuse detection is a separate system that
  does not care what your quota is. This distinction is the one that caused the ban.
- **`observe()` is called on every response, not only failures.** A `200` is how a host
  tells us a cooldown is over. Skipping it on the success path leaves cooldowns latched.
- **A plain `403` is never treated as a rate limit**, and a `403` naming one always is.
  Confusing either direction is a bug with a test: one silences a host for an hour over a
  private repository, the other walks straight back into the ban.
- **The limiter is process-wide and keyed by host.** Not per feature. Two features each
  staying under a limit will jointly exceed it — the skill importer and the cookbook's
  GitHub calls already could.

**And the rule that produced all of it:** *a limit is a conversation.* The server says when
to come back. Read `Retry-After`, read `X-RateLimit-Reset`, and when a server says stop,
stop — the only way to stay banned is to keep asking while it is telling you.
| The emoji SVG guards | XSS via CDN-fetched SVG served same-origin. |
| Signature PNG magic + size and dimension caps | Non-PNG stamped into PDFs and stored. |
| The post-external blocked-effect gate | Prompt injection → privileged action. |
| The untrusted-context wrapper + guard-marker escaping | Prompt injection. |
| `WEB_FETCH_HARD_MAX_BYTES` | Resource exhaustion via a model-chosen byte count. |
| Auth rate limiters | Credential stuffing. |
| `require_admin` | Privilege escalation. |
| Host-Docker flag off · localhost bypass off | Host root-equivalence; auth bypass. |
| Outbound-email confirmation on by default | Prompt injection → real sent mail. |
| The plan-mode read-only allowlist (25 tools) | Fail-safe by construction — a newly added tool is blocked by default. Shell is excluded deliberately, with a written rationale. |
| The approval store's seal, TTL, single-use consumption and owner binding | Dismissing a card retires it but preserves the taint, so it cannot launder an action. |

### Widen only with the stated control kept

- **Skill-bundle suffixes** — keep the relative-path safety check and the byte/count caps.
- **The skill importer's host allowlist** — the SSRF property is held by the outbound-URL
  check and the per-hop IP-pinned transport, *not* by the host list. Widening the hosts is
  a supply-chain decision; removing the transport is a vulnerability.
- **`PANTHEON_MCP_ALLOWED_COMMANDS`** — a curated default is fine. *(Named `ODYSSEUS_MCP_ALLOWED_COMMANDS` here until 2026-08-28. The real variable is read at `src/agent_tools/admin_tools.py:140` and pinned by four assertions in `tests/test_manage_mcp_command_allowlist.py`. A protection list that names the wrong identifier protects nothing — and this one is the RCE control.)* The denied-command,
  denied-flag and dangerous-env lists are the RCE fix and do not move.
- **The serve-command allowlist** — keep the metachar rejection.
- **The system-package allowlist** — it is the only thing shaping argv into a package manager.
- **Upload byte limits** — resolution order is **role profile → instance setting → env →
  built-in default** (`P12-01`). The environment variable is the *override*, not the place a new
  limit goes: the owner asked for these to be controllable from admin, intelligently. *(This line
  said "prefer the env overrides" until 2026-08-28, which is the opposite, in the file every
  agent reads before touching a limit.)* Above ~100 MB you need
  streaming-to-disk, because the reader buffers the whole payload in memory.
  **Three tests pin the current defaults exactly.**
