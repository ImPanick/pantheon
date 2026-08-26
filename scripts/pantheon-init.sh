#!/usr/bin/env bash
# Pantheon — repository initialisation sweep
#
# Performs the mechanical half of P0 as one reviewable change:
#   P0-02 cosmetic surfaces   P0-03 env prefix        P0-04 storage keys
#   P0-06 session cookie      P0-07 headers + UA      P0-08 compose + user
#   P0-10 CLI script names    P0-11 packages + events
#
# Does NOT touch: LICENSE, licenses/, static/lib/, package-lock.json, .git/,
# static/fonts/, or any attribution file. Those are handled by hand in
# P0-14 … P0-27.
#
# Usage:
#   ./scripts/pantheon-init.sh --dry-run     # show what would change (DEFAULT)
#   ./scripts/pantheon-init.sh --apply       # actually change it
#
# Review the diff before committing. This touches ~2,900 occurrences.

set -euo pipefail

MODE="dry-run"
[[ "${1:-}" == "--apply" ]] && MODE="apply"
[[ "${1:-}" == "--dry-run" ]] && MODE="dry-run"

OLD_LC="odysseus";  NEW_LC="pantheon"
OLD_TC="Odysseus";  NEW_TC="Pantheon"
OLD_UC="ODYSSEUS";  NEW_UC="PANTHEON"
OLD_SHORT="ody";    NEW_SHORT="pan"

# The two upstream identities. The repo was cloned from pewdiepie-archdaemon;
# its own docs and code reference odysseus-dev. Both are real and they are not
# interchangeable.
UP_ORG="odysseus-dev"
UP_REPO="odysseus"
NEW_ORG="${PANTHEON_ORG:-ImPanick}"

# ── files that must never be swept ───────────────────────────────────────────
# Attribution files still say Odysseus, correctly. CHANGELOG and
# CYBERTOOTH_CHANGES record what this was forked FROM — sweeping them would
# rewrite history into a lie. The pantheon-* scripts contain the search strings
# themselves; sweeping them turns OLD_LC into "pantheon" and self-destructs.
EXCLUDES=(
  ':!.git/**'
  ':!LICENSE'
  ':!licenses/**'
  ':!static/lib/**'
  ':!package-lock.json'
  ':!NOTICE'
  ':!ACKNOWLEDGMENTS.md'
  ':!CREDITS.md'
  ':!CHANGELOG.md'
  ':!CYBERTOOTH_CHANGES.md'
  ':!.pantheon/**'
  ':!static/fonts/**'
  ':!scripts/pantheon-init.sh'
  ':!scripts/pantheon-repo-setup.sh'
)

