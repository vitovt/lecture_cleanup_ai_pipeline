#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/lecture_cleanup_shell_common.sh"

OUTDIR=""
SRT_OUTDIR=""
DEBUG=0
OVERWRITE=0
ALL_MODE=0
LANG=""
CONTEXT_FILES=()
INPUT_FILES=()

print_help() {
    cat <<EOF_HELP
Usage: $0 --lang LANG [--outdir DIR] [--srtoutdir DIR] [--context-file FILE] [--overwrite] [--debug] [--all] [file1 file2 ...]

Processes multiple local media files via process_localaudiovideo_via_speechcore.sh.

Mandatory:
  --lang LANG       Language code passed to child script for every file

Input modes (choose one):
  1) Explicit file list in arguments:
       ./${0##*/} --lang ru file1.mp4 file2.mp3 ../file3.mp4 /home/user/Desktop/file5.mp4
  2) --all mode (scan current working directory):
       ./${0##*/} --lang en --all

Options:
  --outdir DIR      Forwarded to child script
  --srtoutdir DIR   Forwarded to child script
  --context-file FILE  Additional context file(s), can be repeated
  --overwrite       Forwarded to child script
  --debug           Forwarded to child script
  --all             Process all known audio/video files in current directory
  -h, --help        Show this help

Notes:
  - --all scans only current directory (non-recursive).
  - Media detection in --all is extension-based.
EOF_HELP
    lecture_cleanup_print_forwarded_help
}

to_lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

is_media_extension() {
    case "$1" in
        # audio
        mp3|m4a|wav|flac|aac|ogg|opus|wma|alac|aiff|aif|amr|mka|weba)
            return 0
            ;;
        # video
        mp4|m4v|mkv|mov|avi|webm|ts|m2ts|mts|mpg|mpeg|flv|wmv|3gp|ogv)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

lecture_workflow_init_logging "$@"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --lang)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --lang requires a language code." >&2
                exit 1
            fi
            LANG="$2"
            shift 2
            ;;
        --outdir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --outdir requires a directory path." >&2
                exit 1
            fi
            OUTDIR="$2"
            shift 2
            ;;
        --srtoutdir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --srtoutdir requires a directory path." >&2
                exit 1
            fi
            SRT_OUTDIR="$2"
            shift 2
            ;;
        --context-file)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --context-file requires a filename." >&2
                exit 1
            fi
            CONTEXT_FILES+=("$2")
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
        --all)
            ALL_MODE=1
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
            INPUT_FILES+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$LANG" ]]; then
    echo "Error: --lang is mandatory." >&2
    echo
    print_help
    exit 1
fi

if [[ "$ALL_MODE" -eq 1 && ${#INPUT_FILES[@]} -gt 0 ]]; then
    echo "Error: --all cannot be combined with explicit file arguments." >&2
    exit 1
fi

if [[ "$ALL_MODE" -eq 0 && ${#INPUT_FILES[@]} -eq 0 ]]; then
    echo "Error: Provide files to process or use --all." >&2
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

if [[ "$ALL_MODE" -eq 1 ]]; then
    shopt -s nullglob
    for path in "$PWD"/*; do
        [[ -f "$path" ]] || continue
        name="$(basename "$path")"
        [[ "$name" == *.* ]] || continue
        ext_raw="${name##*.}"
        ext="$(to_lower "$ext_raw")"
        if is_media_extension "$ext"; then
            INPUT_FILES+=("$path")
        fi
    done
    shopt -u nullglob

    if [[ ${#INPUT_FILES[@]} -eq 0 ]]; then
        echo "[WARN] No known audio/video files found in current directory: $PWD"
        exit 1
    fi
fi

for media_file in "${INPUT_FILES[@]}"; do
    if [[ ! -f "$media_file" ]]; then
        echo "Error: file not found: $media_file" >&2
        exit 1
    fi
done

CHILD_SCRIPT="$SCRIPT_DIR/process_localaudiovideo_via_speechcore.sh"
if [[ ! -f "$CHILD_SCRIPT" ]]; then
    echo "Error: child script not found: $CHILD_SCRIPT" >&2
    exit 1
fi

CHILD_FLAGS=(--lang "$LANG")
CHILD_FLAGS+=("${LECTURE_CLEANUP_FLAGS[@]}")
if [[ -n "$OUTDIR" ]]; then
    CHILD_FLAGS+=(--outdir "$OUTDIR")
fi
if [[ -n "$SRT_OUTDIR" ]]; then
    CHILD_FLAGS+=(--srtoutdir "$SRT_OUTDIR")
fi
if [[ "$OVERWRITE" -eq 1 ]]; then
    CHILD_FLAGS+=(--overwrite)
fi
if [[ "$DEBUG" -eq 1 ]]; then
    CHILD_FLAGS+=(--debug)
fi
if [[ ${#CONTEXT_FILES[@]} -gt 0 ]]; then
    for ctx in "${CONTEXT_FILES[@]}"; do
        CHILD_FLAGS+=(--context-file "$ctx")
    done
fi

TOTAL=${#INPUT_FILES[@]}
SUCCESS=0
FAIL=0

for i in "${!INPUT_FILES[@]}"; do
    n=$((i + 1))
    media_file="${INPUT_FILES[$i]}"
    printf '[%d/%d] Processing %s\n' "$n" "$TOTAL" "$media_file"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" "$media_file"; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "[WARN] Failed: $media_file"
        FAIL=$((FAIL + 1))
    fi
done

echo "Done. Success: $SUCCESS / $TOTAL; Failed: $FAIL"

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi

exit 0
