#!/usr/bin/env bash
# Fast-forward this clone from a git bundle, then say what to do next.
#
# `B1409`. This script is **committed** for one reason: for several waves it
# was delivered into the clone as a loose file at a path that changed each
# time, so the next session's instructions pointed at the previous session's
# path and the whole thing failed with
#
#     /usr/bin/bash: .pantheon-transfer/apply-release.sh: No such file or directory
#
# A procedure that lives in a chat message is a procedure nobody can find
# twice (`Law 15`). This path does not move.
#
# Usage, from the root of the clone:
#
#     & 'C:\Program Files\Git\bin\bash.exe' .pantheon/apply-release.sh [bundle]
#
# `bundle` defaults to `pantheon.bundle` in the current directory. Nothing is
# touched unless the bundle verifies and the result is a fast-forward.
#
# See `docs/delivery.md` for why a bundle exists at all and what follows a push.
set -euo pipefail

BUNDLE="${1:-pantheon.bundle}"
BRANCH="${2:-main}"

die() { printf '%s\n' "$*" >&2; exit 1; }

[ -d .git ] || die "run this from the root of your clone — there is no .git here.
  cd to the repository and try again."

if [ ! -f "$BUNDLE" ]; then
  die "no bundle at '$BUNDLE'.
  Pass its path as the first argument, e.g.
      bash .pantheon/apply-release.sh ~/Downloads/pantheon.bundle
  If you were not given a bundle, you may not need one: a session with a live
  bridge to this machine fast-forwards the clone directly, and all that is
  left is 'git push origin main'. Check 'git log --oneline -1' first."
fi

echo "== verifying the bundle =="
git bundle verify "$BUNDLE"

# The bundle's own ref name, read rather than assumed. An earlier version of
# this script hard-coded `push-tip` while the bundles carried
# `refs/heads/main`, and it would have reported "adds nothing new" over
# sixteen real commits.
REF="$(git bundle list-heads "$BUNDLE" | awk 'NR==1{print $2}')"
TIP="$(git bundle list-heads "$BUNDLE" | awk 'NR==1{print $1}')"
[ -n "$REF" ] || die "that bundle carries no refs."
echo "   bundle ref: $REF  ($TIP)"

# TRACKED changes only. A fast-forward cannot silently eat an untracked file —
# git refuses the checkout if one would be overwritten — so untracked paths are
# worth mentioning and not worth refusing over. Two earlier versions of this
# guard used a plain `git status --porcelain` and blocked on their own bundle,
# on the script itself, and then on a leftover transfer folder: three refusals
# in a row, none of them about anything at risk.
TRACKED="$(git status --porcelain --untracked-files=no)"
if [ -n "$TRACKED" ]; then
  printf '\nyou have uncommitted changes to tracked files — commit or stash first:\n' >&2
  printf '%s\n' "$TRACKED" >&2
  exit 1
fi

UNTRACKED="$(git ls-files --others --exclude-standard | grep -v -e '\.bundle$' || true)"
if [ -n "$UNTRACKED" ]; then
  printf '\nnote: untracked files are present and are left exactly as they are:\n'
  printf '  %s\n' $UNTRACKED
fi

echo
echo "== fetching =="
git fetch "$BUNDLE" "$REF:refs/remotes/bundle/$BRANCH" --force
BEFORE="$(git rev-parse HEAD)"

git checkout "$BRANCH"
echo
echo "== fast-forwarding $BRANCH =="
if ! git merge --ff-only "refs/remotes/bundle/$BRANCH"; then
  printf '\nnot a fast-forward: your %s has commits the bundle does not.\n' "$BRANCH" >&2
  printf 'Nothing has been changed. These are yours alone:\n' >&2
  git --no-pager log --oneline "refs/remotes/bundle/$BRANCH..$BRANCH" >&2
  exit 1
fi

AFTER="$(git rev-parse HEAD)"
echo
if [ "$BEFORE" = "$AFTER" ]; then
  echo "already up to date at ${AFTER:0:8}"
else
  echo "$BRANCH: ${BEFORE:0:8} -> ${AFTER:0:8}"
  git --no-pager log --oneline "$BEFORE..$AFTER"
fi

# The bundle has done its job; leaving it in the clone is how the next run
# finds a stale one and applies nothing.
rm -f "$BUNDLE"
git update-ref -d "refs/remotes/bundle/$BRANCH" 2>/dev/null || true

cat <<'NEXT'

== next ==
  1. git push origin main
  2. watch the build:  https://github.com/ImPanick/pantheon/actions
  3. on the server, once docker-publish.yml is green:
       docker compose pull && docker compose up -d
     (`pull_policy: always` only fires at container CREATION, so the explicit
      pull is what actually moves the image.)
NEXT
