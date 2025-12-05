#!/usr/bin/env bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR="$SCRIPT_DIR/input/autoyoutube"
MDOUTDIR="$SCRIPT_DIR/output/autoyoutube"
OUTDIR="$MDOUTDIR"
DEBUG=0
OVERWRITE=0
mkdir -p "$SRTOUTDIR"

#==============================
#
print_help() {
    cat <<EOF
Usage: $0 [--outdir DIR] [--overwrite] [--debug] <youtube_url>

Options:
  --outdir DIR   Override the default markdown output dir 
    default: $MDOUTDIR
  --overwrite    Re-process even if destination .md already exists (default: skip existing)
  --debug        Show yt-dlp output and pass --debug to lecture_cleanup.sh

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

# remove SI= tracking parameter
URL="${URL%%?si=*}"

# remove playlist data (process only one wide)
# todo: bulk process playlists
URL="${URL%%&list=*}"

# remove timecode parameter
URL="${URL%%?t=*}"
URL="${URL%%&t=*}"

# Validate YouTube URL
# Accepts:
#   - https://www.youtube.com/...
#   - http://youtube.com/...
#   - https://youtu.be/...
if [[ ! "$URL" =~ ^https?://(www\.)?(youtube\.com|youtu\.be)/ ]]; then
    echo "Error: '$URL' is not a valid YouTube URL."
    exit 1
fi

# Enforce "watch?v="
if [[ ! "$URL" =~ ^https?://(www\.)?youtube\.com/watch\?v=.+ && ! "$URL" =~ ^https?://youtu\.be/.+ ]]; then
    echo "Error: '$URL' is not a recognized YouTube video URL format."
    exit 1
fi

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

base="${filename%.*}"
SRT_FILE="${base}.${AUTO_LANG}.srt"
TXT_FILE="${base}.${AUTO_LANG}.txt"
OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"

if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
    echo "[WARN] Output exists, skipping: $OUT_MD (use --overwrite to reprocess)"
    exit 0
fi

yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download --no-progress --extractor-args "youtube:player_client=default" -o "$SRTOUTDIR/$filename" "$URL"

echo "Downloaded: $SRT_FILE"
#ls -alh  "$SRTOUTDIR/$SRT_FILE"
printf 'Download dir: %s\n' "$SRTOUTDIR"

# Step 4: Convert .srt to .txt
echo 'Converting srt to txt:'
$SCRIPT_DIR/subtitle-utils/srt_to_custom.py "$SRTOUTDIR/$SRT_FILE" > "$SRTOUTDIR/$TXT_FILE"
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
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$base"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'url: %s\n' "$URL"
        printf '%s\n\n' '---'
        printf '# %s\n' "$base"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    echo "[+] Prepended front matter to $OUT_MD"
else
    echo "[WARN] Markdown output not found; expected: $OUT_MD"
fi

exit 0