say() { printf '\033[36m%s\033[0m\n' "$*"; }
warn(){ printf '\033[33m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[[ -f app.py && -d static ]] || die "Run this from the repository root."
command -v git >/dev/null || die "git not found."

if [[ -n "$(git diff --name-only HEAD)" ]]; then
  warn "Tracked files are modified. You want a clean diff to review."
  git diff --name-only HEAD | sed 's/^/    M /'
  [[ "$MODE" == "apply" ]] && die "Refusing to apply onto a dirty tree."
fi

say "=== Pantheon init · mode: $MODE · new org: $NEW_ORG ==="

# One git grep, not a per-file loop. On Windows each process spawn costs ~20ms,
# so scanning 1,900 tracked files two greps at a time took minutes. -I already
# skips binaries.
mapfile -t FILES < <(git grep -lIiE "${OLD_LC}|${UP_ORG}" -- "${EXCLUDES[@]}" 2>/dev/null || true)

# ── 1. protect links that must keep pointing at upstream ─────────────────────
# A link to a specific upstream issue, PR or discussion is provenance. Rewriting
# it points at a number that does not exist in the new repo.
say ""
say "[1/6] Protect upstream provenance links"
PROT_RE="${UP_ORG}/${UP_REPO}(/(issues|pull|discussions)/[0-9]+)"
say "    Links matching $UP_ORG/$UP_REPO/{issues,pull,discussions}/<n> stay upstream:"
git grep -InE "$PROT_RE" -- "${EXCLUDES[@]}" 2>/dev/null | sed 's/^/      /' || say "      none"

if [[ "$MODE" == "apply" ]]; then say "    (sentinelled in the single rewrite pass below)"; fi

# ── 2. org rename — every other reference to the upstream org is now ours ─────
say ""
say "[2/6] Org — $UP_ORG → $NEW_ORG"
say "    Covers clone URLs, issue-template links, package.json, the OpenRouter"
say "    HTTP-Referer header, the star-history chart, and CI test fixtures."
if [[ "$MODE" == "dry-run" ]]; then
  git grep -cI "$UP_ORG" -- "${EXCLUDES[@]}" 2>/dev/null | sed 's/^/      /' || say "      none"
else
  say "    (applied in the single rewrite pass below)"
fi

# ── 3. content sweep ─────────────────────────────────────────────────────────
say ""
say "[3/6] Content sweep — odysseus/Odysseus/ODYSSEUS → pantheon/Pantheon/PANTHEON"
say "    ${#FILES[@]} files contain a match."

if [[ "$MODE" == "dry-run" ]]; then
  say "    Top 20 by matching lines:"
  git grep -cIi "$OLD_LC" -- "${EXCLUDES[@]}" 2>/dev/null \
    | awk -F: '{printf "%6d  %s\n", $NF, substr($0,1,length($0)-length($NF)-1)}' \
    | sort -rn | head -20 || true
else
  # sed applies -e expressions in order, per line, so protect → org → rename →
  # restore all happen in ONE invocation per file. Four separate passes meant
  # four process spawns per file; on Windows that was the difference between
  # thirty seconds and several minutes.
  for f in "${FILES[@]}"; do
    [[ -n "$f" ]] || continue
    sed -i -E \
      -e "s#${PROT_RE}#@@UPORG@@/@@UPREPO@@\1#g" \
      -e "s/${UP_ORG}/${NEW_ORG}/g" \
      -e "s/${OLD_UC}/${NEW_UC}/g" \
      -e "s/${OLD_TC}/${NEW_TC}/g" \
      -e "s/${OLD_LC}/${NEW_LC}/g" \
      -e "s/@@UPORG@@/${UP_ORG}/g" \
      -e "s/@@UPREPO@@/${UP_REPO}/g" \
      "$f"
  done
  say "    Rewritten."
fi

# ── 4. restore the protected links ───────────────────────────────────────────
say ""
say "[4/6] Restore upstream provenance links"
if [[ "$MODE" == "apply" ]]; then
  # This script's own source contains the sentinel strings as literals, so it
  # must be excluded or it reports itself and aborts a sweep that worked.
  # `git grep` exits 1 when it finds nothing, and `set -o pipefail` propagates
  # that through the pipe — so the SUCCESS case was killing the script silently
  # under `set -e`, one line after the check it was meant to pass.
  LEFT=$(git grep -lE '@@UP(ORG|REPO)@@' -- . ':!scripts/pantheon-init.sh' 2>/dev/null | wc -l || true)
  [[ "$LEFT" -eq 0 ]] || die "    $LEFT files still hold a sentinel. Something went wrong — 'git checkout .' and stop."
  say "    clean — no sentinels remain"
else
  say "    (apply only)"
fi

# ── 5. short-prefix storage keys ─────────────────────────────────────────────
say ""
say "[5/6] Short-prefix storage keys — 'ody-' / 'ody.' → 'pan-' / 'pan.'"
mapfile -t SHORTFILES < <(git grep -lIE "['\"]${OLD_SHORT}[-.]" -- 'static/**' "${EXCLUDES[@]}" 2>/dev/null || true)
say "    ${#SHORTFILES[@]} files."
if [[ "$MODE" == "apply" ]]; then
  for f in "${SHORTFILES[@]}"; do
    [[ -n "$f" ]] && sed -i -E "s/(['\"])${OLD_SHORT}([-.])/\1${NEW_SHORT}\2/g" "$f"
  done
fi

# ── 6. file and directory renames ────────────────────────────────────────────
say ""
say "[6/6] Path renames"
mapfile -t PATHS < <(git ls-files | grep -i "$OLD_LC" || true)
if [[ "${#PATHS[@]}" -eq 0 ]]; then
  say "    none"
else
  for f in "${PATHS[@]}"; do
    [[ -n "$f" ]] || continue
    new=$(echo "$f" | sed -e "s/${OLD_UC}/${NEW_UC}/g" -e "s/${OLD_TC}/${NEW_TC}/g" -e "s/${OLD_LC}/${NEW_LC}/g")
    if [[ "$MODE" == "apply" ]]; then
      mkdir -p "$(dirname "$new")"
      git mv "$f" "$new" 2>/dev/null || mv "$f" "$new"
    else
      printf '    %s  →  %s\n' "$f" "$new"
    fi
  done
fi

# ── verification ─────────────────────────────────────────────────────────────
say ""
if [[ "$MODE" == "apply" ]]; then
  say "Verify"
  say "    Python syntax:"
  python3 -m py_compile app.py routes/*.py src/*.py 2>&1 | head -5 || warn "    py_compile reported problems — read them."
  say "    JS syntax (changed modules):"
  git diff --name-only HEAD 2>/dev/null | grep '\.js$' | head -60 | while read -r f; do
    [[ -f "$f" ]] && node --check "$f" 2>&1 | head -2
  done || true
  say ""
  say "    Remaining case-insensitive matches outside attribution files:"
  git grep -ic "$OLD_LC" -- "${EXCLUDES[@]}" 2>/dev/null | head -20 || say "      none"
  say ""
  warn "  Attribution and provenance files were deliberately NOT swept:"
  warn "    LICENSE  licenses/  NOTICE  ACKNOWLEDGMENTS.md  CREDITS.md"
  warn "    CHANGELOG.md  CYBERTOOTH_CHANGES.md  static/lib/  static/fonts/"
  say ""
  say "  Next, by hand:"
  say "    · Update your live .env on the host (ODYSSEUS_* → PANTHEON_*)"
  say "    · P0-05  vector collections — drop and re-index"
  say "    · P0-13  the mark"
  say "    · P0-14 … P0-27  notices, credits, the source link"
  say "    · docker compose up -d --build"
else
  say "  Dry run only. Nothing changed."
  say "  Re-run with --apply when the list above looks right."
fi
say ""
say "=== done ==="
