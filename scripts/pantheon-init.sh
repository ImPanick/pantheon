#!/usr/bin/env bash
# Pantheon — repository initialisation sweep
#
# Performs the mechanical half of P0 as one reviewable change:
#   P0-02 cosmetic surfaces   P0-03 env prefix        P0-04 storage keys
#   P0-06 session cookie      P0-07 headers + UA      P0-08 compose + user
#   P0-10 CLI script names    P0-11 packages + events
#
# Does NOT touch: LICENSE, licenses/, static/lib/, package-lock.json, .git/,
# or any attribution file. Those are handled by hand in P0-14 … P0-27.
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

# ── files that must never be swept ───────────────────────────────────────────
EXCLUDES=(
  ':!.git/**'
  ':!LICENSE'
  ':!licenses/**'
  ':!static/lib/**'
  ':!package-lock.json'
  ':!NOTICE'
  ':!ACKNOWLEDGMENTS.md'
  ':!CREDITS.md'
  ':!.pantheon/**'
  ':!static/fonts/**'
)

say() { printf '\033[36m%s\033[0m\n' "$*"; }
warn(){ printf '\033[33m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[[ -f app.py && -d static ]] || die "Run this from the repository root."
command -v git >/dev/null || die "git not found."

if [[ -n "$(git status --porcelain)" ]]; then
  warn "Working tree is dirty. Commit or stash first — you want a clean diff to review."
  [[ "$MODE" == "apply" ]] && die "Refusing to apply onto a dirty tree."
fi

say "=== Pantheon init · mode: $MODE ==="

# ── 1. content sweep ─────────────────────────────────────────────────────────
say ""
say "[1/4] Content sweep — odysseus/Odysseus/ODYSSEUS → pantheon/Pantheon/PANTHEON"

FILES=$(git ls-files -- "${EXCLUDES[@]}" | while read -r f; do
  [[ -f "$f" ]] || continue
  grep -Iq . "$f" 2>/dev/null || continue          # skip binaries
  grep -Iqi "$OLD_LC" "$f" 2>/dev/null && echo "$f"
done)

COUNT=$(printf '%s\n' "$FILES" | grep -c . || true)
say "    $COUNT files contain a match."

if [[ "$MODE" == "dry-run" ]]; then
  say "    Top 20 by occurrence:"
  printf '%s\n' "$FILES" | while read -r f; do
    [[ -n "$f" ]] && printf '%6d  %s\n' "$(grep -oi "$OLD_LC" "$f" | wc -l)" "$f"
  done | sort -rn | head -20
else
  printf '%s\n' "$FILES" | while read -r f; do
    [[ -n "$f" ]] || continue
    sed -i \
      -e "s/${OLD_UC}/${NEW_UC}/g" \
      -e "s/${OLD_TC}/${NEW_TC}/g" \
      -e "s/${OLD_LC}/${NEW_LC}/g" \
      "$f"
  done
  say "    Rewritten."
fi

# ── 2. short-prefix storage keys ─────────────────────────────────────────────
say ""
say "[2/4] Short-prefix storage keys — 'ody-' / 'ody.' → 'pan-' / 'pan.'"
SHORTFILES=$(git ls-files -- 'static/**' "${EXCLUDES[@]}" | while read -r f; do
  [[ -f "$f" ]] && grep -Eq "['\"]${OLD_SHORT}[-.]" "$f" 2>/dev/null && echo "$f"
done || true)
SCOUNT=$(printf '%s\n' "$SHORTFILES" | grep -c . || true)
say "    $SCOUNT files."
if [[ "$MODE" == "apply" ]]; then
  printf '%s\n' "$SHORTFILES" | while read -r f; do
    [[ -n "$f" ]] && sed -i -E "s/(['\"])${OLD_SHORT}([-.])/\1${NEW_SHORT}\2/g" "$f"
  done
fi

# ── 3. file and directory renames ────────────────────────────────────────────
say ""
say "[3/4] Path renames"
PATHS=$(git ls-files | grep -i "$OLD_LC" || true)
if [[ -z "$PATHS" ]]; then
  say "    none"
else
  printf '%s\n' "$PATHS" | while read -r f; do
    new=$(echo "$f" | sed -e "s/${OLD_UC}/${NEW_UC}/g" -e "s/${OLD_TC}/${NEW_TC}/g" -e "s/${OLD_LC}/${NEW_LC}/g")
    if [[ "$MODE" == "apply" ]]; then
      mkdir -p "$(dirname "$new")"
      git mv "$f" "$new" 2>/dev/null || mv "$f" "$new"
    else
      printf '    %s  →  %s\n' "$f" "$new"
    fi
  done
fi

# ── 4. verification ──────────────────────────────────────────────────────────
say ""
say "[4/4] Verify"
if [[ "$MODE" == "apply" ]]; then
  say "    Python syntax:"
  python3 -m py_compile app.py routes/*.py src/*.py 2>&1 | head -5 || warn "    py_compile reported problems — read them."
  say "    JS syntax (changed modules):"
  git diff --name-only --cached HEAD 2>/dev/null | grep '\.js$' | head -40 | while read -r f; do
    [[ -f "$f" ]] && node --check "$f" 2>&1 | head -2
  done || true
  say ""
  say "    Remaining case-insensitive matches outside attribution files:"
  git grep -ic "$OLD_LC" -- "${EXCLUDES[@]}" 2>/dev/null | head -20 || say "    none"
  say ""
  warn "  Attribution files were deliberately NOT swept. They still say Odysseus, correctly:"
  warn "    LICENSE  licenses/  NOTICE  ACKNOWLEDGMENTS.md  CREDITS.md  static/lib/"
  say ""
  say "  Next, by hand:"
  say "    · Update your live .env on the host (ODYSSEUS_* → PANTHEON_*)"
  say "    · P0-05  vector collections — re-index or run pantheon-migrate-vectors.py"
  say "    · P0-13  the mark"
  say "    · P0-14 … P0-27  notices, credits, the source link"
  say "    · docker compose up -d --build"
else
  say ""
  say "  Dry run only. Nothing changed."
  say "  Re-run with --apply when the list above looks right."
fi
say ""
say "=== done ==="
