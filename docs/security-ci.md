# Security CI guide

This project runs a set of automated security checks on pull requests and
selected branch pushes. This page explains what each one does, whether it can
block a merge, and the few one-time settings you should turn on to get the full
benefit.

## What runs, and why

Most checks live in files under `.github/workflows/`. CodeQL uses the
checked-in advanced configuration in `.github/workflows/codeql.yml`. They run
automatically; you do not start them.

| Check | What it protects against | Blocks a merge? |
|---|---|---|
| **Secret scan** (gitleaks) | An API key, token, or password being committed by mistake or on purpose | Yes |
| **Workflow security** (actionlint + zizmor) | A broken or insecure automation file that could leak the repo's access token | Yes |
| **Dependency review** | A pull request that adds a software library with a known security hole | Yes |
| **pip-audit** | Known security holes in the Python libraries already used | Yes |
| **Container scan: hadolint** | Mistakes and insecure patterns in the `Dockerfile` | Yes |
| **Container scan: Trivy** | Known security holes in the Docker image | Findings no; a failed build or a failed upload yes (`B435`) |
| **CodeQL** | Real bugs in the app's own code: injection, auth mistakes, path traversal | No (advisory) — and it now runs on pull requests at all (`B433`) |

"Blocks a merge" means a red X appears on the pull request and, once you enable
the setting below, the **Merge** button is disabled until it is fixed.

"Advisory" means it reports problems into the repository's **Security** tab so
you can review them on your own schedule, but it never stops a merge. These are
advisory on purpose: they often flag long-standing issues in other people's
libraries, not something a given pull request introduced.

**pip-audit was advisory until 2026-09-16 (`B322`) and now blocks.** The
reasoning for leaving it advisory was the paragraph above: it can flag a
pre-existing issue that the pull request in front of you did not introduce. That
is true, and it is an argument for a way to say "we looked at this one" — not
for a check that never fails, which is a check nobody reads. So there is now a
register of accepted risks, `.pantheon/dependency-advisories.toml`. A finding
with an entry there does not fail the build, and the audit prints that entry's
full reasoning — what the bug is, why this code cannot reach it, what upstream
offers, when somebody looks again — right next to whatever did fail. A finding
with no entry fails. Adding an entry is a reviewable diff with a `DECISIONS.md`
entry behind it, and `.pantheon/check-pins.py` refuses one that does not explain
itself or whose review date has passed.

Trivy's **findings** stay advisory: it scans the whole image, including
operating-system packages this project does not choose, and a fixless CVE in one
of those must not stop a merge. It runs with `ignore-unfixed`, and what that flag
was silently dropping is now written down in `D-2026-09-16-01`.

**Whether it looked is not advisory** (`B435`, 2026-09-17). `continue-on-error`
used to sit on the whole Trivy job, both of them — so a Dockerfile that would
not build, or a SARIF upload that never reached the Security tab this page sends
you to, reported a green tick. A green tick that means *I did not look* is worse
than a red one, and it was worse still here: Trivy is the job that was meant to
be the one that caught `basicsr`. The flag now sits on the one step whose
findings are advisory, and its name says so. The rule generalises, and
`.pantheon/check-ci-contract.py` enforces it: **a `continue-on-error` job or
step must say `advisory` or `report-only` in its name**, because the name is all
a reader of the Checks tab gets.

## How to tell whether CI is actually passing

**On 2026-09-17 nobody could, and nobody had.** Of the last forty workflow runs
on this repository, 22 failed, 8 succeeded, 9 were skipped and 1 was cancelled —
and every one of the eight successes is a Dependabot update run or a
`Container scan (Trivy)` job that skipped its work. No `CI`, `CodeQL`,
`Secret scan`, `Workflow security` or `Dependency review` run has ever
succeeded. Every failing job reports an empty `runner_name`, an empty `steps`
array and a three-to-six second duration: **they never got a runner.** That is
the signature of exhausted Actions minutes or a spending limit on a private
repository owned by a user account, and no change to a workflow file makes a
runner appear. Actions itself is enabled
(`{"enabled":true,"allowed_actions":"all"}`). Making the repository public makes
Actions free and unlimited for it, which is the fix and is the owner's call.

