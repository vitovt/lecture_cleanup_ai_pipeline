#!/usr/bin/env bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autolocal"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autolocal"

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

SRTOUTDIR="${AUTOLOCAL_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
MDOUTDIR="${AUTOLOCAL_MDOUTDIR:-$MDOUTDIR_DEFAULT}"
OUTDIR="$MDOUTDIR"
DEBUG=0
OVERWRITE=0
LANG=""
INPUT_FILE=""
CONTEXT_FLAGS=()
CONTEXT_FILES=()

SANITIZE_HELPER="$SCRIPT_DIR/subtitle-utils/sanitize_filename.sh"

if [[ -f "$SANITIZE_HELPER" ]]; then
    # shellcheck disable=SC1091
    source "$SANITIZE_HELPER"
else
    echo "[WARN] Filename sanitizer missing ($SANITIZE_HELPER); filenames may be unsafe." >&2
    sanitize_filename() { printf '%s' "$1"; }
fi

print_help() {
    cat <<EOF_HELP
Usage: $0 [--outdir DIR] [--srtoutdir DIR] --lang LANG [--context-file FILE] [--overwrite] [--debug] <local_media_file>

Processes a local video/audio file via SpeechcoreAI and runs lecture_cleanup.sh.

Mandatory:
  --lang LANG      Language code for SpeechcoreAI and lecture_cleanup.sh

Options:
  --outdir DIR     Override markdown output dir (default or in .env: AUTOLOCAL_MDOUTDIR)
    default: $MDOUTDIR;
  --srtoutdir DIR  Override transcript/audio dir (default or in .env: AUTOLOCAL_SRTOUTDIR)
    default: $SRTOUTDIR;
  --context-file FILE  Additional context file(s) passed to lecture_cleanup.sh (can be repeated)
  --overwrite      Re-process even if destination .md already exists (default: skip existing)
  --debug          Show ffmpeg output and pass --debug to lecture_cleanup.sh

Audio input rules:
  - Audio files are processed directly (no video->audio decoding).
  - Supported audio formats: mp3, m4a, wav.
  - Any other audio extension exits with an error.

Examples:
  $0 --lang en ./recording.mp4
  $0 --lang zh --debug ./audio.m4a
EOF_HELP
}

to_lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

is_supported_audio_ext() {
    case "$1" in
        mp3|m4a|wav) return 0 ;;
        *) return 1 ;;
    esac
}

is_known_audio_ext() {
    case "$1" in
        mp3|m4a|wav|flac|aac|ogg|opus|wma|alac|aiff|aif|amr|mka|weba|webm) return 0 ;;
        *) return 1 ;;
    esac
}

detect_media_kind() {
    local media_path="$1"
    local fallback_ext="$2"
    local has_video=""
    local has_audio=""

    if command -v ffprobe >/dev/null 2>&1; then
        has_video="$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 "$media_path" 2>/dev/null | head -n 1 || true)"
        has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "$media_path" 2>/dev/null | head -n 1 || true)"
        if [[ -n "$has_video" ]]; then
            printf 'video'
            return 0
        fi
        if [[ -n "$has_audio" ]]; then
            printf 'audio'
            return 0
        fi
    fi

    if is_known_audio_ext "$fallback_ext"; then
        printf 'audio'
    else
        printf 'video'
    fi
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            print_help
            exit 0
            ;;
        --outdir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --outdir requires a directory path."
                exit 1
            fi
            OUTDIR="$2"
            shift 2
            ;;
        --srtoutdir)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --srtoutdir requires a directory path."
                exit 1
            fi
            SRTOUTDIR="$2"
            shift 2
            ;;
        --lang)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --lang requires a language code."
                exit 1
            fi
            LANG="$2"
            shift 2
            ;;
        --context-file)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --context-file requires a filename."
                exit 1
            fi
            CONTEXT_FLAGS+=(--context-file "$2")
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
        *)
            if [[ -z "$INPUT_FILE" ]]; then
                INPUT_FILE="$1"
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

if [[ -z "$INPUT_FILE" ]]; then
    echo "Error: No local media file provided."
    echo
    print_help
    exit 1
fi

if [[ -z "$LANG" ]]; then
    echo "Error: --lang is mandatory for local media processing."
    echo
    print_help
    exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: local media file not found: $INPUT_FILE"
    exit 1
fi

