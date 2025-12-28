#!/bin/bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

SANITIZE_HELPER="$SCRIPT_DIR/sanitize_filename.sh"
if [[ -f "$SANITIZE_HELPER" ]]; then
    # shellcheck disable=SC1091
    source "$SANITIZE_HELPER"
else
    echo "[WARN] Filename sanitizer missing ($SANITIZE_HELPER); filenames may be unsafe." >&2
    sanitize_filename() { printf '%s' "$1"; }
fi

# Check for URL argument
if [ -z "$1" ]; then
    echo "Usage: $0 <YouTube_URL>"
    exit 1
fi

URL="$1"

# Step 1: List subtitles
echo "[*] Detecting available subtitles..."
SUB_INFO=$(yt-dlp --list-subs "$URL")

# Step 2: Extract auto-generated subtitle language code
AUTO_LANG=$(echo "$SUB_INFO" | grep '(Original)' | awk '{print $1}' | head -n 1)

if [ -z "$AUTO_LANG" ]; then
    echo "[!] No auto-generated subtitles found."
    exit 2
fi

echo "[*] Detected auto-sub language: $AUTO_LANG"

# Step 3: Download the auto-generated subtitles
filename=$(yt-dlp --get-filename --no-download-archive "$URL")
base_raw="${filename%.*}"
base="$(sanitize_filename "$base_raw")"
yt-dlp --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download -o "${base}.%(ext)s" "$URL"

SRT_FILE="${base}.${AUTO_LANG}.srt"
TXT_FILE="${base}.${AUTO_LANG}.txt"

echo "Downloaded: $SRT_FILE"
ls "$SRT_FILE"

# Step 4: Convert .srt to .txt
echo 'Converting srt to txt:'
"$SCRIPT_DIR/srt_to_custom.py" "$SRT_FILE" > "$TXT_FILE"

echo "[✓] Subtitles saved as plain text: $TXT_FILE"

exit 0
