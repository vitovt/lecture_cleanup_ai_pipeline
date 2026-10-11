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

URL=""
SUBTITLE_TIMING_FLAGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --time-offset)
            [[ -n "${2:-}" ]] || { echo 'ERROR: --time-offset requires signed HH:MM:SS.' >&2; exit 2; }
            SUBTITLE_TIMING_FLAGS=("--time-offset=$2")
            shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--time-offset +/-HH:MM:SS] <YouTube_URL>"
            echo 'Shift subtitle timestamps; example: --time-offset -00:15:33'
            exit 0 ;;
        --*) echo "ERROR: Unknown option: $1" >&2; exit 2 ;;
        *)
            [[ -z "$URL" ]] || { echo "ERROR: Unexpected argument: $1" >&2; exit 2; }
            URL="$1"; shift ;;
    esac
done
[[ -n "$URL" ]] || { echo "Usage: $0 [--time-offset +/-HH:MM:SS] <YouTube_URL>" >&2; exit 2; }

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
yt-dlp --force-overwrites --write-auto-sub --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download -o "${base}.%(ext)s" "$URL" || exit $?

SRT_FILE="${base}.${AUTO_LANG}.srt"
TXT_FILE="${base}.${AUTO_LANG}.txt"
python3 "$SCRIPT_DIR/subtitle_timing.py" "$SRT_FILE" "$URL" "${SUBTITLE_TIMING_FLAGS[@]}" || exit $?

echo "Downloaded: $SRT_FILE"
ls "$SRT_FILE"

# Step 4: Convert .srt to .txt
echo 'Converting srt to txt:'
"$SCRIPT_DIR/srt_to_custom.py" "$SRT_FILE" > "$TXT_FILE"

echo "[✓] Subtitles saved as plain text: $TXT_FILE"

exit 0
