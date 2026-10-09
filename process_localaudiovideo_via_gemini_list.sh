#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
CHILD_SCRIPT="$SCRIPT_DIR/process_localaudiovideo_via_gemini.sh"

LANG=""
ADDITIONAL_LANGS=()
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
CONTEXT_FILES=()
INPUT_FILES=()
ALL_MODE=0
OVERWRITE=0
OUTDIR=""
SRT_OUTDIR=""
LOG_LEVEL_OVERRIDE=""
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

print_help() {
    cat <<EOF
Usage: $0 [OPTIONS] [file1 file2 ...]

Preflights and processes multiple local audio/video files through
process_localaudiovideo_via_gemini.sh. Explicit files and --all are exclusive.

Mandatory:
  --lang CODE           Primary cleanup/transcription language
  file1 ... OR --all    Explicit files, or known media in the current directory

Language format:
  --lang CODE              Required, with a two-letter base: uk/uk-UA,
                           de/de-DE, en/en-US, or ru/ru-RU
  --additional-lang CODE   Extra code-switching language; repeatable; accepts
                           the same shortcut/full-code formats as --lang

Vocabulary (optional, repeatable):
  --custom-vocabulary TERM
  --custom-vocabulary-file FILE
                           UTF-8, one phrase per line; blanks/# comments ignored

Vocabulary is merged/deduplicated, limited by Gemini to 1000 final entries,
and incompatible with timestamps/diarization. Use --timestamps off.

Forwarded Gemini options:
  --stt-config FILE
  --model MODEL
  --mode verbatim|smart
  --timestamps on|off
  --diarization provider|off
  --resume on|off
  --cache-dir DIR

Invalid provider option combinations are rejected before file preflight.

Batch and pipeline options:
  --all                  Scan current directory, not recursively
  --outdir DIR           Markdown output directory
  --srtoutdir DIR        Final TXT/SRT directory
  --context-file FILE    Extra cleanup context; repeatable
  --overwrite            Replace outputs and bypass checkpoints
  --quiet|--error|--info|--debug|--trace

Every selected file is checked before the first Gemini upload. A provider-wide
auth/retry failure aborts the remaining batch; an ordinary file failure does not.

Examples:
  ./${0##*/} --lang uk file1.mp4 file2.m4a
  ./${0##*/} --lang uk-UA --additional-lang de-DE --all
  ./${0##*/} --lang uk --additional-lang de --additional-lang en --all
  ./${0##*/} --lang uk --additional-lang de --timestamps off \
      --custom-vocabulary-file ./terms.txt lesson1.mp4 lesson2.mp4
EOF
    lecture_cleanup_print_forwarded_help
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

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
        --all) ALL_MODE=1; shift ;;
        --outdir) need_value "$1" "${2:-}"; OUTDIR="$2"; shift 2 ;;
        --srtoutdir) need_value "$1" "${2:-}"; SRT_OUTDIR="$2"; shift 2 ;;
        --context-file) need_value "$1" "${2:-}"; CONTEXT_FILES+=("$2"); shift 2 ;;
        --overwrite) OVERWRITE=1; shift ;;
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
        *) INPUT_FILES+=("$1"); shift ;;
    esac
done

