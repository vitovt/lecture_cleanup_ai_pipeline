#!/usr/bin/env bash
set -euo pipefail

# bulk_cleanup.sh
# Runs lecture_cleanup.sh over all *.txt files in an input directory, in alphabetical order.

show_usage() {
  cat <<'USAGE'
Usage:
  bulk_cleanup.sh --lang=<language> [--indir=<dir>] [other args...]

Description:
  - Requires --lang=<language>. If missing, exits with an error.
  - Reads all *.txt files in the input directory (default: ./input) in alphabetical order.
  - Prints the list of files found.
  - Asks for confirmation: "Run bulk cleanup of all those files? [y/N]"
  - If confirmed, sequentially runs:
      ./lecture_cleanup.sh --input <file> --lang=<language> [passed-through args...]
  - Any other arguments are passed through to lecture_cleanup.sh unchanged.
  - The input directory can be overridden with --indir (also passed through).

Examples:
  bulk_cleanup.sh --lang=en
  bulk_cleanup.sh --lang=de --indir=./notes --flag1 --flag2=val
USAGE
}

# If no args at all, show help (as requested)
if [[ $# -eq 0 ]]; then
  show_usage
  exit 1
fi

LANGUAGE=""
INDIR="./input"
# Collect args to pass through to lecture_cleanup.sh (including --lang and --indir)
PASSTHRU=()

# Parse args (support both --opt=value and --opt value forms)
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_usage
      exit 0
      ;;
    --lang=*)
      LANGUAGE="${1#*=}"
      PASSTHRU+=("$1")
      shift
      ;;
    --lang)
      if [[ ${2-} =~ ^-.*$ || -z ${2-} ]]; then
        echo "Error: --lang requires a value. Use --lang=<language>." >&2
        exit 1
      fi
      LANGUAGE="$2"
      PASSTHRU+=("$1" "$2")
      shift 2
      ;;
    --indir=*)
      INDIR="${1#*=}"
      PASSTHRU+=("$1")
      shift
      ;;
    --indir)
      if [[ ${2-} =~ ^-.*$ || -z ${2-} ]]; then
        echo "Error: --indir requires a value. Use --indir=<dir>." >&2
        exit 1
      fi
      INDIR="$2"
      PASSTHRU+=("$1" "$2")
      shift 2
      ;;
    *)
      # Anything else is just passed through
      PASSTHRU+=("$1")
      shift
      ;;
  esac
done

# Ensure language was provided
if [[ -z "${LANGUAGE}" ]]; then
  echo "Error: please provide --lang=<language>." >&2
  exit 1
fi

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
echo "Starting cleanup with language: ${LANGUAGE}"
echo

# Run sequentially
for f in "${FILES[@]}"; do
  echo ">>> ./lecture_cleanup.sh --input \"$f\" ${PASSTHRU[*]:-}"
  # shellcheck disable=SC2086 # we intentionally want word-splitting for PASSTHRU
  ./lecture_cleanup.sh --input "$f" ${PASSTHRU[@]+"${PASSTHRU[@]}"} 
  echo
done

echo "All done."

