#!/usr/bin/env bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR="$SCRIPT_DIR/input/autoyoutube"
MDOUTDIR="$SCRIPT_DIR/output/autoyoutube"
mkdir -p "$SRTOUTDIR"

#==============================
#
print_help() {
    cat <<EOF
Usage: $0 <youtube_url>

Examples:
  $0 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  $0 "https://youtu.be/dQw4w9WgXcQ"
EOF
}

# No argument -> show help and exit
if [[ $# -lt 1 ]]; then
    echo "Error: No URL provided."
    echo
    print_help
    exit 1
fi

# Help flag
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    print_help
    exit 0
fi

URL="$1"

# remove SI= tracking parameter
URL="${URL%%?si=*}"

# remove playlist data (process only one wide)
# todo: bulk process playlists
URL="${URL%%&list=*}"

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
SUB_INFO=$(yt-dlp  --quiet --no-warnings --list-subs "$URL")

# Step 2: Extract auto-generated subtitle language code
AUTO_LANG=$(echo "$SUB_INFO" | grep '(Original)' | awk '{print $1}' | head -n 1)

if [ -z "$AUTO_LANG" ]; then
    echo "[!] No auto-generated subtitles found."
    exit 2
fi

LANG="${AUTO_LANG%-orig}"

echo "[*] Detected auto-sub language: $AUTO_LANG lang: $LANG"

# Step 3: Download the auto-generated subtitles
filename=$(yt-dlp --print filename --skip-download --quiet --no-warnings --extractor-args "youtube:player_client=default" "$URL")

#yt-dlp --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download --no-progress --quiet -o "$SRTOUTDIR/%(title)s.%(ext)s" "$URL"
yt-dlp --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download --no-progress --quiet --no-warnings --extractor-args "youtube:player_client=default" -o "$SRTOUTDIR/$filename" "$URL"


base="${filename%.*}"
SRT_FILE="${base}.${AUTO_LANG}.srt"
TXT_FILE="${base}.${AUTO_LANG}.txt"

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

$SCRIPT_DIR/lecture_cleanup.sh --input "$SRTOUTDIR/$TXT_FILE" --lang=$LANG --outdir "$MDOUTDIR" --context-file "$TMP_CTX" --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" #--trace

exit 0

