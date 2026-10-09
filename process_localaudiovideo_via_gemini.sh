#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autolocal-gemini"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autolocal-gemini"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # Root .env configures workflow paths only. GEMINI_API_KEY is loaded solely
    # from stt-api/.env or the exported process environment.
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

SRTOUTDIR="${GEMINI_LOCAL_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
OUTDIR="${GEMINI_LOCAL_MDOUTDIR:-${AUTOLOCAL_MDOUTDIR:-$MDOUTDIR_DEFAULT}}"
INPUT_FILE=""
LANG=""
ADDITIONAL_LANGS=()
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
CONTEXT_FLAGS=()
CONTEXT_FILES=()
LOG_LEVEL_OVERRIDE=""
OVERWRITE=0
PREFLIGHT=0
PREFLIGHT_OUTPUT=""
STT_CONFIG=""
GEMINI_MODEL=""
GEMINI_MODE=""
GEMINI_TIMESTAMPS=""
GEMINI_DIARIZATION=""
GEMINI_RESUME=""
GEMINI_CACHE_DIR=""

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/gemini_shell_common.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/lecture_cleanup_shell_common.sh"

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

Transcribes one local audio/video file with Gemini 3.5 Transcribe, supports
multilingual code-switching, then runs lecture_cleanup.sh.

Mandatory:
  <local_media_file>       Existing local audio or video file
  --lang CODE              Primary language; required for cleanup and filenames

Language format:
  --lang CODE              Primary spoken/cleanup language (two-letter base).
                           Both forms work:
                           uk or uk-UA, de or de-DE, en or en-US, ru or ru-RU
  --additional-lang CODE   Additional spoken language; repeatable; accepts the
                           same shortcuts and full BCP-47 format as --lang

The primary language is sent first to Gemini and also becomes the Markdown
language (for example, --lang uk-UA produces the .uk.md suffix). Additional
languages affect speech recognition only, not cleanup language or filenames.

Custom vocabulary (optional, repeatable):
  --custom-vocabulary TERM       One exact term or short phrase
  --custom-vocabulary-file FILE  UTF-8 file, one term/phrase per line;
                                 blank lines and # comments are ignored

All vocabulary sources are merged and deduplicated. Gemini accepts at most
1000 final entries and recommends about 100 or fewer. Vocabulary is incompatible
with timestamps and diarization; explicitly use --timestamps off.

Gemini transcription options:
  --stt-config FILE       Override stt-api/config.yaml
  --model MODEL           Model override (default: gemini-3.5-transcribe)
  --mode verbatim|smart   Verbatim preserves speech; smart cleans disfluencies
  --timestamps on|off     Word timestamps (default from stt-api config: on)
  --diarization provider|off    Gemini speaker labels (default: off)
  --resume on|off         Reuse matching chunk checkpoints (default: on)
  --cache-dir DIR         Checkpoint directory override

Compatibility rules validated before media conversion or upload:
  vocabulary + timestamps    invalid
  vocabulary + diarization   invalid
  smart + timestamps         invalid
  smart + diarization        invalid

Pipeline options:
  --outdir DIR           Markdown output directory (default: $OUTDIR)
  --srtoutdir DIR        Audio/transcript directory (default: $SRTOUTDIR)
  --context-file FILE    Extra lecture cleanup context; repeatable
  --overwrite            Replace outputs and bypass matching checkpoints
  --quiet|--error|--info|--debug|--trace
                         Console detail; info is the default

Preflight:
  --preflight            Inspect/split-plan media; do not upload or clean
  --preflight-output FILE
                         Write machine-readable preflight JSON; requires
                         --preflight