gemini_apply_early_log_level
[[ -n "$LANG" ]] || { echo "Error: --lang is required." >&2; print_help; exit 2; }
[[ "${LANG,,}" != "auto" ]] || { echo "Error: --lang auto is not allowed in workflows." >&2; exit 2; }
[[ "$ALL_MODE" -eq 0 || ${#INPUT_FILES[@]} -eq 0 ]] || { echo "Error: --all cannot be combined with explicit files." >&2; exit 2; }
[[ "$ALL_MODE" -eq 1 || ${#INPUT_FILES[@]} -gt 0 ]] || { echo "Error: provide files or use --all." >&2; print_help; exit 2; }
for file in "${CONTEXT_FILES[@]}" "${CUSTOM_VOCABULARY_FILES[@]}"; do
    [[ -f "$file" ]] || { echo "Error: referenced file not found: $file" >&2; exit 2; }
done
[[ -x "$CHILD_SCRIPT" ]] || { echo "Error: child script missing or not executable: $CHILD_SCRIPT" >&2; exit 2; }

gemini_init || exit $?
gemini_resolve_log_level || exit $?
gemini_validate_options || exit $?

if [[ "$ALL_MODE" -eq 1 ]]; then
    shopt -s nullglob
    for path in "$PWD"/*; do
        [[ -f "$path" && "$path" == *.* ]] || continue
        ext="${path##*.}"
        if gemini_is_known_audio_extension "$ext" || gemini_is_known_video_extension "$ext"; then
            INPUT_FILES+=("$path")
        fi
    done
    shopt -u nullglob
fi
[[ ${#INPUT_FILES[@]} -gt 0 ]] || { echo "Error: no known media files selected." >&2; exit 3; }
for path in "${INPUT_FILES[@]}"; do
    [[ -f "$path" ]] || { echo "Error: file not found: $path" >&2; exit 3; }
done

CHILD_FLAGS=("${LECTURE_CLEANUP_FLAGS[@]}" --lang "$LANG")
for value in "${ADDITIONAL_LANGS[@]}"; do CHILD_FLAGS+=(--additional-lang "$value"); done
for value in "${CUSTOM_VOCABULARY[@]}"; do CHILD_FLAGS+=(--custom-vocabulary "$value"); done
for value in "${CUSTOM_VOCABULARY_FILES[@]}"; do CHILD_FLAGS+=(--custom-vocabulary-file "$value"); done
[[ -n "$STT_CONFIG" ]] && CHILD_FLAGS+=(--stt-config "$STT_CONFIG")
[[ -n "$GEMINI_MODEL" ]] && CHILD_FLAGS+=(--model "$GEMINI_MODEL")
[[ -n "$GEMINI_MODE" ]] && CHILD_FLAGS+=(--mode "$GEMINI_MODE")
[[ -n "$GEMINI_TIMESTAMPS" ]] && CHILD_FLAGS+=(--timestamps "$GEMINI_TIMESTAMPS")
[[ -n "$GEMINI_DIARIZATION" ]] && CHILD_FLAGS+=(--diarization "$GEMINI_DIARIZATION")
[[ -n "$GEMINI_RESUME" ]] && CHILD_FLAGS+=(--resume "$GEMINI_RESUME")
[[ -n "$GEMINI_CACHE_DIR" ]] && CHILD_FLAGS+=(--cache-dir "$GEMINI_CACHE_DIR")
[[ -n "$OUTDIR" ]] && CHILD_FLAGS+=(--outdir "$OUTDIR")
[[ -n "$SRT_OUTDIR" ]] && CHILD_FLAGS+=(--srtoutdir "$SRT_OUTDIR")
[[ "$OVERWRITE" -eq 1 ]] && CHILD_FLAGS+=(--overwrite)
CHILD_FLAGS+=("--$LOG_LEVEL")
for value in "${CONTEXT_FILES[@]}"; do CHILD_FLAGS+=(--context-file "$value"); done

PREFLIGHT_DIR="$(mktemp -d)"
trap 'rm -rf "$PREFLIGHT_DIR"' EXIT
VALID_FILES=()
PRECHECK_FAIL=0
gemini_info "Batch stage 1/2: preflighting ${#INPUT_FILES[@]} file(s)"
for index in "${!INPUT_FILES[@]}"; do
    manifest="$PREFLIGHT_DIR/$index.json"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" --preflight --preflight-output "$manifest" "${INPUT_FILES[$index]}"; then
        VALID_FILES+=("${INPUT_FILES[$index]}")
    else
        rc=$?
        PRECHECK_FAIL=$((PRECHECK_FAIL + 1))
        gemini_warn "Preflight failed: ${INPUT_FILES[$index]}"
        gemini_is_global_failure "$rc" && exit "$rc"
    fi
done
[[ ${#VALID_FILES[@]} -gt 0 ]] || { echo "Error: no files passed preflight." >&2; exit 3; }

SUCCESS=0
FAIL="$PRECHECK_FAIL"
for index in "${!VALID_FILES[@]}"; do
    file="${VALID_FILES[$index]}"
    gemini_info "$((index + 1))/${#VALID_FILES[@]} Processing $file"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" "$file"; then
        SUCCESS=$((SUCCESS + 1))
    else
        rc=$?
        FAIL=$((FAIL + 1))
        gemini_warn "Failed: $file"
        gemini_is_global_failure "$rc" && exit "$rc"
    fi
done
gemini_info "Done. Success: $SUCCESS / ${#INPUT_FILES[@]}; Failed: $FAIL"
gemini_info "Batch stage 2/2 complete"
[[ "$FAIL" -eq 0 ]]
