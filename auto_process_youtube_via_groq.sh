#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autoyoutube-groq"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autoyoutube-groq"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

SRTOUTDIR="${GROQ_YOUTUBE_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
MDOUTDIR="${GROQ_YOUTUBE_MDOUTDIR:-${AUTOYOUTUBE_MDOUTDIR:-$MDOUTDIR_DEFAULT}}"
OUTDIR="$MDOUTDIR"

URL=""
LANG_OVERRIDE=""
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

YOUTUBE_NORMALIZER="$SCRIPT_DIR/subtitle-utils/normalize_youtube_url.py"
SANITIZE_HELPER="$SCRIPT_DIR/subtitle-utils/sanitize_filename.sh"
if [[ -f "$SANITIZE_HELPER" ]]; then
    # shellcheck disable=SC1090
    source "$SANITIZE_HELPER"
else
    sanitize_filename() { printf '%s' "$1"; }
fi

normalize_youtube_url_fallback() {
    local raw="$1"
    local url="$raw"
    [[ "$url" =~ ^https?:// ]] || url="https://$url"
    local id=""
    if [[ "$url" =~ youtu\.be/([^?\&#/]+) ]]; then
        id="${BASH_REMATCH[1]}"
    elif [[ "$url" =~ youtube\.com/(shorts|embed|live|v)/([^?\&#/]+) ]]; then
        id="${BASH_REMATCH[2]}"
    elif [[ "$url" =~ v=([^\&#/]+) ]]; then
        id="${BASH_REMATCH[1]}"
    fi
    [[ -n "$id" ]] || return 1
    printf 'https://youtu.be/%s\n' "$id"
}

normalize_youtube_url() {
    local raw="$1"
    if [[ -f "$YOUTUBE_NORMALIZER" ]]; then
        python3 "$YOUTUBE_NORMALIZER" "$raw" 2>/dev/null && return 0
    fi
    normalize_youtube_url_fallback "$raw"
}

print_help() {
    cat <<EOF
Usage: $0 [OPTIONS] <youtube_url>

Downloads YouTube audio, transcribes it with Groq Whisper, optionally adds
local pyannote speakers, then runs lecture_cleanup.sh.

Language:
  --lang CODE|auto       Override YouTube subtitle-language detection
                         If detection fails, config must permit implicit auto

Pipeline options:
  --outdir DIR           Markdown output directory (resolved default: $OUTDIR)
                         Uses GROQ_YOUTUBE_MDOUTDIR, then AUTOYOUTUBE_MDOUTDIR
                         from the root .env, then the Groq project default
  --srtoutdir DIR        Audio/transcript directory (default: $SRTOUTDIR)
  --context-file FILE    Extra cleanup context; repeatable
  --overwrite            Redownload/reprocess existing outputs
  --quiet                Print nothing, including errors
  --error                Print errors only
  --info                 Show download/transcription/cleanup progress (default)
  --debug                Show verbose diagnostics/request metadata, no payloads
  --trace                Show debug output plus full request/response payloads

If no logging flag is given, logging.level from groq-api/config.yaml is used.

Groq options:
  --groq-config FILE     Groq YAML override
  --model MODEL          Groq Whisper model
  --temperature VALUE    Temperature, 0..1
  --prompt TEXT          Whisper context prompt
  --diarization on|off   Local pyannote speaker labels
  --num-speakers auto|N  Automatic or exact speaker count
  --oversize-policy MODE error|compress|chunk|interactive; repeat for fallbacks
  --save-json on|off     Keep verbose_json response
  --max-file-cost-usd N  Estimated per-file USD cap
  --allow-unknown-model  Permit future model slugs

Preflight:
  --preflight            Download/reuse audio and validate without uploading
  --preflight-output FILE  Write machine-readable preflight JSON

Examples:
  $0 "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  $0 --lang uk --diarization off "https://youtu.be/dQw4w9WgXcQ"
  $0 --lang auto --num-speakers 3 --oversize-policy chunk --info "https://youtu.be/dQw4w9WgXcQ"
  $0 --lang uk --oversize-policy compress --oversize-policy chunk "https://youtu.be/dQw4w9WgXcQ"
  $0 --lang en --trace "https://youtu.be/dQw4w9WgXcQ"
EOF
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --lang) need_value "$1" "${2:-}"; LANG_OVERRIDE="$2"; shift 2 ;;
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
            [[ -z "$URL" ]] || { echo "Error: unexpected argument '$1'." >&2; exit 2; }
            URL="$1"
            shift
            ;;
    esac
done
groq_apply_early_quiet

[[ -n "$URL" ]] || { echo "Error: no YouTube URL provided." >&2; print_help; exit 2; }
[[ -z "$PREFLIGHT_OUTPUT" || "$PREFLIGHT" -eq 1 ]] || { echo "Error: --preflight-output requires --preflight." >&2; exit 2; }
for ctx in "${CONTEXT_FILES[@]}"; do
    [[ -f "$ctx" ]] || { echo "Error: context file not found: $ctx" >&2; exit 2; }
done
command -v yt-dlp >/dev/null 2>&1 || { echo "Error: yt-dlp is required." >&2; exit 2; }
groq_init_python || exit 2
groq_resolve_log_level || exit 2
groq_apply_log_level
groq_build_cli_flags
groq_debug "Effective logging level: $LOG_LEVEL"
groq_info "Stage 1/5: normalizing URL and reading YouTube metadata"

RAW_URL="$URL"
URL="$(normalize_youtube_url "$RAW_URL")" || { echo "Error: invalid YouTube URL: $RAW_URL" >&2; exit 2; }
groq_info "Normalized URL: $URL"

YT_DLP_FLAGS=()
(( $(groq_log_rank "$LOG_LEVEL") >= 3 )) || YT_DLP_FLAGS+=(--quiet --no-warnings)
LANG="$LANG_OVERRIDE"
AUTO_LANG=""
if [[ -z "$LANG" ]]; then
    groq_info "Detecting YouTube subtitle language"
    SUB_INFO="$(yt-dlp "${YT_DLP_FLAGS[@]}" --list-subs "$URL" || true)"
    AUTO_LANG="$(printf '%s\n' "$SUB_INFO" | awk '/\(Original\)/ {print $1; exit}')"
    if [[ -n "$AUTO_LANG" ]]; then
        LANG="${AUTO_LANG%-orig}"
        LANG="${LANG%%-*}"
        groq_info "Detected language: $LANG"
        groq_info "YouTube language detection complete: $LANG"
    else
        groq_warn "YouTube subtitle language unavailable; Groq config must allow implicit auto or pass --lang."
    fi
fi

YT_META="$(yt-dlp "${YT_DLP_FLAGS[@]}" --print '%(upload_date)s' --print filename --skip-download --extractor-args 'youtube:player_client=default' "$URL")" || exit 3
UPLOAD_DATE_RAW="$(printf '%s\n' "$YT_META" | awk '/^[0-9]{8}$/ {print; exit}')"
YOUTUBE_UPLOAD_DATE="$UPLOAD_DATE_RAW"
if [[ "$UPLOAD_DATE_RAW" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})$ ]]; then
    YOUTUBE_UPLOAD_DATE="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]}"
fi
filename="$(printf '%s\n' "$YT_META" | tail -n 1)"
base_raw="${filename%.*}"
base="$(sanitize_filename "$base_raw")"

mkdir -p "$SRTOUTDIR" "$OUTDIR"
MP3_PATH="$SRTOUTDIR/${base}.mp3"
groq_info "Stage 2/5: downloading or reusing YouTube audio"
if [[ ! -f "$MP3_PATH" || "$OVERWRITE" -eq 1 ]]; then
    DOWNLOAD_FLAGS=(--extract-audio --audio-format mp3 --no-progress --extractor-args 'youtube:player_client=default')
    [[ "$OVERWRITE" -eq 1 ]] && DOWNLOAD_FLAGS+=(--force-overwrites)
    yt-dlp "${YT_DLP_FLAGS[@]}" "${DOWNLOAD_FLAGS[@]}" -o "$SRTOUTDIR/${base}.%(ext)s" "$URL" || exit 3
else
    groq_info "Reusing downloaded audio: $MP3_PATH"
fi
[[ -f "$MP3_PATH" ]] || { echo "Error: downloaded MP3 not found: $MP3_PATH" >&2; exit 3; }
groq_info "YouTube audio ready: $MP3_PATH"

if [[ "$PREFLIGHT" -eq 1 ]]; then
    groq_info "Stage 3/5: running Groq preflight"
    TEMP_PREFLIGHT=0
    if [[ -z "$PREFLIGHT_OUTPUT" ]]; then PREFLIGHT_OUTPUT="$(mktemp)"; TEMP_PREFLIGHT=1; fi
    groq_preflight "$MP3_PATH" "$PREFLIGHT_OUTPUT" "$LANG"
    rc=$?
    if [[ "$rc" -eq 0 && "$TEMP_PREFLIGHT" -eq 1 ]]; then
        "$GROQ_PYTHON" -m json.tool "$PREFLIGHT_OUTPUT"
    fi
    [[ "$TEMP_PREFLIGHT" -eq 1 ]] && rm -f "$PREFLIGHT_OUTPUT"
    exit "$rc"
fi

LANG_LABEL="${LANG:-auto}"
if [[ "$LANG_LABEL" != "auto" ]]; then
    TXT_FILE="${base}.${LANG_LABEL}.txt"
    TXT_PATH="$SRTOUTDIR/$TXT_FILE"
    OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"
    if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
        groq_warn "Output exists, skipping: $OUT_MD (use --overwrite)"
        exit 0
    fi
fi

METADATA_FILE="$(mktemp)"
TMP_CTX=""
trap 'rm -f "$METADATA_FILE" "${TMP_CTX:-}"' EXIT
MODEL_USED="${GROQ_MODEL:-whisper-large-v3}"
REUSE_TXT=""
[[ "$LANG_LABEL" != "auto" ]] && REUSE_TXT="$SRTOUTDIR/${base}.${LANG_LABEL}.txt"
if [[ -n "$REUSE_TXT" && -f "$REUSE_TXT" && "$OVERWRITE" -ne 1 ]]; then
    groq_info "Reusing existing transcript: $REUSE_TXT"
    RAW_TXT_PATH="$REUSE_TXT"
    RAW_JSON_PATH="$SRTOUTDIR/${base}.${LANG_LABEL}.json"
else
    groq_info "Stage 3/5: transcribing audio and detecting speakers"
    groq_transcribe "$MP3_PATH" "$SRTOUTDIR" "$METADATA_FILE" "$LANG"
    rc=$?
    [[ "$rc" -eq 0 ]] || exit "$rc"
    RAW_TXT_PATH="$(groq_json_field "$METADATA_FILE" transcript_file)"
    RAW_JSON_PATH="$(groq_json_field "$METADATA_FILE" verbose_json_file)"
    DETECTED_LANG="$(groq_json_field "$METADATA_FILE" detected_language)"
    MODEL_USED="$(groq_json_field "$METADATA_FILE" model)"
    [[ "$LANG_LABEL" == "auto" ]] && LANG_LABEL="${DETECTED_LANG,,}"
fi
[[ "$LANG_LABEL" =~ ^[a-z]{2}$ ]] || { echo "Error: unusable detected language '$LANG_LABEL'." >&2; exit 3; }

TXT_FILE="${base}.${LANG_LABEL}.txt"
TXT_PATH="$SRTOUTDIR/$TXT_FILE"
[[ -n "$RAW_TXT_PATH" && -f "$RAW_TXT_PATH" ]] || { echo "Error: Groq transcript not found: $RAW_TXT_PATH" >&2; exit 3; }
[[ "$RAW_TXT_PATH" == "$TXT_PATH" ]] || mv -f "$RAW_TXT_PATH" "$TXT_PATH"
if [[ -n "$RAW_JSON_PATH" && -f "$RAW_JSON_PATH" ]]; then
    JSON_PATH="$SRTOUTDIR/${base}.${LANG_LABEL}.json"
    [[ "$RAW_JSON_PATH" == "$JSON_PATH" ]] || mv -f "$RAW_JSON_PATH" "$JSON_PATH"
fi

OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"
TEMPLATE_CTX="$SCRIPT_DIR/prompts/custom_context_general/youtube-url-timecodes.txt"
TMP_CTX="$(mktemp)"
ESCAPED_URL="$(printf '%s' "$URL" | sed 's/[&|]/\\&/g')"
sed "s|https://www.youtube.com/watch?v=dQw4w9WgXcQ|$ESCAPED_URL|g" "$TEMPLATE_CTX" > "$TMP_CTX"
LECTURE_LOG_FLAG=()
LECTURE_LOG_FLAG+=(--log-level "$LOG_LEVEL")

groq_info "Stage 4/5: cleaning transcript with the lecture pipeline"
"$SCRIPT_DIR/lecture_cleanup.sh" \
    --input "$TXT_PATH" \
    --lang="$LANG_LABEL" \
    --outdir "$OUTDIR" \
    --context-file "$TMP_CTX" \
    --context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt" \
    "${CONTEXT_FLAGS[@]}" \
    "${LECTURE_LOG_FLAG[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$base_raw"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'url: %s\n' "$URL"
        printf 'youtube_upload_date: "%s"\n' "$YOUTUBE_UPLOAD_DATE"
        printf 'transcription_source: %s\n' "groq"
        printf 'transcription_date: %s\n' "$(date '+%Y-%m-%d_%H-%M')"
        printf 'language: %s\n' "$LANG_LABEL"
        printf 'model: %s\n' "$MODEL_USED"
        printf '%s\n\n' '---'
        printf '# %s\n' "$base_raw"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    groq_info "Output: $OUT_MD"
    groq_info "Stage 5/5 complete: Markdown output written"
else
    echo "Error: Markdown output not found: $OUT_MD" >&2
    exit 3
fi
