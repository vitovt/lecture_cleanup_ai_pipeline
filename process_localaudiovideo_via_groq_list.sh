#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
CHILD_SCRIPT="$SCRIPT_DIR/process_localaudiovideo_via_groq.sh"

LANG=""
OUTDIR=""
SRT_OUTDIR=""
ALL_MODE=0
OVERWRITE=0
LOG_LEVEL_OVERRIDE=""
CONTEXT_FILES=()
INPUT_FILES=()
GROQ_CONFIG=""
GROQ_MODEL=""
GROQ_TEMPERATURE=""
GROQ_DIARIZATION=""
GROQ_NUM_SPEAKERS=""
GROQ_OVERSIZE_POLICIES=()
GROQ_SAVE_JSON=""
GROQ_MAX_FILE_COST_USD=""
GROQ_MAX_BATCH_COST_USD=""
GROQ_PROMPT=""
GROQ_ALLOW_UNKNOWN_MODEL=0

# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/groq_shell_common.sh"

print_help() {
    cat <<EOF
Usage: $0 [OPTIONS] [file1 file2 ...]

Preflights and processes multiple local audio/video files through
process_localaudiovideo_via_groq.sh. Explicit files and --all are exclusive.

Input and language:
  --lang CODE|auto       Language for every file; config may allow omitted auto
  --all                  Process known media files in current directory (not recursive)

Forwarded pipeline options:
  --outdir DIR           Markdown output directory
  --srtoutdir DIR        Audio/transcript directory
  --context-file FILE    Extra cleanup context; repeatable
  --overwrite            Replace existing outputs
  --quiet                Print nothing, including errors
  --error                Print errors only
  --info                 Show batch and per-file progress (default)
  --debug                Show verbose diagnostics/request metadata, no payloads
  --trace                Show debug output plus full request/response payloads

If no logging flag is given, logging.level from groq-api/config.yaml is used.

Forwarded Groq options:
  --groq-config FILE     Groq YAML override
  --model MODEL          Groq Whisper model
  --temperature VALUE    Temperature, 0..1
  --prompt TEXT          Whisper prompt/context
  --diarization on|off   Local pyannote speaker labels
  --num-speakers auto|N  Automatic or exact speaker count
  --oversize-policy MODE error|compress|chunk|interactive; repeat for fallbacks
  --save-json on|off     Keep verbose_json artifacts
  --max-file-cost-usd N  Per-file estimated USD cap
  --max-batch-cost-usd N Batch estimated USD cap; negative disables
  --allow-unknown-model  Permit future model slugs

The list wrapper validates every selected file and total estimated cost before
the first Groq request. Provider-wide billing/auth/model failures abort the batch.

Examples:
  $0 --lang ru file1.mp4 file2.mp3 ../file3.m4a
  $0 --lang auto --all --diarization off
  $0 --lang en --all --oversize-policy chunk --max-batch-cost-usd 1.00 --info
  $0 --lang uk --all --oversize-policy compress --oversize-policy chunk
  $0 --lang en --trace problem-file.m4a
EOF
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --lang) need_value "$1" "${2:-}"; LANG="$2"; shift 2 ;;
        --all) ALL_MODE=1; shift ;;
        --outdir) need_value "$1" "${2:-}"; OUTDIR="$2"; shift 2 ;;
        --srtoutdir) need_value "$1" "${2:-}"; SRT_OUTDIR="$2"; shift 2 ;;
        --context-file) need_value "$1" "${2:-}"; CONTEXT_FILES+=("$2"); shift 2 ;;
        --groq-config) need_value "$1" "${2:-}"; GROQ_CONFIG="$2"; shift 2 ;;
        --model) need_value "$1" "${2:-}"; GROQ_MODEL="$2"; shift 2 ;;
        --temperature) need_value "$1" "${2:-}"; GROQ_TEMPERATURE="$2"; shift 2 ;;
        --prompt) need_value "$1" "${2:-}"; GROQ_PROMPT="$2"; shift 2 ;;
        --diarization) need_value "$1" "${2:-}"; GROQ_DIARIZATION="$2"; shift 2 ;;
        --num-speakers) need_value "$1" "${2:-}"; GROQ_NUM_SPEAKERS="$2"; shift 2 ;;
        --oversize-policy) need_value "$1" "${2:-}"; GROQ_OVERSIZE_POLICIES+=("$2"); shift 2 ;;
        --save-json) need_value "$1" "${2:-}"; GROQ_SAVE_JSON="$2"; shift 2 ;;
        --max-file-cost-usd) need_value "$1" "${2:-}"; GROQ_MAX_FILE_COST_USD="$2"; shift 2 ;;
        --max-batch-cost-usd) need_value "$1" "${2:-}"; GROQ_MAX_BATCH_COST_USD="$2"; shift 2 ;;
        --allow-unknown-model) GROQ_ALLOW_UNKNOWN_MODEL=1; shift ;;
        --overwrite) OVERWRITE=1; shift ;;
        --quiet) LOG_LEVEL_OVERRIDE=quiet; shift ;;
        --error) LOG_LEVEL_OVERRIDE=error; shift ;;
        --info) LOG_LEVEL_OVERRIDE=info; shift ;;
        --debug) LOG_LEVEL_OVERRIDE=debug; shift ;;
        --trace) LOG_LEVEL_OVERRIDE=trace; shift ;;
        --*) echo "Error: unknown option '$1'." >&2; print_help; exit 2 ;;
        *) INPUT_FILES+=("$1"); shift ;;
    esac
