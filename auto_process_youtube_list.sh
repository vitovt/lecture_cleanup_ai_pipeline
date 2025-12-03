#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

OUTDIR=""
DEBUG=0
PLAYLIST_URL=""

print_help() {
    cat <<EOF
Usage: $0 [--outdir DIR] [--debug] <youtube_playlist_url>

Expands a YouTube playlist and runs auto_process_youtube.sh for each video.

Options:
  --outdir DIR   Override markdown output dir for all videos (default: auto_process_youtube.sh default)
  --debug        Show yt-dlp output and pass --debug to auto_process_youtube.sh
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --outdir)
            if [[ -z "${2-}" ]]; then
                echo "Error: --outdir requires a directory path."
                exit 1
            fi
            OUTDIR="$2"
            shift 2
            ;;
        --debug)
            DEBUG=1
            shift
            ;;
        *)
            if [[ -z "$PLAYLIST_URL" ]]; then
                PLAYLIST_URL="$1"
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

if [[ -z "$PLAYLIST_URL" ]]; then
    echo "Error: No playlist URL provided."
    echo
    print_help
    exit 1
fi

# Basic YouTube URL validation
if [[ ! "$PLAYLIST_URL" =~ ^https?://(www\.)?(youtube\.com|youtu\.be)/ ]]; then
    echo "Error: '$PLAYLIST_URL' is not a valid YouTube URL."
    exit 1
fi

# Ensure playlist parameter is present
if [[ "$PLAYLIST_URL" != *"list="* ]]; then
    echo "Error: URL does not contain a playlist 'list=' parameter. Please pass a playlist link."
    exit 1
fi

YT_DLP_SILENT_FLAGS=()
CHILD_FLAGS=()
if [[ "$DEBUG" -ne 1 ]]; then
    YT_DLP_SILENT_FLAGS+=(--quiet --no-warnings)
else
    CHILD_FLAGS+=(--debug)
fi
if [[ -n "$OUTDIR" ]]; then
    CHILD_FLAGS+=(--outdir "$OUTDIR")
fi

echo "[*] Fetching playlist items…"
mapfile -t VIDEO_IDS < <(yt-dlp "${YT_DLP_SILENT_FLAGS[@]}" --flat-playlist --get-id "$PLAYLIST_URL")

if [[ ${#VIDEO_IDS[@]} -eq 0 ]]; then
    echo "[!] No videos found in playlist."
    exit 1
fi

TOTAL=${#VIDEO_IDS[@]}
SUCCESS=0
FAIL=0

for ((i=0; i<TOTAL; i++)); do
    vid_id="${VIDEO_IDS[$i]}"
    url="https://youtu.be/${vid_id}"
    printf '[%d/%d] Processing %s\n' "$((i+1))" "$TOTAL" "$url"
    if "$SCRIPT_DIR/auto_process_youtube.sh" "${CHILD_FLAGS[@]}" "$url"; then
        SUCCESS=$((SUCCESS+1))
    else
        echo "[WARN] Failed: $url"
        FAIL=$((FAIL+1))
    fi
done

echo "Done. Success: $SUCCESS / $TOTAL; Failed: $FAIL"
