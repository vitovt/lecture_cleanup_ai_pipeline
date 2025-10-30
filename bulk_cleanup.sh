#!/usr/bin/env bash
set -euo pipefail

# bulk_cleanup.sh
# Runs lecture_cleanup.sh over all *.txt files in an input directory, in alphabetical order.

show_usage() {
  cat <<'USAGE'
Usage:
  bulk_cleanup.sh --lang <language> [--indir <dir>] [other args...]

Description:
  - Reads all *.txt files in the input directory (default: ./input) in alphabetical order.
  - Prints the list of files found and asks for confirmation.
  - If confirmed, sequentially runs:
      ./lecture_cleanup.sh --input <file> [passed-through args...]
  - All options must use the space-separated form: --option value (no '=')
  - All arguments are passed through unchanged to lecture_cleanup.sh, EXCEPT --indir which is only used here.

Examples:
  bulk_cleanup.sh --lang uk
  bulk_cleanup.sh --lang de --indir ./notes --outdir ./output/de --format txt --debug
USAGE
}

# If no args at all, show help
if [[ $# -eq 0 ]]; then
  show_usage
  exit 1
fi

INDIR="./input"
PASSTHRU=()

# Parse args minimally: strip only --indir, error on any --key=value usage, pass everything else.
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_usage
      exit 0
      ;;
    --indir)
      if [[ -z "${2-}" ]]; then
        echo "Error: --indir requires a value. Use: --indir <dir>" >&2
        exit 1
      fi
      INDIR="$2"
      shift 2
      ;;
    --*=*)
      echo "Error: options must use '--option value' form (no '='): got '$1'" >&2
      echo
      show_usage
      exit 1
      ;;
    *)
      PASSTHRU+=("$1")
      shift
      ;;
  esac
done

# Ensure lecture_cleanup.sh exists and is executable
if [[ ! -x "./lecture_cleanup.sh" ]]; then
  echo "Error: ./lecture_cleanup.sh not found or not executable." >&2
  exit 1
fi

# Ensure input directory exists
if [[ ! -d "$INDIR" ]]; then
  echo "Error: input directory '$INDIR' does not exist." >&2
  exit 1
fi

# Gather *.txt files (alphabetical, non-recursive)
shopt -s nullglob
# Use find+sort -z to be robust and strictly alphabetical (C collation)
mapfile -d '' FILES < <(LC_ALL=C find "$INDIR" -maxdepth 1 -type f -name '*.txt' -print0 | sort -z)

if (( ${#FILES[@]} == 0 )); then
  echo "No .txt files found in '$INDIR'." >&2
  exit 1
fi

echo "Found ${#FILES[@]} .txt file(s) in '$INDIR':"
for f in "${FILES[@]}"; do
  printf '  - %s\n' "$f"
done
echo

# Confirmation prompt (default: No)
read -r -p "Run bulk cleanup of all those files? [y/N] " ANSWER
if [[ ! "$ANSWER" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

echo

# Run sequentially
for f in "${FILES[@]}"; do
  echo ">>> ./lecture_cleanup.sh --input \"$f\" ${PASSTHRU[*]:-}"
  # shellcheck disable=SC2086 # intentional word splitting for PASSTHRU
  ./lecture_cleanup.sh --input "$f" ${PASSTHRU[@]+"${PASSTHRU[@]}"}
  echo
done

echo "All done."

