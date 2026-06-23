#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
CHILD_SCRIPT="$SCRIPT_DIR/auto_process_youtube_via_groq.sh"

PLAYLIST_URL=""
VIDEOS_SPEC=""
LANG=""
OUTDIR=""
SRT_OUTDIR=""
OVERWRITE=0
LOG_LEVEL_OVERRIDE=""
CONTEXT_FILES=()
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
Usage: $0 [OPTIONS] <youtube_playlist_url>

Expands a YouTube playlist, downloads/preflights every selected video's audio,
checks total estimated cost, then invokes auto_process_youtube_via_groq.sh.

Selection and language:
  --videos SPEC          1-based items: 1-6 | 2,4,6 | 1-3,5,7-9
  --lang CODE|auto       Override per-video YouTube subtitle-language detection

Forwarded pipeline options:
  --outdir DIR           Markdown output directory
  --srtoutdir DIR        Audio/transcript directory
  --context-file FILE    Extra cleanup context; repeatable
  --overwrite            Replace existing outputs
  --quiet                Print nothing, including errors
  --error                Print errors only
  --info                 Show playlist and per-video progress (default)
  --debug                Show verbose diagnostics/request metadata, no payloads
  --trace                Show debug output plus full request/response payloads

If no logging flag is given, logging.level from groq-api/config.yaml is used.

Forwarded Groq options:
  --groq-config FILE     Groq YAML override
  --model MODEL          Groq Whisper model
  --temperature VALUE    Temperature, 0..1
  --prompt TEXT          Whisper prompt/context
  --diarization on|off   Local pyannote speakers
  --num-speakers auto|N  Automatic or exact speaker count
  --oversize-policy MODE error|compress|chunk|interactive; repeat for fallbacks
  --save-json on|off     Keep verbose_json responses
  --max-file-cost-usd N  Per-video estimated USD cap
  --max-batch-cost-usd N Playlist estimated USD cap; negative disables
  --allow-unknown-model  Permit future model slugs

Provider-wide auth, billing, balance, permission, and model failures abort the
remaining playlist. Ordinary per-video failures are counted and processing continues.

Examples:
  $0 "https://www.youtube.com/playlist?list=PL123"
  $0 --lang ru --videos 1-5 --diarization off "https://youtube.com/playlist?list=PL123"
  $0 --videos 2,4,7 --oversize-policy chunk --max-batch-cost-usd 1.00 --info "https://youtube.com/playlist?list=PL123"
  $0 --oversize-policy compress --oversize-policy chunk "https://youtube.com/playlist?list=PL123"
  $0 --videos 1 --trace "https://youtube.com/playlist?list=PL123"
EOF
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --videos) need_value "$1" "${2:-}"; VIDEOS_SPEC="$2"; shift 2 ;;
        --lang) need_value "$1" "${2:-}"; LANG="$2"; shift 2 ;;
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
        *)
            [[ -z "$PLAYLIST_URL" ]] || { echo "Error: unexpected argument '$1'." >&2; exit 2; }
            PLAYLIST_URL="$1"
            shift
            ;;
    esac
done
groq_apply_early_quiet

[[ -n "$PLAYLIST_URL" ]] || { echo "Error: no playlist URL provided." >&2; print_help; exit 2; }
[[ "$PLAYLIST_URL" == *list=* ]] || { echo "Error: URL has no list= parameter." >&2; exit 2; }
for ctx in "${CONTEXT_FILES[@]}"; do
    [[ -f "$ctx" ]] || { echo "Error: context file not found: $ctx" >&2; exit 2; }
done
command -v yt-dlp >/dev/null 2>&1 || { echo "Error: yt-dlp is required." >&2; exit 2; }
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

YT_DLP_FLAGS=(--flat-playlist --get-id)
(( $(groq_log_rank "$LOG_LEVEL") >= 3 )) || YT_DLP_FLAGS+=(--quiet --no-warnings)
groq_info "Fetching playlist items"
groq_info "Batch stage 1/4: reading playlist metadata"
mapfile -t VIDEO_IDS < <(yt-dlp "${YT_DLP_FLAGS[@]}" "$PLAYLIST_URL")
[[ ${#VIDEO_IDS[@]} -gt 0 ]] || { echo "Error: playlist contains no videos." >&2; exit 3; }

declare -A FILTER=()
if [[ -n "$VIDEOS_SPEC" ]]; then
    IFS=',' read -ra PARTS <<< "$VIDEOS_SPEC"
    for raw in "${PARTS[@]}"; do
        part="${raw//[[:space:]]/}"
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            a="${BASH_REMATCH[1]}"; b="${BASH_REMATCH[2]}"
            (( a > b )) && { temp="$a"; a="$b"; b="$temp"; }
            for ((n=a; n<=b; n++)); do FILTER[$n]=1; done
        elif [[ "$part" =~ ^[0-9]+$ ]]; then
            FILTER[$part]=1
        else
            echo "Error: invalid --videos item '$part'." >&2
            exit 2
        fi
    done
fi

URLS=()
for i in "${!VIDEO_IDS[@]}"; do
    idx=$((i + 1))
    [[ ${#FILTER[@]} -eq 0 || -n "${FILTER[$idx]-}" ]] || continue
    URLS+=("https://youtu.be/${VIDEO_IDS[$i]}")
done
[[ ${#URLS[@]} -gt 0 ]] || { echo "Error: no playlist items selected." >&2; exit 3; }

PREFLIGHT_DIR="$(mktemp -d)"
trap 'rm -rf "$PREFLIGHT_DIR"' EXIT
VALID_URLS=()
PREFLIGHT_FILES=()
PRECHECK_FAIL=0
groq_info "Downloading/reusing and preflighting ${#URLS[@]} selected video(s)"
groq_info "Batch stage 2/4: preparing audio and validating limits"
for i in "${!URLS[@]}"; do
    manifest="$PREFLIGHT_DIR/$i.json"
    "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" --preflight --preflight-output "$manifest" "${URLS[$i]}"
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        VALID_URLS+=("${URLS[$i]}")
        PREFLIGHT_FILES+=("$manifest")
    else
        PRECHECK_FAIL=$((PRECHECK_FAIL + 1))
        groq_warn "Preflight failed: ${URLS[$i]}"
        groq_is_global_failure "$rc" && exit "$rc"
    fi
done
[[ ${#VALID_URLS[@]} -gt 0 ]] || { echo "Error: no videos passed preflight." >&2; exit 3; }

groq_check_batch "${PREFLIGHT_FILES[@]}"
rc=$?
[[ "$rc" -eq 0 ]] || exit "$rc"
groq_info "Batch stage 3/4 complete: estimated cost is within the configured limit"

SUCCESS=0
FAIL="$PRECHECK_FAIL"
for i in "${!VALID_URLS[@]}"; do
    url="${VALID_URLS[$i]}"
    groq_info "$((i + 1))/${#VALID_URLS[@]} Processing $url"
    "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" "$url"
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAIL=$((FAIL + 1))
        groq_warn "Failed: $url"
        if groq_is_global_failure "$rc"; then
            echo "[ERROR] Provider-wide/budget failure; aborting playlist." >&2
            exit "$rc"
        fi
    fi
done

groq_info "Done. Success: $SUCCESS / ${#URLS[@]}; Failed: $FAIL"
groq_info "Batch stage 4/4 complete"
[[ "$FAIL" -eq 0 ]]