done
groq_apply_early_quiet

if [[ "$ALL_MODE" -eq 1 && ${#INPUT_FILES[@]} -gt 0 ]]; then
    echo "Error: --all cannot be combined with explicit files." >&2
    exit 2
fi
if [[ "$ALL_MODE" -eq 0 && ${#INPUT_FILES[@]} -eq 0 ]]; then
    echo "Error: provide files or use --all." >&2
    print_help
    exit 2
fi
for ctx in "${CONTEXT_FILES[@]}"; do
    [[ -f "$ctx" ]] || { echo "Error: context file not found: $ctx" >&2; exit 2; }
done

if [[ "$ALL_MODE" -eq 1 ]]; then
    shopt -s nullglob
    for path in "$PWD"/*; do
        [[ -f "$path" ]] || continue
        name="$(basename "$path")"
        [[ "$name" == *.* ]] || continue
        ext="${name##*.}"
        if groq_is_known_audio_extension "$ext" || groq_is_known_video_extension "$ext"; then
            INPUT_FILES+=("$path")
        fi
    done
    shopt -u nullglob
fi
if [[ ${#INPUT_FILES[@]} -eq 0 ]]; then
    echo "Error: no known media files selected." >&2
    exit 3
fi
for path in "${INPUT_FILES[@]}"; do
    [[ -f "$path" ]] || { echo "Error: file not found: $path" >&2; exit 3; }
done
[[ -f "$CHILD_SCRIPT" ]] || { echo "Error: child script not found: $CHILD_SCRIPT" >&2; exit 2; }

groq_init_python || exit 2
groq_resolve_log_level || exit 2
groq_apply_log_level
groq_debug "Effective logging level: $LOG_LEVEL"

CHILD_FLAGS=()
[[ -n "$LANG" ]] && CHILD_FLAGS+=(--lang "$LANG")
[[ -n "$OUTDIR" ]] && CHILD_FLAGS+=(--outdir "$OUTDIR")
[[ -n "$SRT_OUTDIR" ]] && CHILD_FLAGS+=(--srtoutdir "$SRT_OUTDIR")
[[ -n "$GROQ_CONFIG" ]] && CHILD_FLAGS+=(--groq-config "$GROQ_CONFIG")
[[ -n "$GROQ_MODEL" ]] && CHILD_FLAGS+=(--model "$GROQ_MODEL")
[[ -n "$GROQ_TEMPERATURE" ]] && CHILD_FLAGS+=(--temperature "$GROQ_TEMPERATURE")
[[ -n "$GROQ_PROMPT" ]] && CHILD_FLAGS+=(--prompt "$GROQ_PROMPT")
[[ -n "$GROQ_DIARIZATION" ]] && CHILD_FLAGS+=(--diarization "$GROQ_DIARIZATION")
[[ -n "$GROQ_NUM_SPEAKERS" ]] && CHILD_FLAGS+=(--num-speakers "$GROQ_NUM_SPEAKERS")
for policy in "${GROQ_OVERSIZE_POLICIES[@]}"; do
    CHILD_FLAGS+=(--oversize-policy "$policy")
done
[[ -n "$GROQ_SAVE_JSON" ]] && CHILD_FLAGS+=(--save-json "$GROQ_SAVE_JSON")
[[ -n "$GROQ_MAX_FILE_COST_USD" ]] && CHILD_FLAGS+=(--max-file-cost-usd "$GROQ_MAX_FILE_COST_USD")
[[ "$GROQ_ALLOW_UNKNOWN_MODEL" -eq 1 ]] && CHILD_FLAGS+=(--allow-unknown-model)
[[ "$OVERWRITE" -eq 1 ]] && CHILD_FLAGS+=(--overwrite)
CHILD_FLAGS+=("--$LOG_LEVEL")
for ctx in "${CONTEXT_FILES[@]}"; do CHILD_FLAGS+=(--context-file "$ctx"); done

PREFLIGHT_DIR="$(mktemp -d)"
trap 'rm -rf "$PREFLIGHT_DIR"' EXIT
VALID_FILES=()
PREFLIGHT_FILES=()
PRECHECK_FAIL=0

groq_info "Preflighting ${#INPUT_FILES[@]} local media file(s)"
groq_info "Batch stage 1/3: validating formats, sizes, and per-file costs"
for i in "${!INPUT_FILES[@]}"; do
    manifest="$PREFLIGHT_DIR/$i.json"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" --preflight --preflight-output "$manifest" "${INPUT_FILES[$i]}"; then
        VALID_FILES+=("${INPUT_FILES[$i]}")
        PREFLIGHT_FILES+=("$manifest")
    else
        rc=$?
        groq_warn "Preflight failed: ${INPUT_FILES[$i]}"
        PRECHECK_FAIL=$((PRECHECK_FAIL + 1))
        if groq_is_global_failure "$rc"; then
            exit "$rc"
        fi
    fi
done

if [[ ${#VALID_FILES[@]} -eq 0 ]]; then
    echo "Error: no files passed preflight." >&2
    exit 3
fi
groq_check_batch "${PREFLIGHT_FILES[@]}"
rc=$?
[[ "$rc" -eq 0 ]] || exit "$rc"
groq_info "Batch stage 2/3 complete: total estimated cost is within the configured limit"

SUCCESS=0
FAIL="$PRECHECK_FAIL"
TOTAL=${#INPUT_FILES[@]}
for i in "${!VALID_FILES[@]}"; do
    media_file="${VALID_FILES[$i]}"
    groq_info "$((i + 1))/${#VALID_FILES[@]} Processing $media_file"
    "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" "$media_file"
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAIL=$((FAIL + 1))
        groq_warn "Failed: $media_file"
        if groq_is_global_failure "$rc"; then
            echo "[ERROR] Provider-wide/budget failure; aborting remaining files." >&2
            exit "$rc"
        fi
    fi
done

groq_info "Done. Success: $SUCCESS / $TOTAL; Failed: $FAIL"
groq_info "Batch stage 3/3 complete"
[[ "$FAIL" -eq 0 ]]
