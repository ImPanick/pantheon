#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Pantheon — repository setup
#
# Detaches the fork from upstream, wires the new private remote, and lays down
# the P0 scaffolding. Run this BEFORE pantheon-init.sh.
#
# Requires: gh (authenticated) — https://cli.github.com
#
#   ./scripts/pantheon-repo-setup.sh --dry-run
#   ./scripts/pantheon-repo-setup.sh --apply

set -euo pipefail

MODE="dry-run"
[[ "${1:-}" == "--apply" ]] && MODE="apply"

REPO_NAME="pantheon"
REPO_DESC="A self-hosted AI agent workspace. Elevated fork of Odysseus."
BRANCH="main"

say() { printf '\033[36m%s\033[0m\n' "$*"; }
warn(){ printf '\033[33m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }
run() { if [[ "$MODE" == "apply" ]]; then eval "$@"; else printf '    \033[90m$ %s\033[0m\n' "$*"; fi; }

[[ -f app.py && -d static ]] || die "Run this from the repository root."
command -v git >/dev/null || die "git not found."
command -v gh  >/dev/null || die "gh not found. Install from https://cli.github.com, then 'gh auth login'."
gh auth status >/dev/null 2>&1 || die "gh is not authenticated. Run 'gh auth login'."

GH_USER=$(gh api user --jq .login)
say "=== Pantheon repo setup · mode: $MODE · account: $GH_USER ==="

# ── 0. safety ────────────────────────────────────────────────────────────────
say ""
say "[0/6] Preflight"
say "    Current remotes:"
git remote -v | sed 's/^/      /' || true
CUR_BRANCH=$(git rev-parse --abbrev-ref HEAD)
say "    Current branch: $CUR_BRANCH"
say "    HEAD: $(git rev-parse --short HEAD)"

# Tracked modifications are a hard stop — step 6 does `git add -A` and would
# sweep unrelated work into the initial commit. Untracked files are expected
# here (that is the scaffolding), so they are listed for review, not refused.
if [[ -n "$(git diff --name-only HEAD)" ]]; then
  warn "    Tracked files are modified:"
  git diff --name-only HEAD | sed 's/^/      M /'
  [[ "$MODE" == "apply" ]] && die "Commit or stash tracked changes first — step 6 commits everything."
fi
UNTRACKED=$(git ls-files --others --exclude-standard)
if [[ -n "$UNTRACKED" ]]; then
  say "    Untracked files that WILL land in the initial commit:"
  printf '%s\n' "$UNTRACKED" | sed 's/^/      + /'
  say "    ($(printf '%s\n' "$UNTRACKED" | grep -c .) files — anything that should not be committed goes in .gitignore now.)"
fi

# ── 1. secret scan — SECURITY.md's own fork checklist ────────────────────────
say ""
say "[1/6] Secret scan (upstream's own pre-fork checklist)"
say "    Tracked files that should never be committed:"
git check-ignore -v .env data/auth.json data/app.db logs/compound.log 2>/dev/null | sed 's/^/      ignored: /' || \
  warn "      One or more are NOT ignored — check .gitignore before pushing."
say "    Scanning tracked content for key-shaped strings:"
# Each pattern is anchored so it cannot fire on ordinary identifiers. The
# unanchored "sk-" of the first draft matched every "ta[sk-]form-..." class name
# in the codebase, and a bare "xox[baprs]-" matched Slack's own setup help text.
SECRET_RE='(\bsk-(proj-)?[A-Za-z0-9]{24,}'
SECRET_RE+='|\bxox[baprsoe]-[0-9]{6,}-[0-9A-Za-z-]{10,}'
SECRET_RE+='|\bAIza[0-9A-Za-z_-]{33}'
SECRET_RE+='|\bgh[pousr]_[A-Za-z0-9]{36}'
SECRET_RE+='|\bgithub_pat_[A-Za-z0-9_]{60,}'
SECRET_RE+='|\bAKIA[0-9A-Z]{16}'
SECRET_RE+='|\bsk-ant-[A-Za-z0-9_-]{24,}'
SECRET_RE+='|-----BEGIN [A-Z ]*PRIVATE KEY-----'
SECRET_RE+='|\b[Aa]uthorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]{30,})'
if git grep -n -I -E "$SECRET_RE" \
     -- . ':!static/lib/**' ':!package-lock.json' ':!scripts/pantheon-repo-setup.sh' 2>/dev/null; then
  die "Potential secrets found above. Resolve before continuing."
else
  say "      clean"
fi

# ── 2. preserve upstream as a reference remote ───────────────────────────────
say ""
say "[2/6] Remotes"
say "    Keeping upstream reachable for cherry-picking fixes, renaming origin."
if git remote | grep -qx upstream; then
  say "    'upstream' already present."
else
  UP=$(git remote get-url origin 2>/dev/null || echo "https://github.com/pewdiepie-archdaemon/odysseus.git")
  run "git remote rename origin upstream" || true
  say "    upstream → $UP"
fi

# ── 3. create the private repo ───────────────────────────────────────────────
say ""
say "[3/6] Create $GH_USER/$REPO_NAME — PRIVATE"
if gh repo view "$GH_USER/$REPO_NAME" >/dev/null 2>&1; then
  warn "    Already exists. Skipping creation."
else
  run "gh repo create '$GH_USER/$REPO_NAME' --private --description '$REPO_DESC' --disable-wiki"
fi
run "git remote remove origin 2>/dev/null || true"
run "git remote add origin \"https://github.com/$GH_USER/$REPO_NAME.git\""

# ── 4. branch ────────────────────────────────────────────────────────────────
say ""
say "[4/6] Branch → $BRANCH"
if [[ "$CUR_BRANCH" != "$BRANCH" ]]; then
  run "git branch -m '$CUR_BRANCH' '$BRANCH'"
  say "    Renamed $CUR_BRANCH → $BRANCH (keeps all history, including your custom commits)"
fi

# ── 5. scaffolding ───────────────────────────────────────────────────────────
say ""
say "[5/6] Scaffolding"
for f in NOTICE CHANGELOG.md CREDITS.md; do
  if [[ -f "$f" ]]; then warn "    $f exists — not overwriting."; else say "    + $f"; fi
done
say "    + .pantheon/  (ROADMAP, AGENTS, FORBIDDEN, DEFERRED, handoff/, design/)"
say "    ~ .gitignore  (append the Pantheon block)"
say "    (Present above means already copied in from the init package.)"

# ── 6. first commit + push ───────────────────────────────────────────────────
say ""
say "[6/6] First commit"
run "git add -A"
run "git commit -m 'chore: initialise Pantheon

Fork of Odysseus (pewdiepie-archdaemon/odysseus) at b4d1293.

Adds the AGPL-3.0 modification notice, credits, changelog, and the
.pantheon/ programme directory: roadmap, working agreement, do-not-touch
list, deferred decisions and per-area handoff notes.

Upstream remains available as the '\''upstream'\'' remote for cherry-picks.
No source changes in this commit.'"
run "git push -u origin '$BRANCH'"

say ""
if [[ "$MODE" == "apply" ]]; then
  say "=== done ==="
  say ""
  say "  Repo:   https://github.com/$GH_USER/$REPO_NAME  (private)"
  say "  Next:   ./scripts/pantheon-init.sh --dry-run"
  say ""
  warn "  Do NOT flip to public until P0-14 … P0-27 are ticked."
  warn "  The licence notices and credits gaps must close first."
else
  say "  Dry run. Nothing was created, renamed, committed or pushed."
  say "  Re-run with --apply when the plan above looks right."
fi
