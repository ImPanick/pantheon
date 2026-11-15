# Where Pantheon came from

Pantheon is a fork of [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus), a self-hosted
AI workspace with about two thousand commits behind it. We installed it, used it for real work,
and liked it.

Odysseus goes by two names. We cloned `pewdiepie-archdaemon/odysseus`; its own code and docs point
at `odysseus-dev/odysseus`. Both are the same upstream project and we credit both — see
[`NOTICE`](../NOTICE).

The workstation's live desktop and the agent's live browser are
[KasmVNC](https://github.com/kasmtech/KasmVNC), open source from
[Kasm Technologies](https://kasmweb.com): it is why you can watch the agent's screen as it works and
take over the mouse and keyboard, instead of looking at screenshots. A VM workstation runs on
[QEMU](https://www.qemu.org/) with Linux's KVM. Both are credited in
[`CREDITS.md`](../CREDITS.md#kasmvnc--the-live-workstation).

Then we tried to change something small and ended up reading all 42,739 lines of the stylesheet.

`--accent` — the colour behind every highlight, hover state and drag handle — was referenced 813
times and defined nowhere. 206 style rules resolved to nothing. Nothing errored; the rules simply
never applied. Most of what we found after that was finished work that had never been connected: a
webhooks admin panel with no interface, a built-in skills editor behind `showBuiltin = false`, an
image upscaler with no button, a plan mode whose window never existed, and files the system did not
recognise reaching the model as the literal string `[Attached document file]`. Someone built the hard
part and moved on before the last step, which is a normal thing to happen to a project moving
quickly. We forked it to finish that last step — and then kept building.

## Switching it back on

<details>
<summary>The wiring count: why it read 78, then 120, then 40 — and the six areas it found</summary>

We wrote a script that counts element lookups with nothing behind them. It found **78**, across
six subsystems, which is the point of writing the script rather than writing the list. What
follows is that original finding, kept because it is the honest picture of what a fork inherits.

**Run it today and it says 0** (2026-10-25, `B1444`–`B1446`). It said 40 before that, 120 when this paragraph was written and 78 when the
original sweep was taken, and neither difference is a regression — it is the same script looking at
more than it used to, and then a triage driving down what it found. It has been widened three times since the 78 was taken, each time because
it turned out to be measuring less than it claimed: it read `static/js/` and never `static/app.js`,
the largest module in the product; it counted a lookup *described in a comment* as a lookup; and
it scored a lookup that indexes a map with a variable as clean, which on 2026-08-30 hid a live
defect where the agent reported opening a panel that had no button behind it. Closing that last
one moved the count from 9 to 124 with no product code changing. **So 78, 120 and 40 are three
different measurements and the differences between them mean nothing on their own.** The ratchet is
what means something: `check-wiring.py` runs in CI at a ceiling that may come down and may not go
up, so a *new* unreachable id shows up the day it is written. It has come down twice since — `P3-20`
triaged 124 to 40, and `P3-20`'s own test used to pin the literal `120` and went red the day the
ratchet did its job, which is `B520`.

**Nor were the 40 all defects.** Classified by how each id is reached rather than by
name, at least 87 of the 124 measured at the 2026-08-30 triage were guarded by construction — code that knows the markup
may be absent and returns early. That is a feature removed cleanly with its wiring left behind
on purpose, costing one null check. The triage is `P3-20`, and its finding was that driving the
number down is the wrong goal: it would mean deleting guarded code that costs nothing, which
this fork's first law forbids.

And a script that counts one shape of unreachability says nothing about the others: routes with
no caller, settings nothing reads, features whose only door is an undocumented keystroke. Those
are `check-unreachable.py` (`P3-15`) and the `H` rows.

| Area | Built, but unreachable |
|---|---|
| **Documents** | bulk archive, clone, delete, export; import; PDF AI-fill |
| **Image editor** | upscaler, edge feathering, resize and edge menus, background removal |
| **Model serving** | Ollama library browser, HuggingFace refresh, engine rebuild, hardware rescan |
| **Skills** | the skill-creation form |
| **Knowledge** | RAG document upload — the endpoint works and always has |
| **Email** | folder switching, attachment view, load-more |

Two of those six are wired: the image upscaler (`P2-22`) and RAG document upload (`P2-23`). The
rest are open rows in the tracker's `P2` section, which is where their current status lives.
Each is classified before anything changes — a stale reference to a renamed element gets fixed,
a real feature gets its markup and its event wiring, and code is deleted only when an audit has
proved it dead.

</details>

## How we work

**Add, never subtract.** Features survive. This is an elevation of Odysseus rather than a
rewrite.

Twenty laws are written down in [`.pantheon/AGENTS.md`](../.pantheon/AGENTS.md), each one added
after something went wrong, and nine of them cite the incident that produced them. Two examples:

> **Nothing ships half-wired.** A backend with no caller and a button with no handler get treated
> the same way. A script counts them and CI enforces the number.

> **If it needs a tutorial, it isn't finished.** A beta user with access to a more advanced
> version of a feature we're planning stopped using it because the learning curve was too steep
> and there were no docs.

Findings get checked by a second agent tasked with disproving them. In the first audit round the
reviewers overturned **twelve of twelve** contested findings, including on the phase's headline
task.
