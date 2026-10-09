#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
CHILD_SCRIPT="$SCRIPT_DIR/process_localaudiovideo_via_elevenlabs.sh"

LANG=""
ADDITIONAL_LANGS=()
ELEVENLABS_MULTILINGUAL=0
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
ELEVENLABS_MODEL=""
ELEVENLABS_MODE=""
ELEVENLABS_TIMESTAMPS=""
ELEVENLABS_DIARIZATION=""
ELEVENLABS_RESUME=""
ELEVENLABS_CACHE_DIR=""

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/elevenlabs_shell_common.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/lecture_cleanup_shell_common.sh"

print_help() {
    cat <<EOF
Usage: $0 [OPTIONS] [file1 file2 ...]

Preflights and processes multiple local audio/video files through
process_localaudiovideo_via_elevenlabs.sh. Explicit files and --all are exclusive.

Mandatory:
  --lang CODE           Primary cleanup/transcription language
  file1 ... OR --all    Explicit files, or known media in the current directory

Language format:
  --lang CODE              Required, with a two-letter base: uk/uk-UA,
                           de/de-DE, en/en-US, or ru/ru-RU
  --multilingual           Automatically detect every language in each file;
                           no --additional-lang values are required
  --additional-lang CODE   Extra code-switching language; repeatable; accepts
                           the same shortcut/full-code formats as --lang

With --multilingual or any --additional-lang, Scribe v2 automatically detects
any number of languages. ElevenLabs does not use --additional-lang values as a
restrictive list; they only document expected languages and enable the same
automatic mode. Use --multilingual when the additional languages are unknown.
--lang continues to select cleanup language and filename suffixes.

Keyterms (optional, repeatable):
  --custom-vocabulary TERM  One term or short phrase; repeat for every term
  --custom-vocabulary-file FILE
                            UTF-8, one term/phrase per line; repeatable

The wrapper reads every vocabulary file, merges it with individual terms, and
sends one deduplicated keyterms array to ElevenLabs (maximum: 1000). Each term
must be under 50 characters, contain at most 5 words, and exclude < > { } [ ]
and backslash. Keyterms remain compatible with timestamps and diarization and
add a 20% provider surcharge.

Forwarded ElevenLabs options:
  --stt-config FILE
  --model MODEL
  --mode verbatim|smart
  --timestamps on|off
  --diarization provider|off
  --resume on|off
  --cache-dir DIR

Invalid provider options and keyterm syntax are rejected before file preflight.
With --diarization provider, Scribe labels turns as speaker_0, speaker_1, and so on in
each timestamped TXT and events JSON. These are anonymous labels, not names.

Batch and pipeline options:
  --all                  Scan current directory, not recursively
  --outdir DIR           Markdown output directory
  --srtoutdir DIR        Final TXT/SRT directory
  --context-file FILE    Extra cleanup context; repeatable
  --overwrite            Replace outputs and bypass checkpoints
  --quiet|--error|--info|--debug|--trace

Every selected file is checked before the first ElevenLabs upload. A provider-wide
auth/retry failure aborts the remaining batch; an ordinary file failure does not.

Examples:
  ./${0##*/} --lang uk file1.mp4 file2.m4a
  ./${0##*/} --lang uk --multilingual --all
  ./${0##*/} --lang uk-UA --additional-lang de-DE --all
  ./${0##*/} --lang uk --additional-lang de --additional-lang en --all
  ./${0##*/} --lang uk --multilingual --diarization provider --all
  ./${0##*/} --lang uk --custom-vocabulary-file ./terms.txt --all
EOF
    lecture_cleanup_print_forwarded_help
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

lecture_workflow_init_logging "$@"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --lang) need_value "$1" "${2:-}"; LANG="$2"; shift 2 ;;
        --multilingual) ELEVENLABS_MULTILINGUAL=1; shift ;;
        --additional-lang) need_value "$1" "${2:-}"; ADDITIONAL_LANGS+=("$2"); shift 2 ;;
        --custom-vocabulary) need_value "$1" "${2:-}"; CUSTOM_VOCABULARY+=("$2"); shift 2 ;;
        --custom-vocabulary-file) need_value "$1" "${2:-}"; CUSTOM_VOCABULARY_FILES+=("$2"); shift 2 ;;
        --stt-config) need_value "$1" "${2:-}"; STT_CONFIG="$2"; shift 2 ;;
        --model) need_value "$1" "${2:-}"; ELEVENLABS_MODEL="$2"; shift 2 ;;
        --mode) need_value "$1" "${2:-}"; ELEVENLABS_MODE="$2"; shift 2 ;;
        --timestamps) need_value "$1" "${2:-}"; ELEVENLABS_TIMESTAMPS="$2"; shift 2 ;;
        --diarization) need_value "$1" "${2:-}"; ELEVENLABS_DIARIZATION="$2"; shift 2 ;;
        --resume) need_value "$1" "${2:-}"; ELEVENLABS_RESUME="$2"; shift 2 ;;
        --cache-dir) need_value "$1" "${2:-}"; ELEVENLABS_CACHE_DIR="$2"; shift 2 ;;
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

