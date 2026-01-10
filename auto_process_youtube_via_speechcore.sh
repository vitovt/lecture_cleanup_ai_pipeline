#!/usr/bin/env bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autoyoutube"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autoyoutube"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

if [[ -n "${SPEECHCOREAI_API_KEY:-}" ]]; then
    export SPEECHCOREAI_API_KEY
elif [[ -f "$SCRIPT_DIR/speechcoreai-api/.env" ]]; then
    # shellcheck disable=SC1091
    set -a
    source "$SCRIPT_DIR/speechcoreai-api/.env"
    set +a
fi

SRTOUTDIR="${AUTOYOUTUBE_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
MDOUTDIR="${AUTOYOUTUBE_MDOUTDIR:-$MDOUTDIR_DEFAULT}"
OUTDIR="$MDOUTDIR"
DEBUG=0
OVERWRITE=0
LANG_OVERRIDE=""

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
Usage: $0 [--outdir DIR] [--srtoutdir DIR] [--lang LANG] [--context-file FILE] [--overwrite] [--debug] <youtube_url>

Downloads audio, transcribes it via SpeechcoreAI, and runs lecture_cleanup.sh.

Options:
  --outdir DIR     Override the markdown output dir (default or in .env: AUTOYOUTUBE_MDOUTDIR)
    default: $MDOUTDIR;
  --srtoutdir DIR  Override the audio/transcript dir (default or in .env:  AUTOYOUTUBE_SRTOUTDIR)
    default: $SRTOUTDIR;
  --lang LANG      Language code for lecture_cleanup.sh (auto-detected from YouTube if omitted)
  --overwrite      Re-process even if destination .md already exists (default: skip existing)
  --debug          Show yt-dlp output and pass --debug to lecture_cleanup.sh
  --context-file FILE  Additional context file(s) passed to lecture_cleanup.sh (can be repeated)

Examples:
  $0 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  $0 --lang en "https://youtu.be/dQw4w9WgXcQ"
EOF
}

URL=""
CONTEXT_FLAGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --outdir)
            if [[ -z "$2" ]]; then
                echo "Error: --outdir requires a directory path."
                exit 1
            fi
            OUTDIR="$2"
            shift 2
            ;;
        --srtoutdir)
            if [[ -z "$2" ]]; then
                echo "Error: --srtoutdir requires a directory path."
                exit 1
            fi
            SRTOUTDIR="$2"
            shift 2
            ;;
        --lang)
            if [[ -z "$2" ]]; then
                echo "Error: --lang requires a language code."
                exit 1
            fi
            LANG_OVERRIDE="$2"
            shift 2
            ;;
        --context-file)
            if [[ -z "$2" ]]; then
                echo "Error: --context-file requires a filename."
                exit 1
            fi
            CONTEXT_FLAGS+=(--context-file "$2")
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
            if [[ -z "$URL" ]]; then
                URL="$1"
                shift
            else
                echo "Error: Unexpected argument '$1'."
                echo
                print_help
                exit 1
            fi
            ;;
    esac
done

if [[ -z "$URL" ]]; then
    echo "Error: No URL provided."
    echo
    print_help
    exit 1
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
    echo "Error: '$RAW_URL' is not a recognized YouTube video URL."
    exit 1
fi
echo "[*] Normalized URL: $URL"

# Detect language from YouTube subtitles unless overridden
AUTO_LANG=""
LANG=""
if [[ -n "$LANG_OVERRIDE" ]]; then
    LANG="$LANG_OVERRIDE"
    AUTO_LANG="$LANG_OVERRIDE"
else
    echo "[*] Detecting available subtitles..."
    SUB_INFO=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --list-subs "$URL")

    AUTO_LANG=$(echo "$SUB_INFO" | grep '(Original)' | awk '{print $1}' | head -n 1)
    if [[ -z "$AUTO_LANG" ]]; then
        echo "[!] No auto-generated subtitles found."
        echo "[!] Provide --lang to continue without YouTube subtitles."
        exit 2
    fi
    LANG="${AUTO_LANG%-orig}"
    echo "[*] Detected auto-sub language: $AUTO_LANG lang: $LANG"
fi

if [[ -z "$LANG" ]]; then
    echo "Error: Unable to determine language."
    exit 1
fi

filename=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --print filename --skip-download --extractor-args "youtube:player_client=default" "$URL")
base_raw="${filename%.*}"
base="$(sanitize_filename "$base_raw")"
MP3_FILE="${base}.mp3"
RAW_TXT_FILE="${base}.txt"

if [[ -n "$AUTO_LANG" ]]; then
    TXT_FILE="${base}.${AUTO_LANG}.txt"
else
    TXT_FILE="${base}.txt"
fi

OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"

if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
    echo "[WARN] Output exists, skipping: $OUT_MD (use --overwrite to reprocess)"
    exit 0
fi

mkdir -p "$SRTOUTDIR" "$OUTDIR"

MP3_PATH="$SRTOUTDIR/$MP3_FILE"
if [[ ! -f "$MP3_PATH" || "$OVERWRITE" -eq 1 ]]; then
    YT_DLP_AUDIO_FLAGS=(
        --extract-audio
        --audio-format mp3
        --no-progress
        --extractor-args "youtube:player_client=default"
    )
    if [[ "$OVERWRITE" -eq 1 ]]; then
        YT_DLP_AUDIO_FLAGS+=(--force-overwrites)
    fi
    AUDIO_TEMPLATE="$SRTOUTDIR/${base}.%(ext)s"
    yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" "${YT_DLP_AUDIO_FLAGS[@]}" -o "$AUDIO_TEMPLATE" "$URL"
