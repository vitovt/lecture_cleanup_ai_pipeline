#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
SRTOUTDIR_DEFAULT="$SCRIPT_DIR/input/autoyoutube-elevenlabs"
MDOUTDIR_DEFAULT="$SCRIPT_DIR/output/autoyoutube-elevenlabs"

if [[ -f "$SCRIPT_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
fi

SRTOUTDIR="${ELEVENLABS_YOUTUBE_SRTOUTDIR:-$SRTOUTDIR_DEFAULT}"
OUTDIR="${ELEVENLABS_YOUTUBE_MDOUTDIR:-${AUTOYOUTUBE_MDOUTDIR:-$MDOUTDIR_DEFAULT}}"
URL=""
LANG=""
ADDITIONAL_LANGS=()
ELEVENLABS_MULTILINGUAL=0
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
CONTEXT_FLAGS=()
CONTEXT_FILES=()
LOG_LEVEL_OVERRIDE=""
OVERWRITE=0
PREFLIGHT=0
PREFLIGHT_OUTPUT=""
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

YOUTUBE_NORMALIZER="$SCRIPT_DIR/subtitle-utils/normalize_youtube_url.py"
SANITIZE_HELPER="$SCRIPT_DIR/subtitle-utils/sanitize_filename.sh"
if [[ -f "$SANITIZE_HELPER" ]]; then
    # shellcheck disable=SC1090
    source "$SANITIZE_HELPER"
else
    sanitize_filename() { printf '%s' "$1"; }
fi

normalize_youtube_url() {
    python3 "$YOUTUBE_NORMALIZER" "$1" 2>/dev/null
}

print_help() {
    cat <<EOF
Usage: $0 [OPTIONS] <youtube_url>

Downloads one YouTube video's audio, transcribes it with ElevenLabs Scribe v2
with multilingual code-switching, then runs lecture_cleanup.sh.

Mandatory:
  <youtube_url>          YouTube watch, youtu.be, Shorts, live, or embed URL
  --lang CODE           Primary language for cleanup and output filenames

Language format:
  --lang CODE              Required, with a two-letter base language. Accepts
                           uk or uk-UA, de or de-DE, en or en-US, ru or ru-RU
  --multilingual           Automatically detect every language in the audio;
                           no --additional-lang values are required
  --additional-lang CODE   Additional spoken language; repeatable

With only --lang, its base ISO code is sent as the Scribe language hint. If any
--additional-lang is present, or if --multilingual is used, the single-language
hint is omitted and Scribe v2 automatically detects any number of languages.
ElevenLabs does not receive --additional-lang values as a restrictive list;
they only document expected languages and enable the same automatic mode.
Therefore use --multilingual when the additional languages are unknown.
--lang remains mandatory because it controls cleanup and the filename suffix:
--lang uk-UA writes .uk.txt/.uk.md.

Keyterms (optional, repeatable):
  --custom-vocabulary TERM  One domain term or short phrase; repeat the option
                            for every term you want to provide
  --custom-vocabulary-file FILE
                            UTF-8, one term per line; repeatable

The wrapper reads every vocabulary file, merges it with individual terms,
deduplicates the result, and sends one keyterms array to ElevenLabs. ElevenLabs
permits at most 1000 keyterms; each must be under 50 characters, contain at most
5 words, and must not contain < > { } [ ] or backslash. Keyterms add a 20%
provider surcharge and are compatible with timestamps and diarization.

ElevenLabs transcription options:
  --stt-config FILE       Override stt-api/config.yaml
  --model MODEL           Default: scribe_v2
  --mode verbatim|smart   smart maps to no_verbatim and removes disfluencies
  --timestamps on|off     Word timestamps; default from config is on
  --diarization on|off    ElevenLabs speaker labels; default off
  --resume on|off         Reuse matching chunk checkpoints; default on
  --cache-dir DIR         Checkpoint directory

Scribe v2 accepts keyterms, word timestamps, diarization, and smart mode in the
same request. Invalid keyterm syntax is rejected before YouTube download.
With --diarization on, Scribe labels turns as speaker_0, speaker_1, and so on in
the timestamped TXT and events JSON. These are anonymous labels, not names.

Pipeline options:
  --outdir DIR           Markdown directory (default: $OUTDIR)
  --srtoutdir DIR        Download/transcript directory (default: $SRTOUTDIR)
  --context-file FILE    Extra cleanup context; repeatable
  --overwrite            Redownload/reprocess and bypass checkpoints
  --quiet|--error|--info|--debug|--trace

Preflight:
  --preflight            Download/reuse audio and print a split plan; no upload
  --preflight-output FILE
                         Machine-readable JSON; requires --preflight

Examples:
  ./${0##*/} --lang uk 'https://www.youtube.com/watch?v=VIDEO_ID'
  ./${0##*/} --lang uk --multilingual 'https://youtu.be/VIDEO_ID'
  ./${0##*/} --lang uk-UA --additional-lang de-DE 'https://youtu.be/VIDEO_ID'
  ./${0##*/} --lang uk --additional-lang de --additional-lang en \
      'https://youtu.be/VIDEO_ID'
  ./${0##*/} --lang uk --multilingual --diarization on \
      'https://youtu.be/VIDEO_ID'
  ./${0##*/} --lang uk --custom-vocabulary-file ./german-terms.txt \
      'https://youtu.be/VIDEO_ID'
  ./${0##*/} --lang ru-RU --preflight 'https://youtu.be/VIDEO_ID'
EOF
    lecture_cleanup_print_forwarded_help
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

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
            [[ -z "$URL" ]] || { echo "Error: unexpected argument '$1'." >&2; exit 2; }
            URL="$1"
            shift
            ;;
    esac
done

elevenlabs_apply_early_log_level
[[ -n "$URL" ]] || { echo "Error: no YouTube URL provided." >&2; print_help; exit 2; }
[[ -n "$LANG" ]] || { echo "Error: --lang is required." >&2; print_help; exit 2; }
[[ "${LANG,,}" != "auto" ]] || { echo "Error: --lang auto is not allowed in workflows; choose the cleanup language." >&2; exit 2; }
[[ -z "$PREFLIGHT_OUTPUT" || "$PREFLIGHT" -eq 1 ]] || { echo "Error: --preflight-output requires --preflight." >&2; exit 2; }
for file in "${CONTEXT_FILES[@]}" "${CUSTOM_VOCABULARY_FILES[@]}"; do
    [[ -f "$file" ]] || { echo "Error: referenced file not found: $file" >&2; exit 2; }
done
command -v yt-dlp >/dev/null 2>&1 || { echo "Error: yt-dlp is required." >&2; exit 2; }
[[ -f "$YOUTUBE_NORMALIZER" ]] || { echo "Error: URL normalizer not found: $YOUTUBE_NORMALIZER" >&2; exit 2; }

elevenlabs_init || exit $?
elevenlabs_resolve_log_level || exit $?
elevenlabs_validate_options || exit $?
LANG_LABEL="$(elevenlabs_primary_label "$LANG")" || { echo "Error: unusable primary language '$LANG'." >&2; exit 2; }

RAW_URL="$URL"
URL="$(normalize_youtube_url "$RAW_URL")" || { echo "Error: invalid YouTube URL: $RAW_URL" >&2; exit 2; }
elevenlabs_info "Normalized URL: $URL"
YT_DLP_FLAGS=()
(( $(elevenlabs_log_rank "$LOG_LEVEL") >= 3 )) || YT_DLP_FLAGS+=(--quiet --no-warnings)

elevenlabs_info "Stage 1/5: reading YouTube metadata"
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
elevenlabs_info "Stage 2/5: downloading or reusing YouTube audio"
if [[ ! -f "$MP3_PATH" || "$OVERWRITE" -eq 1 ]]; then
    DOWNLOAD_FLAGS=(--extract-audio --audio-format mp3 --no-progress --extractor-args 'youtube:player_client=default')
    [[ "$OVERWRITE" -eq 1 ]] && DOWNLOAD_FLAGS+=(--force-overwrites)
    yt-dlp "${YT_DLP_FLAGS[@]}" "${DOWNLOAD_FLAGS[@]}" -o "$SRTOUTDIR/${base}.%(ext)s" "$URL" || exit 3
fi
[[ -f "$MP3_PATH" ]] || { echo "Error: downloaded MP3 not found: $MP3_PATH" >&2; exit 3; }

if [[ "$PREFLIGHT" -eq 1 ]]; then
    temporary=0
    if [[ -z "$PREFLIGHT_OUTPUT" ]]; then PREFLIGHT_OUTPUT="$(mktemp)"; temporary=1; fi
    elevenlabs_preflight "$MP3_PATH" "$PREFLIGHT_OUTPUT"
    rc=$?
    [[ "$rc" -eq 0 && "$temporary" -eq 1 ]] && "$STT_PYTHON" -m json.tool "$PREFLIGHT_OUTPUT"
    [[ "$temporary" -eq 1 ]] && rm -f "$PREFLIGHT_OUTPUT"
    exit "$rc"
fi

TXT_FILE="${base}.${LANG_LABEL}.txt"
TXT_PATH="$SRTOUTDIR/$TXT_FILE"
OUT_MD="$OUTDIR/${TXT_FILE%.txt}.md"
if [[ -f "$OUT_MD" && "$OVERWRITE" -ne 1 ]]; then
    elevenlabs_warn "Output exists, skipping: $OUT_MD (use --overwrite)"
    exit 0
fi

METADATA_FILE="$SRTOUTDIR/${base}.${LANG_LABEL}.metadata.json"
TMP_CTX=""
trap 'rm -f "${TMP_CTX:-}"' EXIT
elevenlabs_info "Stage 3/5: transcribing with ElevenLabs"
elevenlabs_transcribe "$MP3_PATH" "$SRTOUTDIR" "$METADATA_FILE" "${base}.${LANG_LABEL}" >/dev/null
rc=$?
[[ "$rc" -eq 0 ]] || exit "$rc"
RAW_TXT_PATH="$(elevenlabs_json_field "$METADATA_FILE" transcript_file)"
MODEL_USED="$(elevenlabs_json_field "$METADATA_FILE" model)"
[[ -n "$RAW_TXT_PATH" && -f "$RAW_TXT_PATH" ]] || { echo "Error: ElevenLabs transcript not found: $RAW_TXT_PATH" >&2; exit 3; }
[[ "$RAW_TXT_PATH" == "$TXT_PATH" ]] || mv -f "$RAW_TXT_PATH" "$TXT_PATH"

CLEANUP_CONTEXTS=(--context-file "$SCRIPT_DIR/prompts/custom_context_general/lection-monolog-with-questions.txt")
if [[ "$ELEVENLABS_EFFECTIVE_TIMESTAMPS" == "on" ]]; then
    TEMPLATE_CTX="$SCRIPT_DIR/prompts/custom_context_general/youtube-url-timecodes.txt"
    TMP_CTX="$(mktemp)"
    ESCAPED_URL="$(printf '%s' "$URL" | sed 's/[&|]/\\&/g')"
    sed "s|https://youtu.be/dQw4w9WgXcQ|$ESCAPED_URL|g" "$TEMPLATE_CTX" > "$TMP_CTX"
    CLEANUP_CONTEXTS=(--context-file "$TMP_CTX" "${CLEANUP_CONTEXTS[@]}")
fi

elevenlabs_info "Stage 4/5: cleaning transcript with the lecture pipeline"
"$SCRIPT_DIR/lecture_cleanup.sh" \
    --input "$TXT_PATH" \
    --lang="$LANG_LABEL" \
    --outdir "$OUTDIR" \
    "${CLEANUP_CONTEXTS[@]}" \
    "${CONTEXT_FLAGS[@]}" \
    --log-level "$LOG_LEVEL" \
    "${LECTURE_CLEANUP_FLAGS[@]}"

if [[ -f "$OUT_MD" ]]; then
    tmp_md="$(mktemp)"
    languages="$LANG"
    for value in "${ADDITIONAL_LANGS[@]}"; do languages+=",$value"; done
    {
        printf '%s\n' '---'
        printf 'title: %s\n' "$base_raw"
        printf 'filename: %s\n' "$TXT_FILE"
        printf 'url: %s\n' "$URL"
        printf 'youtube_upload_date: "%s"\n' "$YOUTUBE_UPLOAD_DATE"
        printf 'transcription_source: elevenlabs\n'
        printf 'transcription_date: %s\n' "$(date '+%Y-%m-%d_%H-%M')"
        printf 'language: %s\n' "$LANG_LABEL"
        printf 'transcription_languages: "%s"\n' "$languages"
        printf 'model: %s\n' "$MODEL_USED"
        printf '%s\n\n' '---'
        printf '# %s\n' "$base_raw"
        cat "$OUT_MD"
    } > "$tmp_md"
    mv "$tmp_md" "$OUT_MD"
    elevenlabs_info "Output: $OUT_MD"
    elevenlabs_info "Stage 5/5 complete"
else
    echo "Error: Markdown output not found: $OUT_MD" >&2
    exit 3
fi
