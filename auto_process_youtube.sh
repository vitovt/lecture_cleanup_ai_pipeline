#!/usr/bin/env bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/lecture_cleanup_shell_common.sh"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

DEBUG=0
OVERWRITE=0
SUBTITLE_TIMING_FLAGS=()
YOUTUBE_UPLOAD_DATE=""

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

    if [[ -z "$id" ]]; then
        return 1
    fi

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

#==============================
#
print_help() {
    cat <<EOF
Usage: $0 [--outdir DIR] [--srtoutdir DIR] [--context-file FILE] [--overwrite] [--debug] <youtube_url>

Options:
  --outdir DIR     Override the markdown output dir (default or in .env: CLEANUP_MDOUTDIR)
    default: $MDOUTDIR;
  --srtoutdir DIR  Override the final TXT/SRT dir (default or in .env:  TRANSCRIPT_OUTDIR)
    default: $SRTOUTDIR; 
  --overwrite      Re-process even if destination .md already exists (default: error if Markdown exists)
  --debug          Show yt-dlp output and pass --debug to lecture_cleanup.sh
  --time-offset OFFSET  Shift subtitles by signed HH:MM:SS (e.g. -00:15:33)
  --context-file FILE  Additional context file(s) passed to lecture_cleanup.sh (can be repeated)

Examples:
  ./${0##*/} "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ./${0##*/} "https://youtu.be/dQw4w9WgXcQ"
EOF
    lecture_cleanup_print_forwarded_help
}

URL=""
CONTEXT_FLAGS=()
CONTEXT_FILES=()

# Parse arguments
workflow_path_defaults || exit $?
lecture_workflow_init_logging "$@"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --outdir)
            if [[ -z "$2" ]]; then
                echo "Error: --outdir requires a directory path." >&2
                exit 1
            fi
            OUTDIR="$2"
            shift 2
            ;;
        --srtoutdir)
            if [[ -z "$2" ]]; then
                echo "Error: --srtoutdir requires a directory path." >&2
                exit 1
            fi
            SRTOUTDIR="$2"
            shift 2
            ;;
        --context-file)
            if [[ -z "$2" ]]; then
                echo "Error: --context-file requires a filename." >&2
                exit 1
            fi
            CONTEXT_FLAGS+=(--context-file "$2")
            CONTEXT_FILES+=("$2")
            shift 2
            ;;
        --overwrite)
            OVERWRITE=1
            shift
            ;;
        --time-offset)
            [[ -n "${2:-}" ]] || { echo 'ERROR: --time-offset requires signed HH:MM:SS.' >&2; exit 2; }
            SUBTITLE_TIMING_FLAGS=("--time-offset=$2")
            shift 2
            ;;
        --debug)
            DEBUG=1
            shift
            ;;
        --*)
            if lecture_cleanup_parse_option "$1" "${2:-}"; then
                shift "$LECTURE_CLEANUP_OPTION_SHIFT"
            else
                status=$?
                [[ "$status" -eq 2 ]] || echo "Error: unknown option '$1'." >&2
                print_help
                exit 2
            fi
            ;;
        *)
            if [[ -z "$URL" ]]; then
                URL="$1"
                shift
            else
                echo "Error: Unexpected argument '$1'." >&2
                echo
                print_help
                exit 1
            fi
            ;;
    esac
done

if [[ -z "$URL" ]]; then
    echo "Error: No URL provided." >&2
    echo
    print_help
    exit 1
fi

if [[ ${#CONTEXT_FILES[@]} -gt 0 ]]; then
    for ctx in "${CONTEXT_FILES[@]}"; do
        if [[ ! -f "$ctx" ]]; then
            echo "Error: context file not found: $ctx" >&2
            exit 1
        fi
    done
fi

YT_DLP_SILENT_FLAGS=()
LECTURE_DEBUG_FLAG=()

if [[ "$DEBUG" -ne 1 ]]; then
    YT_DLP_SILENT_FLAGS+=(--quiet --no-warnings)
else
    LECTURE_DEBUG_FLAG+=(--debug)
fi

# Normalize and validate the URL regardless of parameter order
RAW_URL="$URL"
if ! URL=$(normalize_youtube_url "$RAW_URL"); then
    echo "Error: '$RAW_URL' is not a recognized YouTube video URL." >&2
    exit 1
fi
echo "[INFO] Normalized URL: $URL"

# Step 1: List subtitles
echo "[INFO] Detecting available subtitles..."
SUB_INFO=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --print "%(upload_date)s" --list-subs "$URL")

# Step 2: Extract auto-generated subtitle language code
AUTO_LANG=$(echo "$SUB_INFO" | grep '(Original)' | awk '{print $1}' | head -n 1)
YOUTUBE_UPLOAD_DATE_RAW=$(printf '%s\n' "$SUB_INFO" | awk '/^[0-9]{8}$/ {print; exit}')
if [[ "$YOUTUBE_UPLOAD_DATE_RAW" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})$ ]]; then
    YOUTUBE_UPLOAD_DATE="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