else
    echo "[*] Reusing existing audio: $MP3_FILE"
fi

if [[ ! -f "$MP3_PATH" ]]; then
    echo "[ERROR] MP3 not found after download: $MP3_PATH"
    exit 1
fi

RAW_TXT_PATH="$SRTOUTDIR/$RAW_TXT_FILE"
TXT_PATH="$SRTOUTDIR/$TXT_FILE"

if [[ -f "$TXT_PATH" && "$OVERWRITE" -ne 1 ]]; then
    echo "[*] Transcript exists, skipping SpeechcoreAI: $TXT_FILE"
elif [[ -f "$RAW_TXT_PATH" && "$OVERWRITE" -ne 1 && "$RAW_TXT_PATH" != "$TXT_PATH" ]]; then
    mv -f "$RAW_TXT_PATH" "$TXT_PATH"
    echo "[*] Using existing transcript: $TXT_FILE"
else
    SPEECHCORE_CLI="$SCRIPT_DIR/speechcoreai-api/speechcoreai_cli.py"
    if [[ ! -f "$SPEECHCORE_CLI" ]]; then
        echo "[ERROR] SpeechcoreAI CLI not found: $SPEECHCORE_CLI"
        exit 1
    fi
    TASK_ID_FILE="$SRTOUTDIR/${base}.speechcore_task_id"
    if [[ -f "$TASK_ID_FILE" && "$OVERWRITE" -eq 1 ]]; then
        rm -f "$TASK_ID_FILE"
    fi
    SPEECHCORE_ARGS=(--input-file "$MP3_PATH" --output-dir "$SRTOUTDIR" --task-output "$TASK_ID_FILE")
    case "$LANG" in
        ru|uk|en|de) SPEECHCORE_ARGS+=(--language "$LANG") ;;
    esac
    if [[ "$DEBUG" -eq 1 ]]; then
        SPEECHCORE_ARGS+=(--log-level DEBUG)
    fi
    python3 "$SPEECHCORE_CLI" "${SPEECHCORE_ARGS[@]}"

    if [[ -f "$RAW_TXT_PATH" && "$RAW_TXT_PATH" != "$TXT_PATH" ]]; then
        mv -f "$RAW_TXT_PATH" "$TXT_PATH"
    fi
fi

if [[ ! -f "$TXT_PATH" ]]; then
    echo "[WARN] Transcript output not found; expected: $TXT_PATH"
    exit 3
fi

echo "Transcript ready: $TXT_FILE"
printf 'Transcript dir: %s\n' "$SRTOUTDIR"

echo "Starting AI processing"

# Preparing template
TEMPLATE_CTX="$SCRIPT_DIR/prompts/custom_context_general/youtube-url-timecodes.txt"
TMP_CTX="$(mktemp)"

# Safely escape the URL for sed (handles &, /, etc.)
ESCAPED_URL=$(printf '%s\n' "$URL" | sed 's/[&/\]/\\&/g')

# Replace the hardcoded URL in the template with the real one
sed "s|https://www.youtube.com/watch?v=dQw4w9WgXcQ|$ESCAPED_URL|g" "$TEMPLATE_CTX" > "$TMP_CTX"

"$SCRIPT_DIR/lecture_cleanup.sh" --input "$TXT_PATH" --lang="$LANG" --outdir "$OUTDIR" --context-file "$TMP_CTX" --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" "${CONTEXT_FLAGS[@]}" "${LECTURE_DEBUG_FLAG[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    TRANSCRIPTION_DATE="$(date '+%Y-%m-%d_%H-%M')"
    TASK_ID_FILE="$SRTOUTDIR/${base}.speechcore_task_id"
    TRANSCRIBE_URL=""
    if [[ -f "$TASK_ID_FILE" ]]; then
        MP3_NAME="$(basename "$MP3_PATH")"
        TASK_ID="$(awk -v name="$MP3_NAME" -F '\t' '$1==name{tid=$2} END{print tid}' "$TASK_ID_FILE")"
        if [[ -z "$TASK_ID" ]]; then
            TASK_ID="$(tail -n 1 "$TASK_ID_FILE" | awk -F '\t' '{print $2}')"
        fi
        TASK_ID="$(printf '%s' "$TASK_ID" | tr -d '[:space:]')"
        if [[ -n "$TASK_ID" ]]; then
            SPEECHCORE_BASE_URL="${SPEECHCOREAI_BASE_URL:-https://speechcoreai.com}"
            TRANSCRIBE_URL="${SPEECHCORE_BASE_URL%/}/transcribe/${TASK_ID}"
        fi
    fi
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$base_raw"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'url: %s\n' "$URL"
        printf 'transcription_source: %s\n' "speechcore-ai"
        printf 'transcription_date: %s\n' "$TRANSCRIPTION_DATE"
        printf 'language: %s\n' "$LANG"
        printf 'transcribe_url: %s\n' "$TRANSCRIBE_URL"
        printf '%s\n\n' '---'
        printf '# %s\n' "$base_raw"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    echo "[+] Prepended front matter to $OUT_MD"
else
    echo "[WARN] Markdown output not found; expected: $OUT_MD"
fi

exit 0
