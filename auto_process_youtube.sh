#!/usr/bin/env bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autoyoutube"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autoyoutube"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

SRTOUTDIR="${AUTOYOUTUBE_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
MDOUTDIR="${AUTOYOUTUBE_MDOUTDIR:-$MDOUTDIR_DEFAULT}"
OUTDIR="$MDOUTDIR"
DEBUG=0
OVERWRITE=0

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
Usage: $0 [--outdir DIR] [--srtoutdir DIR] [--overwrite] [--debug] <youtube_url>

Options:
  --outdir DIR     Override the markdown output dir (default or in .env: AUTOYOUTUBE_MDOUTDIR)
    default: $MDOUTDIR;
  --srtoutdir DIR  Override the subtitles download dir (default or in .env:  AUTOYOUTUBE_SRTOUTDIR)
    default: $SRTOUTDIR; 
  --overwrite      Re-process even if destination .md already exists (default: skip existing)
  --debug          Show yt-dlp output and pass --debug to lecture_cleanup.sh

Examples:
  $0 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  $0 "https://youtu.be/dQw4w9WgXcQ"
EOF
}

URL=""

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

# Step 1: List subtitles
echo "[*] Detecting available subtitles..."
SUB_INFO=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --list-subs "$URL")

# Step 2: Extract auto-generated subtitle language code
AUTO_LANG=$(echo "$SUB_INFO" | grep '(Original)' | awk '{print $1}' | head -n 1)

if [ -z "$AUTO_LANG" ]; then
    echo "[!] No auto-generated subtitles found."
    exit 2
fi

LANG="${AUTO_LANG%-orig}"

echo "[*] Detected auto-sub language: $AUTO_LANG lang: $LANG"

# Step 3: Download the auto-generated subtitles
filename=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --print filename --skip-download --extractor-args "youtube:player_client=default" "$URL")
base_raw="${filename%.*}"
base="$(sanitize_filename "$base_raw")"
SRT_FILE="${base}.${AUTO_LANG}.srt"
TXT_FILE="${base}.${AUTO_LANG}.txt"
OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"

if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
    echo "[WARN] Output exists, skipping: $OUT_MD (use --overwrite to reprocess)"
    exit 0
fi

mkdir -p "$SRTOUTDIR" "$OUTDIR"

yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download --no-progress --extractor-args "youtube:player_client=default" -o "$SRTOUTDIR/${base}.%(ext)s" "$URL"

echo "Downloaded: $SRT_FILE"
#ls -alh  "$SRTOUTDIR/$SRT_FILE"
printf 'Download dir: %s\n' "$SRTOUTDIR"

# Step 4: Convert .srt to .txt
echo 'Converting srt to txt:'
"$SCRIPT_DIR/subtitle-utils/srt_to_custom.py" "$SRTOUTDIR/$SRT_FILE" > "$SRTOUTDIR/$TXT_FILE"
echo "[✓] Subtitles saved as plain text: $TXT_FILE"

echo "Starting AI processing"


# Preparing template
TEMPLATE_CTX="$SCRIPT_DIR/prompts/custom_context_general/youtube-url-timecodes.txt"
TMP_CTX="$(mktemp)"

# Safely escape the URL for sed (handles &, /, etc.)
ESCAPED_URL=$(printf '%s\n' "$URL" | sed 's/[&/\]/\\&/g')

# Replace the hardcoded URL in the template with the real one
sed "s|https://www.youtube.com/watch?v=dQw4w9WgXcQ|$ESCAPED_URL|g" "$TEMPLATE_CTX" > "$TMP_CTX"

"$SCRIPT_DIR/lecture_cleanup.sh" --input "$SRTOUTDIR/$TXT_FILE" --lang="$LANG" --outdir "$OUTDIR" --context-file "$TMP_CTX" --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" "${LECTURE_DEBUG_FLAG[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    TRANSCRIPTION_DATE="$(date '+%Y-%m-%d_%H-%M')"
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$base_raw"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'url: %s\n' "$URL"
        printf 'transcription_source: %s\n' "youtube-auto"
        printf 'transcription_date: %s\n' "$TRANSCRIPTION_DATE"
        printf 'language: %s\n' "$LANG"
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