Examples:
  ./${0##*/} --lang uk ./lesson.mp4
  ./${0##*/} --lang uk-UA --additional-lang de-DE ./bilingual.m4a
  ./${0##*/} --lang uk --additional-lang de --additional-lang en ./lesson.wav
  ./${0##*/} --lang uk --additional-lang de --timestamps off \
      --custom-vocabulary 'Sicherheitsgruppe' \
      --custom-vocabulary-file ./aws-terms.txt ./lesson.mp4
  ./${0##*/} --lang ru-RU --preflight ./recording.m4a
EOF
    lecture_cleanup_print_forwarded_help
}

need_value() {
    [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }
}

lecture_workflow_init_logging "$@"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --lang) need_value "$1" "${2:-}"; LANG="$2"; shift 2 ;;
        --additional-lang) need_value "$1" "${2:-}"; ADDITIONAL_LANGS+=("$2"); shift 2 ;;
        --custom-vocabulary) need_value "$1" "${2:-}"; CUSTOM_VOCABULARY+=("$2"); shift 2 ;;
        --custom-vocabulary-file) need_value "$1" "${2:-}"; CUSTOM_VOCABULARY_FILES+=("$2"); shift 2 ;;
        --stt-config) need_value "$1" "${2:-}"; STT_CONFIG="$2"; shift 2 ;;
        --model) need_value "$1" "${2:-}"; GEMINI_MODEL="$2"; shift 2 ;;
        --mode) need_value "$1" "${2:-}"; GEMINI_MODE="$2"; shift 2 ;;
        --timestamps) need_value "$1" "${2:-}"; GEMINI_TIMESTAMPS="$2"; shift 2 ;;
        --diarization) need_value "$1" "${2:-}"; GEMINI_DIARIZATION="$2"; shift 2 ;;
        --resume) need_value "$1" "${2:-}"; GEMINI_RESUME="$2"; shift 2 ;;
        --cache-dir) need_value "$1" "${2:-}"; GEMINI_CACHE_DIR="$2"; shift 2 ;;
        --outdir) need_value "$1" "${2:-}"; OUTDIR="$2"; shift 2 ;;
        --srtoutdir) need_value "$1" "${2:-}"; SRTOUTDIR="$2"; shift 2 ;;
        --context-file) need_value "$1" "${2:-}"; CONTEXT_FLAGS+=(--context-file "$2"); CONTEXT_FILES+=("$2"); shift 2 ;;
        --overwrite) OVERWRITE=1; shift ;;
        --preflight) PREFLIGHT=1; shift ;;
        --preflight-output) need_value "$1" "${2:-}"; PREFLIGHT_OUTPUT="$2"; shift 2 ;;
        --quiet) LOG_LEVEL_OVERRIDE=quiet; shift ;;
        --error) LOG_LEVEL_OVERRIDE=error; shift ;;
        --info) LOG_LEVEL_OVERRIDE=info; shift ;;
        --debug) LOG_LEVEL_OVERRIDE=debug; shift ;;
        --trace) LOG_LEVEL_OVERRIDE=trace; shift ;;
        --log-level) need_value "$1" "${2:-}"; LOG_LEVEL_OVERRIDE="$2"; shift 2 ;;
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
            [[ -z "$INPUT_FILE" ]] || { echo "Error: unexpected argument '$1'." >&2; exit 2; }
            INPUT_FILE="$1"
            shift
            ;;
    esac
done

gemini_apply_early_log_level
[[ -n "$INPUT_FILE" ]] || { echo "Error: no local media file provided." >&2; print_help; exit 2; }
[[ -n "$LANG" ]] || { echo "Error: --lang is required." >&2; print_help; exit 2; }
[[ "${LANG,,}" != "auto" ]] || { echo "Error: --lang auto is not allowed in workflows; choose the cleanup language." >&2; exit 2; }
[[ -f "$INPUT_FILE" ]] || { echo "Error: file not found: $INPUT_FILE" >&2; exit 3; }
python3 "$SCRIPT_DIR/subtitle-utils/audio_streams.py" --single "$INPUT_FILE" || exit $?

[[ -z "$PREFLIGHT_OUTPUT" || "$PREFLIGHT" -eq 1 ]] || { echo "Error: --preflight-output requires --preflight." >&2; exit 2; }
for file in "${CONTEXT_FILES[@]}" "${CUSTOM_VOCABULARY_FILES[@]}"; do
    [[ -f "$file" ]] || { echo "Error: referenced file not found: $file" >&2; exit 2; }
done

gemini_init || exit $?
gemini_resolve_log_level || exit $?
gemini_validate_options || exit $?
LANG_LABEL="$(gemini_primary_label "$LANG")" || { echo "Error: unusable primary language '$LANG'." >&2; exit 2; }
mkdir -p "$SRTOUTDIR" "$OUTDIR"