The part that was ours is that **five waves of work shipped that day, each
reporting "gate green on 22 checkers", and every one of those was a local
`.pantheon/release-gate.py --fast` run.** The pipeline was red for all five and
nothing in this repository observed it. So:

### The badges in README.md

The five badges under the title are live. Each is
`github.com/ImPanick/pantheon/actions/workflows/<file>/badge.svg?branch=main`
and each links to that workflow's runs. `.pantheon/check-ci-contract.py` rule 2
fails if a merge-blocking workflow has no badge, if a badge names a workflow or
branch that does not exist, or if it points at another repository.

**`?branch=main` is not decoration.** A badge with no branch reports the newest
run on *any* ref — so a green Dependabot branch paints it green while `main` is
red, which is precisely the shape of the eight successes above.

What the badges do and do not tell you:

| State | What a logged-out reader sees | What it means |
|---|---|---|
| Private repo (today) | A blank or broken image | **Nothing.** `badge.svg` needs read access; a stranger learns nothing, and neither does a stranger's scraper |
| Private repo, signed in with access | The real status | The latest run on `main` for that workflow |
| Public repo | The real status | The same, to everybody |
| Any state, workflow never ran | `no status` | **Not "passing".** No run has happened — which is exactly today's situation and the one most easily misread |

So the badge is necessary and **not sufficient**, for three reasons: it is
invisible while the repo is private, "no status" reads as absence rather than
failure, and a badge is green whenever the *workflow* concluded green — which a
job that fails open does. The first two are facts to know; the third is what the
checker below is for.

### The checker

`.pantheon/check-ci-contract.py` runs in `ci.yml` and therefore in
`release-gate.py`, which reads its checker list out of that file. Seven rules:

1. every check name this page tells you to require matches a job that exists;
2. every merge-blocking workflow has a branch-pinned badge in `README.md`;
3. no workflow trigger names a branch this repository does not have (`B433`:
   `ci.yml`, `codeql.yml` and `docker-publish.yml` all said `dev`, which has
   never existed — and in `codeql.yml` the filter was on pull requests, so
   **CodeQL had never analysed a single pull request**);
4. a `continue-on-error` job or step says so in its name (`B435`);
5. the local gate reads its interpreter, node version, suite argv and advisory
   argv out of `ci.yml` rather than copying them (`B431`);
6. neither syntax job keeps a second list of which files are ours (`B436`);
7. a skip that claims "this change is only documentation" can prove it
   (`B434`).

### What the local gate is and is not

`.pantheon/release-gate.py` mirrors `ci.yml` and **nothing else**. A push also
sets off the secret scan, the workflow-security audit, the dependency review and
the container scan — four gates this page calls merge-blocking — and the gate
runs none of them. `--fast` additionally skips the suite. Every run now ends
with a block naming exactly what it did not cover, including the suite, the
workflows it does not run, and any place the developer's interpreter or node
differs from the pinned ones. A green gate is evidence about the checkers it
ran, on the machine it ran on. It is not a green pipeline, and only the badges
and the Actions tab are.

## Where results appear

- **Checks tab of a pull request**: the pass/fail of each check. A green tick is
  good; a red X needs attention.
- **Security tab of the repository**: detailed findings from the advisory
  scanners (Trivy and CodeQL). This is your dashboard.

## If a check fails

- **Secret scan failed**: a real credential may have been committed. Treat it as
  leaked: rotate (regenerate) that key or token immediately, then remove it from
  the file. Do not just delete the commit; assume it was seen.
- **Dependency review failed**: the pull request adds a library with a known
  vulnerability. Ask the contributor to use a patched version, or decline the
  change.
- **hadolint / workflow security failed**: the contributor changed the
  `Dockerfile` or an automation file in a way the linter rejects. Ask them to
  address the message shown in the failed check.

## One-time settings to turn on

These three settings unlock the full value. You only do them once. Do the third
one **before** the repository is public, not after — it is the only one where
being late has a cost you cannot take back.

### 1. Require the blocking checks before merging

