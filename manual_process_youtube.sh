#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autoyoutube"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
fi

MDOUTDIR="${AUTOYOUTUBE_MDOUTDIR:-$MDOUTDIR_DEFAULT}"
OUTDIR="$MDOUTDIR"
DEBUG=0
OVERWRITE=0
EXTRA_CONTEXT_FLAGS=()
EXTRA_CONTEXT_FILES=()

# Optional YouTube URL (used only for filename + timecode context replacement)
URL=""

# Mandatory inputs
INPUT_FILE=""
LANG=""

# External helper for URL normalization
YOUTUBE_NORMALIZER="$SCRIPT_DIR/subtitle-utils/normalize_youtube_url.py"
SANITIZE_HELPER="$SCRIPT_DIR/subtitle-utils/sanitize_filename.sh"

if [[ -f "$SANITIZE_HELPER" ]]; then
  # shellcheck disable=SC1091
  source "$SANITIZE_HELPER"
else
  echo "[WARN] Filename sanitizer missing ($SANITIZE_HELPER); filenames may be unsafe." >&2
  sanitize_filename() { printf '%s' "$1"; }
fi

# Simple bash fallback if the Python helper is missing or fails
normalize_youtube_url_fallback() {
  local raw="$1"
  local url="$raw"
  [[ -z "$url" ]] && return 1

  if [[ ! "$url" =~ ^https?:// ]]; then
    url="https://$url"
  fi

  local id=""
  if [[ "$url" =~ youtu\.be/([^?&#/]+) ]]; then
    id="${BASH_REMATCH[1]}"
  elif [[ "$url" =~ youtube\.com/(shorts|embed|live|v)/([^?&#/]+) ]]; then
    id="${BASH_REMATCH[2]}"
  elif [[ "$url" =~ v=([^&#/]+) ]]; then
    id="${BASH_REMATCH[1]}"
  fi

  [[ -z "$id" ]] && return 1

  id="${id%%\?*}"
  id="${id%%&*}"
  id="${id%%#*}"
  echo "https://youtu.be/$id"
  return 0
}

# Normalize incoming YouTube URLs using the Python helper when available
normalize_youtube_url() {
  local raw="$1"
  local helper="$YOUTUBE_NORMALIZER"
  local normalized=""

  if [[ -f "$helper" ]]; then
    if normalized=$(python3 "$helper" "$raw" 2>/dev/null); then
      echo "$normalized"
      return 0
    else
      echo "[WARN] URL helper failed, using fallback parser." >&2
    fi
  else
    echo "[WARN] URL helper missing ($helper), using fallback parser." >&2
  fi

  normalize_youtube_url_fallback "$raw"
}

print_help() {
  cat <<EOF
Usage: $0 --input FILE --lang LANG [--url YOUTUBE_URL] [--outdir DIR] [--context-file FILE] [--overwrite] [--debug]

Mandatory:
  --input FILE     Input subtitles text file (already prepared; no downloading here)
  --lang LANG      Language code to pass to lecture_cleanup.sh (e.g. en, de, uk)

Optional:
  --url URL        YouTube URL. If provided, script will:
                   - normalize URL
                   - derive video filename via yt-dlp (skip download)
                   - enable YouTube timecode context URL replacement
  --outdir DIR     Markdown output dir (default or in .env: AUTOYOUTUBE_MDOUTDIR)
    default: $OUTDIR
  --context-file FILE  Additional context file(s) passed to lecture_cleanup.sh (can be repeated)
  --overwrite      Re-process even if destination .md already exists (default: skip existing)
  --debug          Show yt-dlp output (when --url is used) and pass --debug to lecture_cleanup.sh

Examples:
  $0 --input "./input/video.en.txt" --lang en
  $0 --input "./input/video.txt" --lang en --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      print_help
      exit 0
      ;;
    --input)
      [[ -n "${2:-}" ]] || { echo "Error: --input requires a file path."; exit 1; }
      INPUT_FILE="$2"
      shift 2
      ;;
    --lang)
      [[ -n "${2:-}" ]] || { echo "Error: --lang requires a language code."; exit 1; }
      LANG="$2"
      shift 2
      ;;
    --url)
      [[ -n "${2:-}" ]] || { echo "Error: --url requires a YouTube URL."; exit 1; }
      URL="$2"
      shift 2
      ;;
    --outdir)
      [[ -n "${2:-}" ]] || { echo "Error: --outdir requires a directory path."; exit 1; }
      OUTDIR="$2"
      shift 2
      ;;
    --context-file)
      [[ -n "${2:-}" ]] || { echo "Error: --context-file requires a filename."; exit 1; }
      EXTRA_CONTEXT_FLAGS+=(--context-file "$2")
      EXTRA_CONTEXT_FILES+=("$2")
      shift 2
      ;;
    --overwrite)
      OVERWRITE=1
      shift
      ;;
    --debug)
      DEBUG=1
      shift
      ;;
    *)
      echo "Error: Unexpected argument '$1'."
      echo
      print_help
      exit 1
      ;;
  esac
done

# Validate mandatory args
if [[ -z "$INPUT_FILE" || -z "$LANG" ]]; then
  echo "Error: --input and --lang are mandatory."
  echo
  print_help
  exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "Error: Input file not found: $INPUT_FILE"
  exit 1
fi

if [[ ${#EXTRA_CONTEXT_FILES[@]} -gt 0 ]]; then
  for ctx in "${EXTRA_CONTEXT_FILES[@]}"; do
    if [[ ! -f "$ctx" ]]; then
      echo "Error: context file not found: $ctx"
      exit 1
    fi
  done
fi

mkdir -p "$OUTDIR"

# Debug flags
LECTURE_DEBUG_FLAG=()
if [[ "$DEBUG" -eq 1 ]]; then
  LECTURE_DEBUG_FLAG+=(--debug)
fi

# Determine base naming strategy:
# - If URL is provided: try to use yt-dlp-derived filename (same as before) and enable URL timecode context replacement
# - If URL is not provided: use input filename (without .txt) and DO NOT use the YouTube timecode context
INPUT_BASENAME="$(basename "$INPUT_FILE")"
INPUT_STEM_RAW="${INPUT_BASENAME%.txt}"
INPUT_STEM_SAFE="$(sanitize_filename "$INPUT_STEM_RAW")"

BASE_FOR_TITLE="$INPUT_STEM_SAFE"
OUT_STEM="$INPUT_STEM_SAFE"
NORMALIZED_URL=""

if [[ -n "$URL" ]]; then
  RAW_URL="$URL"
  if ! NORMALIZED_URL="$(normalize_youtube_url "$RAW_URL")"; then
    echo "Error: '$RAW_URL' is not a recognized YouTube video URL."
    exit 1
  fi
  echo "[*] Normalized URL: $NORMALIZED_URL"

  # Derive filename from yt-dlp (skip download) to preserve prior naming
  YT_DLP_FLAGS=()
  if [[ "$DEBUG" -ne 1 ]]; then
    YT_DLP_FLAGS+=(--quiet --no-warnings)
  fi

  if command -v yt-dlp >/dev/null 2>&1; then
    if filename="$(yt-dlp "${YT_DLP_FLAGS[@]}" --print filename --skip-download --extractor-args "youtube:player_client=default" "$NORMALIZED_URL" 2>/dev/null)"; then
      BASE_FOR_TITLE="$(sanitize_filename "${filename%.*}")"
      # Match old behavior: include language suffix in the output stem when URL-based naming is used
      OUT_STEM="${BASE_FOR_TITLE}.${LANG}"
    else
      echo "[WARN] yt-dlp failed to derive filename; falling back to input filename for naming." >&2
      BASE_FOR_TITLE="$INPUT_STEM_SAFE"
      OUT_STEM="${BASE_FOR_TITLE}.${LANG}"
    fi
  else
    echo "[WARN] yt-dlp not found; falling back to input filename for naming." >&2
    BASE_FOR_TITLE="$INPUT_STEM_SAFE"
    OUT_STEM="${BASE_FOR_TITLE}.${LANG}"
  fi
fi

OUT_MD="$OUTDIR/$OUT_STEM.md"

if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
  echo "[WARN] Output exists, skipping: $OUT_MD (use --overwrite to reprocess)"
  exit 0
fi

echo "[*] Input: $INPUT_FILE"
echo "[*] Lang:  $LANG"
echo "[*] Out:   $OUT_MD"

# Build context args:
# Always include lection-monolog-with-questions.txt
# Include youtube-url-timecodes context ONLY if URL was provided (and we can replace the URL).
CONTEXT_ARGS=()
CONTEXT_ARGS+=(--context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt")

TMP_CTX=""
if [[ -n "$NORMALIZED_URL" ]]; then
  TEMPLATE_CTX="$SCRIPT_DIR/prompts/custom_context_general/youtube-url-timecodes.txt"
  TMP_CTX="$(mktemp)"
  trap '[[ -n "${TMP_CTX:-}" && -f "${TMP_CTX:-}" ]] && rm -f "$TMP_CTX"' EXIT

  # Escape URL for sed replacement
  ESCAPED_URL="$(printf '%s' "$NORMALIZED_URL" | sed -e 's/[\/&]/\\&/g')"
  sed "s|https://www.youtube.com/watch?v=dQw4w9WgXcQ|$ESCAPED_URL|g" "$TEMPLATE_CTX" > "$TMP_CTX"

  CONTEXT_ARGS+=(--context-file "$TMP_CTX")
fi
if [[ ${#EXTRA_CONTEXT_FLAGS[@]} -gt 0 ]]; then
  CONTEXT_ARGS+=("${EXTRA_CONTEXT_FLAGS[@]}")
fi

echo "[*] Starting AI processing"
"$SCRIPT_DIR/lecture_cleanup.sh" \
  --input "$INPUT_FILE" \
  --lang="$LANG" \
  --outdir "$OUTDIR" \
  "${CONTEXT_ARGS[@]}" \
  "${LECTURE_DEBUG_FLAG[@]}"

# lecture_cleanup.sh most likely writes: OUTDIR/<input_stem>.md
# If we expect a different OUT_MD (URL-based naming), rename accordingly.
GENERATED_MD="$OUTDIR/$INPUT_STEM_RAW.md"
if [[ -f "$GENERATED_MD" && "$GENERATED_MD" != "$OUT_MD" ]]; then
  mv -f "$GENERATED_MD" "$OUT_MD"
fi

GENERATED_QC="$OUTDIR/${INPUT_STEM_RAW}_qc_report.csv"
OUT_QC="$OUTDIR/${OUT_STEM}_qc_report.csv"
if [[ -f "$GENERATED_QC" && "$GENERATED_QC" != "$OUT_QC" ]]; then
  mv -f "$GENERATED_QC" "$OUT_QC"
fi

# Prepend front matter
if [[ -f "$OUT_MD" ]]; then
  tmp_md="$(mktemp)"
  {
    printf '%s\n' '---'
    printf 'title: %s\n' "$BASE_FOR_TITLE"
    printf 'filename: %s\n' "$INPUT_BASENAME"
    printf 'lang: %s\n' "$LANG"
    if [[ -n "$NORMALIZED_URL" ]]; then
      printf 'url: %s\n' "$NORMALIZED_URL"
    fi
    printf '%s\n\n' '---'
    printf '# %s\n' "$BASE_FOR_TITLE"
    cat "$OUT_MD"
  } > "$tmp_md"
  mv "$tmp_md" "$OUT_MD"
  echo "[+] Prepended front matter to $OUT_MD"
else
  echo "[WARN] Markdown output not found; expected: $OUT_MD"
  exit 3
fi

exit 0