INPUT_PATH="$(readlink -f "$INPUT_FILE")"
INPUT_BASENAME="$(basename "$INPUT_PATH")"
INPUT_EXT=""
[[ "$INPUT_BASENAME" == *.* ]] && INPUT_EXT="${INPUT_BASENAME##*.}"
INPUT_EXT="${INPUT_EXT,,}"
MEDIA_KIND="$(gemini_detect_media_kind "$INPUT_PATH" "$INPUT_EXT")"
BASE_RAW="${INPUT_BASENAME%.*}"
BASE_SAFE="$(sanitize_filename "$BASE_RAW")"

gemini_info "Stage 1/4: preparing local media"
case "$MEDIA_KIND" in
    audio)
        AUDIO_INPUT_PATH="$INPUT_PATH"
        ;;
    video)
        AUDIO_INPUT_PATH="$SRTOUTDIR/${BASE_SAFE}.flac"
        gemini_extract_video_audio "$INPUT_PATH" "$AUDIO_INPUT_PATH" "$OVERWRITE" || exit 3
        ;;
    *)
        echo "Error: unable to identify supported audio/video input: $INPUT_PATH" >&2
        exit 3
        ;;
esac

if [[ "$PREFLIGHT" -eq 1 ]]; then
    temporary=0
    if [[ -z "$PREFLIGHT_OUTPUT" ]]; then PREFLIGHT_OUTPUT="$(mktemp)"; temporary=1; fi
    gemini_preflight "$AUDIO_INPUT_PATH" "$PREFLIGHT_OUTPUT"
    rc=$?
    [[ "$rc" -eq 0 && "$temporary" -eq 1 ]] && "$STT_PYTHON" -m json.tool "$PREFLIGHT_OUTPUT"
    [[ "$temporary" -eq 1 ]] && rm -f "$PREFLIGHT_OUTPUT"
    exit "$rc"
fi

TXT_FILE="${BASE_SAFE}.${LANG_LABEL}.txt"
TXT_PATH="$SRTOUTDIR/$TXT_FILE"
OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"
if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
    gemini_warn "Output exists, skipping: $OUT_MD (use --overwrite)"
    exit 0
fi

METADATA_FILE="$SRTOUTDIR/${BASE_SAFE}.${LANG_LABEL}.metadata.json"
gemini_info "Stage 2/4: transcribing with Gemini"
gemini_transcribe "$AUDIO_INPUT_PATH" "$SRTOUTDIR" "$METADATA_FILE" "${BASE_SAFE}.${LANG_LABEL}" >/dev/null
rc=$?
[[ "$rc" -eq 0 ]] || exit "$rc"
RAW_TXT_PATH="$(gemini_json_field "$METADATA_FILE" transcript_file)"
MODEL_USED="$(gemini_json_field "$METADATA_FILE" model)"
[[ -n "$RAW_TXT_PATH" && -f "$RAW_TXT_PATH" ]] || { echo "Error: Gemini transcript not found: $RAW_TXT_PATH" >&2; exit 3; }
[[ "$RAW_TXT_PATH" == "$TXT_PATH" ]] || mv -f "$RAW_TXT_PATH" "$TXT_PATH"

LECTURE_LOG_FLAG=(--log-level "$LOG_LEVEL")
gemini_info "Stage 3/4: cleaning transcript with the lecture pipeline"
"$SCRIPT_DIR/lecture_cleanup.sh" \
    --input "$TXT_PATH" \
    --lang="$LANG_LABEL" \
    --outdir "$OUTDIR" \
    --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" \
    "${CONTEXT_FLAGS[@]}" \
    "${LECTURE_LOG_FLAG[@]}" \
    "${LECTURE_CLEANUP_FLAGS[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    languages="$LANG"
    for value in "${ADDITIONAL_LANGS[@]}"; do languages+=",$value"; done
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$BASE_RAW"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'source_file: %s\n' "$INPUT_PATH"
        printf 'source_type: %s\n' "$MEDIA_KIND"
        printf 'transcription_source: gemini\n'
        printf 'transcription_date: %s\n' "$(date '+%Y-%m-%d_%H-%M')"
        printf 'language: %s\n' "$LANG_LABEL"
        printf 'transcription_languages: "%s"\n' "$languages"
        printf 'model: %s\n' "$MODEL_USED"
        printf '%s\n\n' '---'
        printf '# %s\n' "$BASE_RAW"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    gemini_info "Output: $OUT_MD"
    gemini_info "Stage 4/4 complete"
else
    echo "Error: Markdown output not found: $OUT_MD" >&2
    exit 3
fi