elif [[ -n "$YOUTUBE_UPLOAD_DATE_RAW" ]]; then
    YOUTUBE_UPLOAD_DATE="$YOUTUBE_UPLOAD_DATE_RAW"
fi

if [ -z "$AUTO_LANG" ]; then
    echo "[WARN] No auto-generated subtitles found."
    exit 2
fi

LANG="${AUTO_LANG%-orig}"

echo "[INFO] Detected auto-sub language: $AUTO_LANG lang: $LANG"

# Step 3: Download the auto-generated subtitles
filename=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --print filename --skip-download --extractor-args "youtube:player_client=default" "$URL")
base_raw="${filename%.*}"
base="$(sanitize_filename "$base_raw")"
workflow_prepare_job "$URL" "$base" || exit $?
SRT_FILE="${base}.${AUTO_LANG}.srt"
TXT_FILE="${base}.${AUTO_LANG}.txt"

OUT_MD_EXISTED_BEFORE=0
if [[ -f "$OUT_MD" ]]; then
    OUT_MD_EXISTED_BEFORE=1
fi


mkdir -p "$SRTOUTDIR" "$OUTDIR"

yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --force-overwrites --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download --no-progress --extractor-args "youtube:player_client=default" -o "$SRTOUTDIR/${base}.%(ext)s" "$URL" || exit $?
python3 "$SCRIPT_DIR/subtitle-utils/subtitle_timing.py" "$SRTOUTDIR/$SRT_FILE" "$URL" "${SUBTITLE_TIMING_FLAGS[@]}" || exit $?

echo "Downloaded: $SRT_FILE"
#ls -alh  "$SRTOUTDIR/$SRT_FILE"
printf 'Download dir: %s\n' "$SRTOUTDIR"

# Step 4: Convert .srt to .txt
echo 'Converting srt to txt:'
"$SCRIPT_DIR/subtitle-utils/srt_to_custom.py" "$SRTOUTDIR/$SRT_FILE" > "$SRTOUTDIR/$TXT_FILE"
echo "[INFO] Subtitles saved as plain text: $TXT_FILE"

workflow_publish_transcript "$SRTOUTDIR/$SRT_FILE" "$base" srt || exit $?
workflow_publish_transcript "$SRTOUTDIR/$TXT_FILE" "$base" || exit $?
echo "Starting AI processing"


# Preparing template
TEMPLATE_CTX="$SCRIPT_DIR/prompts/custom_context_general/youtube-url-timecodes.txt"
TMP_CTX="$(mktemp)"

# Safely escape the URL for sed (handles &, /, etc.)
ESCAPED_URL=$(printf '%s\n' "$URL" | sed 's/[&/\]/\\&/g')

# Replace the hardcoded URL in the template with the real one
sed "s|https://youtu.be/dQw4w9WgXcQ|$ESCAPED_URL|g" "$TEMPLATE_CTX" > "$TMP_CTX"

"$SCRIPT_DIR/lecture_cleanup.sh" --input "$TXT_PATH" --lang="$LANG" --outdir "$OUTDIR" --context-file "$TMP_CTX" --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" "${CONTEXT_FLAGS[@]}" "${LECTURE_DEBUG_FLAG[@]}" "${LECTURE_CLEANUP_FLAGS[@]}"
cleanup_status=$?

if [[ "$cleanup_status" -ne 0 ]]; then
    if [[ "$OUT_MD_EXISTED_BEFORE" -eq 1 ]]; then
        echo "[WARN] Output .md already existed before this run and was not post-processed: $OUT_MD"
    elif [[ -f "$OUT_MD" ]]; then
        echo "[WARN] Output .md exists after failed run (possible leftover from earlier behavior): $OUT_MD"
    fi
    echo "[ERROR] AI processing failed (exit=$cleanup_status). Markdown front matter step skipped." >&2
    exit "$cleanup_status"
fi

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    TRANSCRIPTION_DATE="$(date '+%Y-%m-%d_%H-%M')"
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$base_raw"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'url: %s\n' "$URL"
        printf 'youtube_upload_date: "%s"\n' "$YOUTUBE_UPLOAD_DATE"
        printf 'transcription_source: %s\n' "youtube-auto"
        printf 'transcription_date: %s\n' "$TRANSCRIPTION_DATE"
        printf 'language: %s\n' "$LANG"
        printf '%s\n\n' '---'
        printf '# %s\n' "$base_raw"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    echo "[INFO] Prepended front matter to $OUT_MD"
else
    echo "[WARN] Markdown output not found; expected: $OUT_MD"
fi

exit 0
