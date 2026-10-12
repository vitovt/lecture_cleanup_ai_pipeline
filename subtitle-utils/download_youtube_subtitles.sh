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
SUBTITLE_SELECTION_FLAGS=()
DEBUG=0
source "$SCRIPT_DIR/youtube_subtitle_selection.sh"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lang|--subtitle-source)
            [[ -n "${2:-}" && "$2" != --* ]] || { echo "ERROR: $1 requires a value." >&2; exit 2; }
            SUBTITLE_SELECTION_FLAGS+=("$1" "$2"); shift 2 ;;
        --lang=*|--subtitle-source=*)
            SUBTITLE_SELECTION_FLAGS+=("$1"); shift ;;
        --debug) DEBUG=1; shift ;;
        --time-offset)
            [[ -n "${2:-}" ]] || { echo 'ERROR: --time-offset requires signed HH:MM:SS.' >&2; exit 2; }
            SUBTITLE_TIMING_FLAGS=("--time-offset=$2")
            shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--time-offset +/-HH:MM:SS] <YouTube_URL>"
            echo '  --lang CODE: original audio language by default; select an exact variant if ambiguous'
            echo '  --subtitle-source auto|manual|prefer-manual: default auto (native ASR only)'
            echo '  --debug: show yt-dlp diagnostics'
            echo 'Shift subtitle timestamps; example: --time-offset -00:15:33'
            exit 0 ;;
        --*) echo "ERROR: Unknown option: $1" >&2; exit 2 ;;
        *)
            [[ -z "$URL" ]] || { echo "ERROR: Unexpected argument: $1" >&2; exit 2; }
            URL="$1"; shift ;;
    esac
done
[[ -n "$URL" ]] || { echo "Usage: $0 [--time-offset +/-HH:MM:SS] <YouTube_URL>" >&2; exit 2; }

echo "[INFO] Detecting available subtitles..."
select_youtube_subtitles "$SCRIPT_DIR/.." "$URL" || exit $?
YT_DLP_SILENT_FLAGS=()
[[ "$DEBUG" -eq 1 ]] || YT_DLP_SILENT_FLAGS=(--quiet --no-warnings)

filename=$(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --get-filename --no-download-archive "$URL") || exit $?
base_raw="${filename%.*}"
base="$(sanitize_filename "$base_raw")"
yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --no-download-archive --no-playlist --force-overwrites "${SUBTITLE_DOWNLOAD_FLAGS[@]}" --sub-lang "$AUTO_LANG" --convert-subs srt --skip-download -o "${base}.%(ext)s" --load-info-json "$SUBTITLE_METADATA" || exit $?

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
