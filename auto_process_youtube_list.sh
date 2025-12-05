#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

OUTDIR=""
DEBUG=0
PLAYLIST_URL=""
VIDEOS_SPEC=""
OVERWRITE=0

print_help() {
    cat <<EOF
Usage: $0 [--outdir DIR] [--videos SPEC] [--overwrite] [--debug] <youtube_playlist_url>

Expands a YouTube playlist and runs auto_process_youtube.sh for each video.

Options:
  --outdir DIR   Override markdown output dir for all videos (default: auto_process_youtube.sh default)
  --videos SPEC  Process only selected items (1-based). Examples: 1-6 | 2,4,6 | 1-3,5,7,9-11,13
  --overwrite    Re-process even if destination .md already exists (default: skip existing)
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
        --videos)
            if [[ -z "${2-}" ]]; then
                echo "Error: --videos requires a list, e.g. 1-3,5,7"
                exit 1
            fi
            VIDEOS_SPEC="$2"
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
if [[ "$OVERWRITE" -eq 1 ]]; then
    CHILD_FLAGS+=(--overwrite)
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

declare -A VIDEO_FILTER=()
if [[ -n "$VIDEOS_SPEC" ]]; then
    IFS=',' read -ra PARTS <<< "$VIDEOS_SPEC"
    for raw_part in "${PARTS[@]}"; do
        part="${raw_part//[[:space:]]/}"
        [[ -z "$part" ]] && continue
        if [[ "$part" == *-* ]]; then
            IFS='-' read -r a b <<< "$part"
            if [[ "$a" =~ ^[0-9]+$ && "$b" =~ ^[0-9]+$ ]]; then
                if (( a > b )); then tmp=$a; a=$b; b=$tmp; fi
                for ((n=a; n<=b; n++)); do
                    VIDEO_FILTER[$n]=1
                done
            else
                echo "[WARN] Ignoring invalid range: $part"
            fi
        else
            if [[ "$part" =~ ^[0-9]+$ ]]; then
                VIDEO_FILTER[$part]=1
            else
                echo "[WARN] Ignoring invalid item: $part"
            fi
        fi
    done
fi

PROCESS_IDX=()
for i in "${!VIDEO_IDS[@]}"; do
    idx=$((i+1))
    if [[ ${#VIDEO_FILTER[@]} -gt 0 && -z "${VIDEO_FILTER[$idx]-}" ]]; then
        continue
    fi
    PROCESS_IDX+=("$i")
done

PLAN_TOTAL=${#PROCESS_IDX[@]}
if (( PLAN_TOTAL == 0 )); then
    echo "[!] No videos selected (check --videos range against playlist length=${#VIDEO_IDS[@]})."
    exit 1
fi

TOTAL=${#VIDEO_IDS[@]}
SUCCESS=0
FAIL=0

for ((k=0; k<PLAN_TOTAL; k++)); do
    i=${PROCESS_IDX[$k]}
    vid_id="${VIDEO_IDS[$i]}"
    url="https://youtu.be/${vid_id}"
    printf '[%d/%d] Processing VIDEO #%d %s\n' "$((k+1))" "$PLAN_TOTAL" "$((i+1))" "$url"
    if "$SCRIPT_DIR/auto_process_youtube.sh" "${CHILD_FLAGS[@]}" "$url"; then
        SUCCESS=$((SUCCESS+1))
    else
        echo "[WARN] Failed: $url"
        FAIL=$((FAIL+1))
    fi
done

echo "Done. Success: $SUCCESS / $PLAN_TOTAL; Failed: $FAIL"
