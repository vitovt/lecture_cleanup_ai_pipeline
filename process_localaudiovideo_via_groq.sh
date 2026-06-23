#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autolocal-groq"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autolocal-groq"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

SRTOUTDIR="${GROQ_LOCAL_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
MDOUTDIR="${GROQ_LOCAL_MDOUTDIR:-${AUTOLOCAL_MDOUTDIR:-$MDOUTDIR_DEFAULT}}"
OUTDIR="$MDOUTDIR"
INPUT_FILE=""
LANG=""
LOG_LEVEL_OVERRIDE=""
OVERWRITE=0
PREFLIGHT=0
PREFLIGHT_OUTPUT=""
CONTEXT_FLAGS=()
CONTEXT_FILES=()

GROQ_CONFIG=""
GROQ_MODEL=""
GROQ_TEMPERATURE=""
GROQ_DIARIZATION=""
GROQ_NUM_SPEAKERS=""
GROQ_OVERSIZE_POLICIES=()
GROQ_SAVE_JSON=""
GROQ_MAX_FILE_COST_USD=""
GROQ_PROMPT=""
GROQ_ALLOW_UNKNOWN_MODEL=0

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/groq_shell_common.sh"

SANITIZE_HELPER="$SCRIPT_DIR/subtitle-utils/sanitize_filename.sh"
if [[ -f "$SANITIZE_HELPER" ]]; then
    # shellcheck disable=SC1090
    source "$SANITIZE_HELPER"
else
    sanitize_filename() { printf '%s' "$1"; }
fi

print_help() {
    cat <<EOF
Usage: $0 [OPTIONS] <local_media_file>

Extracts audio when needed, transcribes it with Groq Whisper, optionally adds
local pyannote speaker labels, then runs lecture_cleanup.sh.

Language:
  --lang CODE|auto       Required unless Groq config enables implicit auto language

Pipeline options:
  --outdir DIR           Markdown output directory (resolved default: $OUTDIR)
                         Uses GROQ_LOCAL_MDOUTDIR, then AUTOLOCAL_MDOUTDIR
                         from the root .env, then the Groq project default
  --srtoutdir DIR        Audio/transcript directory (default: $SRTOUTDIR)
  --context-file FILE    Extra lecture cleanup context; repeatable
  --overwrite            Replace existing audio/transcript/Markdown outputs
  --quiet                Print nothing, including errors
  --error                Print errors only
  --info                 Show stage progress and results (default)
  --debug                Show verbose diagnostics/request metadata, no payloads
  --trace                Show debug output plus full request/response payloads

If no logging flag is given, logging.level from groq-api/config.yaml is used.

Groq options:
  --groq-config FILE     Override groq-api/config.yaml
  --model MODEL          Override Groq Whisper model
  --temperature VALUE    Transcription temperature, 0..1
  --prompt TEXT          Optional Whisper context prompt
  --diarization on|off   Enable/disable local pyannote speakers
  --num-speakers auto|N  Automatic or exact speaker count
  --oversize-policy MODE error|compress|chunk|interactive; repeat for fallbacks
  --save-json on|off     Retain raw verbose_json response
  --max-file-cost-usd N  Estimated per-file USD cap; negative disables
  --allow-unknown-model  Permit a future model slug not in known_models

Preflight:
  --preflight            Prepare media and validate format/size/cost; do not upload
  --preflight-output FILE  Write machine-readable preflight JSON

Supported direct audio containers: FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, WEBM.
Other audio formats fail. Video formats are converted to 16 kHz mono FLAC.

Examples:
  $0 --lang ru ./meeting.mp4
  $0 --lang auto --diarization off ./lecture.m4a
  $0 --lang en --num-speakers 2 --oversize-policy chunk --info ./long-video.mkv
  $0 --lang uk --oversize-policy compress --oversize-policy chunk ./large.mp3
  $0 --lang en --trace ./problem-recording.m4a
EOF
}