elevenlabs_apply_early_log_level
[[ -n "$LANG" ]] || { echo "Error: --lang is required." >&2; print_help; exit 2; }
[[ "${LANG,,}" != "auto" ]] || { echo "Error: --lang auto is not allowed in workflows." >&2; exit 2; }
[[ "$ALL_MODE" -eq 0 || ${#INPUT_FILES[@]} -eq 0 ]] || { echo "Error: --all cannot be combined with explicit files." >&2; exit 2; }
[[ "$ALL_MODE" -eq 1 || ${#INPUT_FILES[@]} -gt 0 ]] || { echo "Error: provide files or use --all." >&2; print_help; exit 2; }
for file in "${CONTEXT_FILES[@]}" "${CUSTOM_VOCABULARY_FILES[@]}"; do
    [[ -f "$file" ]] || { echo "Error: referenced file not found: $file" >&2; exit 2; }
done
[[ -x "$CHILD_SCRIPT" ]] || { echo "Error: child script missing or not executable: $CHILD_SCRIPT" >&2; exit 2; }

elevenlabs_init || exit $?
elevenlabs_resolve_log_level || exit $?
elevenlabs_validate_options || exit $?

if [[ "$ALL_MODE" -eq 1 ]]; then
    shopt -s nullglob
    for path in "$PWD"/*; do
        [[ -f "$path" && "$path" == *.* ]] || continue
        ext="${path##*.}"
        if elevenlabs_is_known_audio_extension "$ext" || elevenlabs_is_known_video_extension "$ext"; then
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
[[ "$ELEVENLABS_MULTILINGUAL" -eq 1 ]] && CHILD_FLAGS+=(--multilingual)
for value in "${ADDITIONAL_LANGS[@]}"; do CHILD_FLAGS+=(--additional-lang "$value"); done
for value in "${CUSTOM_VOCABULARY[@]}"; do CHILD_FLAGS+=(--custom-vocabulary "$value"); done
for value in "${CUSTOM_VOCABULARY_FILES[@]}"; do CHILD_FLAGS+=(--custom-vocabulary-file "$value"); done
[[ -n "$STT_CONFIG" ]] && CHILD_FLAGS+=(--stt-config "$STT_CONFIG")
[[ -n "$ELEVENLABS_MODEL" ]] && CHILD_FLAGS+=(--model "$ELEVENLABS_MODEL")
[[ -n "$ELEVENLABS_MODE" ]] && CHILD_FLAGS+=(--mode "$ELEVENLABS_MODE")
[[ -n "$ELEVENLABS_TIMESTAMPS" ]] && CHILD_FLAGS+=(--timestamps "$ELEVENLABS_TIMESTAMPS")
[[ -n "$ELEVENLABS_DIARIZATION" ]] && CHILD_FLAGS+=(--diarization "$ELEVENLABS_DIARIZATION")
[[ -n "$ELEVENLABS_RESUME" ]] && CHILD_FLAGS+=(--resume "$ELEVENLABS_RESUME")
[[ -n "$ELEVENLABS_CACHE_DIR" ]] && CHILD_FLAGS+=(--cache-dir "$ELEVENLABS_CACHE_DIR")
[[ -n "$OUTDIR" ]] && CHILD_FLAGS+=(--outdir "$OUTDIR")
[[ -n "$SRT_OUTDIR" ]] && CHILD_FLAGS+=(--srtoutdir "$SRT_OUTDIR")
[[ "$OVERWRITE" -eq 1 ]] && CHILD_FLAGS+=(--overwrite)
CHILD_FLAGS+=("--$LOG_LEVEL")
for value in "${CONTEXT_FILES[@]}"; do CHILD_FLAGS+=(--context-file "$value"); done

PREFLIGHT_DIR="$(mktemp -d)"
trap 'rm -rf "$PREFLIGHT_DIR"' EXIT
VALID_FILES=()
PRECHECK_FAIL=0
elevenlabs_info "Batch stage 1/2: preflighting ${#INPUT_FILES[@]} file(s)"
for index in "${!INPUT_FILES[@]}"; do
    manifest="$PREFLIGHT_DIR/$index.json"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" --preflight --preflight-output "$manifest" "${INPUT_FILES[$index]}"; then
        VALID_FILES+=("${INPUT_FILES[$index]}")
    else
        rc=$?
        PRECHECK_FAIL=$((PRECHECK_FAIL + 1))
        elevenlabs_warn "Preflight failed: ${INPUT_FILES[$index]}"
        elevenlabs_is_global_failure "$rc" && exit "$rc"
    fi
done
[[ ${#VALID_FILES[@]} -gt 0 ]] || { echo "Error: no files passed preflight." >&2; exit 3; }

SUCCESS=0
FAIL="$PRECHECK_FAIL"
for index in "${!VALID_FILES[@]}"; do
    file="${VALID_FILES[$index]}"
    elevenlabs_info "$((index + 1))/${#VALID_FILES[@]} Processing $file"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" "$file"; then
        SUCCESS=$((SUCCESS + 1))
    else
        rc=$?
        FAIL=$((FAIL + 1))
        elevenlabs_warn "Failed: $file"
        elevenlabs_is_global_failure "$rc" && exit "$rc"
    fi
done
elevenlabs_info "Done. Success: $SUCCESS / ${#INPUT_FILES[@]}; Failed: $FAIL"
elevenlabs_info "Batch stage 2/2 complete"
[[ "$FAIL" -eq 0 ]]