This makes the **Merge** button refuse to work until the gating checks pass.

1. Go to the repository on GitHub.
2. Click **Settings** (top right of the repo).
3. In the left sidebar, click **Branches**.
4. Under **Branch protection rules**, click **Add branch ruleset** (or **Add
   rule**), and set the branch name pattern to `main` (the only branch here —
   corrected 2026-08-30, this said `dev`, which does not exist, so anyone who
   followed it protected nothing).
5. Enable **Require status checks to pass before merging**.
6. In the search box that appears, add these checks by name:
   - `Python syntax (compileall)`
   - `JS syntax (node --check)`
   - `gitleaks`
   - `actionlint`
   - `zizmor (Actions SAST)`
   - `hadolint (Dockerfile lint)`
   - `dependency-review (PR gate)`
   - `pip-audit (blocking)`

   The first two come from the correctness CI (`ci.yml`); the rest are this
   security suite.

   > **`JS syntax (node --check)` was a required check that checked nothing on
   > the largest module in the app, from the fork baseline until 2026-09-14
   > (`B10`).** The step ran `node --check <path>`, and node resolves module
   > type from the nearest `package.json`; the root one declares no `"type"`,
   > so `static/app.js` — 4,641 lines — parsed as CommonJS, and node's
   > module-syntax detection then retried the failed parse as ESM and did not
   > re-check. Any file containing an `import` passed unconditionally,
   > including one whose entire body is `this is not javascript at all !!! ( [
   > {`. Measured on node 20 and 22. A required status check is the strongest
   > assurance this repo offers, which is what made this the worst place for
   > it to be hollow. The step now calls `.pantheon/release-gate.py`'s own
   > `_node_check`, which pipes each file in with `--input-type=module`, and
   > covers 187 files rather than 173.

   Add `pip-audit (blocking)` to the list above as well, once it has run on one
   pull request (`B322`). Leave pytest, Trivy, and CodeQL unchecked so they stay
   advisory.
7. Also enable **Require a pull request before merging** and **Require review
   from Code Owners** (this uses the `.github/CODEOWNERS` file so every change
   needs your sign-off).
8. Click **Create** / **Save changes**.

Note: a check name only appears in the list after it has run at least once, so
let the workflows run on one pull request first, then add them here.

### 2. Turn on the Security tab features

1. **Settings -> Code security** (or **Code security and analysis**).
2. Turn on **Dependency graph** (usually on by default for public repos) -- this
   powers Dependency review and Dependabot.
3. Turn on **Dependabot alerts** and **Dependabot security updates**.
4. Under **Code scanning**, keep **Default setup** disabled. CodeQL is
   configured by `.github/workflows/codeql.yml`; enabling default setup at the
   same time causes GitHub to reject uploads from the checked-in workflow.

### 3. Turn on private vulnerability reporting

Do this before the repository goes public.

1. **Settings -> Code security** (or **Code security and analysis**).
2. Turn on **Private vulnerability reporting**.

Three documents send security reporters to
`https://github.com/ImPanick/pantheon/security/advisories/new`: `SECURITY.md`,
`CODE_OF_CONDUCT.md` (which uses it for conduct reports, because it is the only
private channel this repository has), and `.github/ISSUE_TEMPLATE/config.yml`,
which puts it in the chooser a person sees *before* they reach "New issue".
With the setting off, that URL 404s and every one of those routes ends with a
reporter standing in front of a dead end holding a vulnerability — and the next
thing a reporter does when the private channel fails is file a public issue,
which for most bugs in this project's surface publishes the exploit. All three
documents say what to do if the page 404s, so the failure is handled rather
than silent, but a fallback is not the fix; this setting is.

`B357` could not verify it from the worktree: `api.github.com` is unreachable
from there and the repository was not public yet, so nobody has confirmed the
switch is on. It is checked off when the advisory URL shows the report form to
a logged-out visitor.

## Keeping it current

`.github/dependabot.yml` opens small weekly pull requests to update Python and
npm packages, the Docker base image, and the pinned automation actions
themselves. Review and merge those like any other pull request; they keep the
project patched without manual tracking.