need_value() {
    if [[ -z "${2:-}" ]]; then
        echo "Error: $1 requires a value." >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --lang) need_value "$1" "${2:-}"; LANG="$2"; shift 2 ;;
        --outdir) need_value "$1" "${2:-}"; OUTDIR="$2"; shift 2 ;;
        --srtoutdir) need_value "$1" "${2:-}"; SRTOUTDIR="$2"; shift 2 ;;
        --context-file) need_value "$1" "${2:-}"; CONTEXT_FLAGS+=(--context-file "$2"); CONTEXT_FILES+=("$2"); shift 2 ;;
        --groq-config) need_value "$1" "${2:-}"; GROQ_CONFIG="$2"; shift 2 ;;
        --model) need_value "$1" "${2:-}"; GROQ_MODEL="$2"; shift 2 ;;
        --temperature) need_value "$1" "${2:-}"; GROQ_TEMPERATURE="$2"; shift 2 ;;
        --prompt) need_value "$1" "${2:-}"; GROQ_PROMPT="$2"; shift 2 ;;
        --diarization) need_value "$1" "${2:-}"; GROQ_DIARIZATION="$2"; shift 2 ;;
        --num-speakers) need_value "$1" "${2:-}"; GROQ_NUM_SPEAKERS="$2"; shift 2 ;;
        --oversize-policy) need_value "$1" "${2:-}"; GROQ_OVERSIZE_POLICIES+=("$2"); shift 2 ;;
        --save-json) need_value "$1" "${2:-}"; GROQ_SAVE_JSON="$2"; shift 2 ;;
        --max-file-cost-usd) need_value "$1" "${2:-}"; GROQ_MAX_FILE_COST_USD="$2"; shift 2 ;;
        --allow-unknown-model) GROQ_ALLOW_UNKNOWN_MODEL=1; shift ;;
        --overwrite) OVERWRITE=1; shift ;;
        --quiet) LOG_LEVEL_OVERRIDE=quiet; shift ;;
        --error) LOG_LEVEL_OVERRIDE=error; shift ;;
        --info) LOG_LEVEL_OVERRIDE=info; shift ;;
        --debug) LOG_LEVEL_OVERRIDE=debug; shift ;;
        --trace) LOG_LEVEL_OVERRIDE=trace; shift ;;
        --preflight) PREFLIGHT=1; shift ;;
        --preflight-output) need_value "$1" "${2:-}"; PREFLIGHT_OUTPUT="$2"; shift 2 ;;
        --*) echo "Error: unknown option '$1'." >&2; print_help; exit 2 ;;
        *)
            if [[ -n "$INPUT_FILE" ]]; then
                echo "Error: unexpected argument '$1'." >&2
                exit 2
            fi
            INPUT_FILE="$1"
            shift
            ;;
    esac
done
groq_apply_early_quiet

if [[ -z "$INPUT_FILE" ]]; then
    echo "Error: no local media file provided." >&2
    print_help
    exit 2
fi
if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: file not found: $INPUT_FILE" >&2
    exit 3
fi
if [[ -n "$PREFLIGHT_OUTPUT" && "$PREFLIGHT" -ne 1 ]]; then
    echo "Error: --preflight-output requires --preflight." >&2
    exit 2
fi
for ctx in "${CONTEXT_FILES[@]}"; do
    [[ -f "$ctx" ]] || { echo "Error: context file not found: $ctx" >&2; exit 2; }
done

groq_init_python || exit 2
groq_resolve_log_level || exit 2
groq_apply_log_level
groq_build_cli_flags
groq_debug "Effective logging level: $LOG_LEVEL"
mkdir -p "$SRTOUTDIR" "$OUTDIR"
groq_info "Stage 1/4: inspecting local media"

INPUT_PATH="$(readlink -f "$INPUT_FILE")"
INPUT_BASENAME="$(basename "$INPUT_PATH")"
INPUT_EXT=""
[[ "$INPUT_BASENAME" == *.* ]] && INPUT_EXT="${INPUT_BASENAME##*.}"
INPUT_EXT="${INPUT_EXT,,}"
MEDIA_KIND="$(groq_detect_media_kind "$INPUT_PATH" "$INPUT_EXT")"
BASE_RAW="${INPUT_BASENAME%.*}"
BASE_SAFE="$(sanitize_filename "$BASE_RAW")"
AUDIO_INPUT_PATH=""

case "$MEDIA_KIND" in
    audio)
        if ! groq_is_supported_audio_extension "$INPUT_EXT"; then
            echo "Error: unsupported direct audio '.$INPUT_EXT'. See groq-api/config.default.yaml for accepted formats." >&2
            exit 3
        fi
        AUDIO_INPUT_PATH="$INPUT_PATH"
        groq_info "Direct audio input: $INPUT_BASENAME"
        groq_info "Media inspection complete: direct audio will be used without conversion"
        ;;
    video)
        AUDIO_INPUT_PATH="$SRTOUTDIR/${BASE_SAFE}.flac"
        groq_info "Extracting video audio for Groq"
        groq_extract_video_audio "$INPUT_PATH" "$AUDIO_INPUT_PATH" "$OVERWRITE" || exit 3
        groq_info "Video-to-audio extraction complete: $AUDIO_INPUT_PATH"
        ;;
    *)
        echo "Error: unable to identify audio/video input: $INPUT_PATH" >&2
        exit 3
        ;;
esac

if [[ "$PREFLIGHT" -eq 1 ]]; then
    groq_info "Stage 2/4: running Groq preflight"
    TEMP_PREFLIGHT=0
    if [[ -z "$PREFLIGHT_OUTPUT" ]]; then
        PREFLIGHT_OUTPUT="$(mktemp)"
        TEMP_PREFLIGHT=1
    fi
    if groq_preflight "$AUDIO_INPUT_PATH" "$PREFLIGHT_OUTPUT" "$LANG"; then
        if [[ "$TEMP_PREFLIGHT" -eq 1 ]]; then
            "$GROQ_PYTHON" -m json.tool "$PREFLIGHT_OUTPUT"
            rm -f "$PREFLIGHT_OUTPUT"
        fi
        exit 0
    else
        rc=$?
        [[ "$TEMP_PREFLIGHT" -eq 1 ]] && rm -f "$PREFLIGHT_OUTPUT"
        exit "$rc"
    fi