if [[ ${#CONTEXT_FILES[@]} -gt 0 ]]; then
    for ctx in "${CONTEXT_FILES[@]}"; do
        if [[ ! -f "$ctx" ]]; then
            echo "Error: context file not found: $ctx"
            exit 1
        fi
    done
fi

mkdir -p "$SRTOUTDIR" "$OUTDIR"

INPUT_PATH="$(readlink -f "$INPUT_FILE")"
INPUT_BASENAME="$(basename "$INPUT_PATH")"
if [[ "$INPUT_BASENAME" == *.* ]]; then
    INPUT_EXT_RAW="${INPUT_BASENAME##*.}"
else
    INPUT_EXT_RAW=""
fi
INPUT_EXT="$(to_lower "$INPUT_EXT_RAW")"

MEDIA_KIND="$(detect_media_kind "$INPUT_PATH" "$INPUT_EXT")"

BASE_RAW="${INPUT_BASENAME%.*}"
BASE_SAFE="$(sanitize_filename "$BASE_RAW")"
TXT_FILE="${BASE_SAFE}.${LANG}.txt"
OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"

if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
    echo "[WARN] Output exists, skipping: $OUT_MD (use --overwrite to reprocess)"
    exit 0
fi

AUDIO_INPUT_PATH=""
RAW_TXT_FILE=""

if [[ "$MEDIA_KIND" == "audio" ]]; then
    if ! is_supported_audio_ext "$INPUT_EXT"; then
        echo "Error: unsupported audio file extension: '.${INPUT_EXT}'. Speechcore supports: mp3, m4a, wav."
        exit 1
    fi
    AUDIO_INPUT_PATH="$INPUT_PATH"
    RAW_TXT_FILE="${BASE_RAW}.txt"
    echo "[*] Detected audio input; processing directly: $INPUT_BASENAME"
else
    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "Error: ffmpeg is required to extract audio from video input."
        exit 1
    fi

    MP3_FILE="${BASE_SAFE}.mp3"
    MP3_PATH="$SRTOUTDIR/$MP3_FILE"
    RAW_TXT_FILE="${BASE_SAFE}.txt"

    if [[ ! -f "$MP3_PATH" || "$OVERWRITE" -eq 1 ]]; then
        echo "[*] Extracting audio from video to MP3..."
        FFMPEG_ARGS=(-hide_banner)
        if [[ "$DEBUG" -eq 1 ]]; then
            FFMPEG_ARGS+=(-loglevel info)
        else
            FFMPEG_ARGS+=(-loglevel error)
        fi
        if [[ "$OVERWRITE" -eq 1 ]]; then
            FFMPEG_ARGS+=(-y)
        else
            FFMPEG_ARGS+=(-n)
        fi
        FFMPEG_ARGS+=(-i "$INPUT_PATH" -vn -c:a libmp3lame -q:a 2 "$MP3_PATH")

        if [[ "$DEBUG" -eq 1 ]]; then
            ffmpeg "${FFMPEG_ARGS[@]}"
        else
            ffmpeg "${FFMPEG_ARGS[@]}" >/dev/null 2>&1
        fi
    else
        echo "[*] Reusing existing extracted audio: $MP3_FILE"
    fi

    if [[ ! -f "$MP3_PATH" ]]; then
        echo "[ERROR] MP3 not found after extraction: $MP3_PATH"
        exit 1
    fi

    AUDIO_INPUT_PATH="$MP3_PATH"
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

    TASK_ID_FILE="$SRTOUTDIR/${BASE_SAFE}.speechcore_task_id"
    if [[ -f "$TASK_ID_FILE" && "$OVERWRITE" -eq 1 ]]; then
        rm -f "$TASK_ID_FILE"
    fi

    SPEECHCORE_ARGS=(--input-file "$AUDIO_INPUT_PATH" --output-dir "$SRTOUTDIR" --task-output "$TASK_ID_FILE" --language "$LANG")
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

LECTURE_DEBUG_FLAG=()
if [[ "$DEBUG" -eq 1 ]]; then
    LECTURE_DEBUG_FLAG+=(--debug)
fi

"$SCRIPT_DIR/lecture_cleanup.sh" \
    --input "$TXT_PATH" \
    --lang="$LANG" \
    --outdir "$OUTDIR" \
    --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" \
    "${CONTEXT_FLAGS[@]}" \
    "${LECTURE_DEBUG_FLAG[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    TRANSCRIPTION_DATE="$(date '+%Y-%m-%d_%H-%M')"
    TASK_ID_FILE="$SRTOUTDIR/${BASE_SAFE}.speechcore_task_id"
    TRANSCRIBE_URL=""
    if [[ -f "$TASK_ID_FILE" ]]; then
        AUDIO_NAME="$(basename "$AUDIO_INPUT_PATH")"
        TASK_ID="$(awk -v name="$AUDIO_NAME" -F '\t' '$1==name{tid=$2} END{print tid}' "$TASK_ID_FILE")"
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
        printf 'title: %s\n' "$BASE_RAW"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'source_file: %s\n' "$INPUT_PATH"
        printf 'source_type: %s\n' "$MEDIA_KIND"
        printf 'transcription_source: %s\n' "speechcore-ai"
        printf 'transcription_date: %s\n' "$TRANSCRIPTION_DATE"
        printf 'language: %s\n' "$LANG"
        printf 'transcribe_url: %s\n' "$TRANSCRIBE_URL"
        printf '%s\n\n' '---'
        printf '# %s\n' "$BASE_RAW"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    echo "[+] Prepended front matter to $OUT_MD"
else
    echo "[WARN] Markdown output not found; expected: $OUT_MD"
fi

exit 0
