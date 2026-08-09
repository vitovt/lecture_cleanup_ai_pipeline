#!/usr/bin/env bash
set -euo pipefail

# bulk_cleanup.sh
# Runs lecture_cleanup.sh over all *.txt files in an input directory, in alphabetical order.

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/lecture_cleanup_shell_common.sh"

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
  - Supported cleanup arguments are passed to lecture_cleanup.sh; --indir is only used here.

Options:
  --indir DIR       Input directory containing TXT files (default: ./input)
  --lang LANG       Required lecture language
  --format txt      Optional explicit input format; bulk inputs are always TXT
  --outdir DIR      Markdown output directory
  --context-file FILE
                     Extra cleanup context; repeatable
  --debug            Enable cleanup debug logging

Examples:
  bulk_cleanup.sh --lang uk
  bulk_cleanup.sh --lang de --indir ./notes --outdir ./output/de --format txt --debug
USAGE
  lecture_cleanup_print_forwarded_help
}

# If no args at all, show help
if [[ $# -eq 0 ]]; then
  show_usage
  exit 1
fi

INDIR="./input"
PASSTHRU=()

# Validate the complete cleanup option allowlist before asking for confirmation.
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
    --format|--outdir|--lang|--context-file)
      lecture_cleanup_add_value_option "$1" "${2:-}" || exit $?
      shift 2
      ;;
    --debug)
      lecture_cleanup_add_flag_option "$1"
      shift
      ;;
    --*=*)
      echo "Error: options must use '--option value' form (no '='): got '$1'" >&2
      echo
      show_usage
      exit 1
      ;;
    --*)
      if lecture_cleanup_parse_option "$1" "${2:-}"; then
        shift "$LECTURE_CLEANUP_OPTION_SHIFT"
      else
        status=$?
        [[ "$status" -eq 2 ]] || echo "Error: unknown option '$1'." >&2
        echo
        show_usage
        exit 2
      fi
      ;;
    *)
      echo "Error: unexpected argument '$1'." >&2
      echo
      show_usage
      exit 2
      ;;
  esac
done

PASSTHRU+=("${LECTURE_CLEANUP_FLAGS[@]}")

# Ensure lecture_cleanup.sh exists and is executable
if [[ ! -x "$SCRIPT_DIR/lecture_cleanup.sh" ]]; then
  echo "Error: lecture_cleanup.sh not found or not executable: $SCRIPT_DIR/lecture_cleanup.sh" >&2
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
  "$SCRIPT_DIR/lecture_cleanup.sh" --input "$f" ${PASSTHRU[@]+"${PASSTHRU[@]}"}
  echo
done

echo "All done."