fi

LANG_LABEL="${LANG:-auto}"
if [[ "$LANG_LABEL" != "auto" ]]; then
    OUT_MD="$OUTDIR/${BASE_SAFE}.${LANG_LABEL}.md"
    if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
        groq_warn "Output exists, skipping: $OUT_MD (use --overwrite)"
        exit 0
    fi
fi

METADATA_FILE="$(mktemp)"
trap 'rm -f "$METADATA_FILE"' EXIT
MODEL_USED="${GROQ_MODEL:-whisper-large-v3}"
REUSE_TXT=""
if [[ "$LANG_LABEL" != "auto" ]]; then
    REUSE_TXT="$SRTOUTDIR/${BASE_SAFE}.${LANG_LABEL}.txt"
fi
if [[ -n "$REUSE_TXT" && -f "$REUSE_TXT" && "$OVERWRITE" -ne 1 ]]; then
    groq_info "Reusing existing transcript: $REUSE_TXT"
    RAW_TXT_PATH="$REUSE_TXT"
    RAW_JSON_PATH="$SRTOUTDIR/${BASE_SAFE}.${LANG_LABEL}.json"
else
    groq_info "Stage 2/4: transcribing audio and detecting speakers"
    groq_transcribe "$AUDIO_INPUT_PATH" "$SRTOUTDIR" "$METADATA_FILE" "$LANG"
    rc=$?
    [[ "$rc" -eq 0 ]] || exit "$rc"
    RAW_TXT_PATH="$(groq_json_field "$METADATA_FILE" transcript_file)"
    RAW_JSON_PATH="$(groq_json_field "$METADATA_FILE" verbose_json_file)"
    DETECTED_LANG="$(groq_json_field "$METADATA_FILE" detected_language)"
    MODEL_USED="$(groq_json_field "$METADATA_FILE" model)"
    if [[ "$LANG_LABEL" == "auto" ]]; then
        LANG_LABEL="${DETECTED_LANG,,}"
    fi
fi
if [[ ! "$LANG_LABEL" =~ ^[a-z]{2}$ ]]; then
    echo "Error: Groq did not return a usable two-letter detected language ('$LANG_LABEL')." >&2
    exit 3
fi

TXT_FILE="${BASE_SAFE}.${LANG_LABEL}.txt"
TXT_PATH="$SRTOUTDIR/$TXT_FILE"
if [[ -z "$RAW_TXT_PATH" || ! -f "$RAW_TXT_PATH" ]]; then
    echo "Error: Groq transcript output not found: $RAW_TXT_PATH" >&2
    exit 3
fi
if [[ "$RAW_TXT_PATH" != "$TXT_PATH" ]]; then
    mv -f "$RAW_TXT_PATH" "$TXT_PATH"
fi
if [[ -n "$RAW_JSON_PATH" && -f "$RAW_JSON_PATH" ]]; then
    JSON_PATH="$SRTOUTDIR/${BASE_SAFE}.${LANG_LABEL}.json"
    [[ "$RAW_JSON_PATH" == "$JSON_PATH" ]] || mv -f "$RAW_JSON_PATH" "$JSON_PATH"
fi

OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"
LECTURE_LOG_FLAG=()
LECTURE_LOG_FLAG+=(--log-level "$LOG_LEVEL")

groq_info "Starting AI cleanup: $TXT_FILE"
groq_info "Stage 3/4: cleaning transcript with the lecture pipeline"
"$SCRIPT_DIR/lecture_cleanup.sh" \
    --input "$TXT_PATH" \
    --lang="$LANG_LABEL" \
    --outdir "$OUTDIR" \
    --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" \
    "${CONTEXT_FLAGS[@]}" \
    "${LECTURE_LOG_FLAG[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$BASE_RAW"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'source_file: %s\n' "$INPUT_PATH"
        printf 'source_type: %s\n' "$MEDIA_KIND"
        printf 'transcription_source: %s\n' "groq"
        printf 'transcription_date: %s\n' "$(date '+%Y-%m-%d_%H-%M')"
        printf 'language: %s\n' "$LANG_LABEL"
        printf 'model: %s\n' "$MODEL_USED"
        printf '%s\n\n' '---'
        printf '# %s\n' "$BASE_RAW"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    groq_info "Output: $OUT_MD"
    groq_info "Stage 4/4 complete: Markdown output written"
else
    echo "Error: Markdown output not found: $OUT_MD" >&2
    exit 3
fi
