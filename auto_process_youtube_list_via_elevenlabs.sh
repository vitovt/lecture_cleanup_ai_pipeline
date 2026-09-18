#!/usr/bin/env bash

set -uo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
CHILD_SCRIPT="$SCRIPT_DIR/auto_process_youtube_via_elevenlabs.sh"

PLAYLIST_URL=""
VIDEOS_SPEC=""
LANG=""
ADDITIONAL_LANGS=()
ELEVENLABS_MULTILINGUAL=0
CUSTOM_VOCABULARY=()
CUSTOM_VOCABULARY_FILES=()
CONTEXT_FILES=()
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
Usage: $0 [OPTIONS] <youtube_playlist_url>

Selects playlist items, preflights them, then processes each through
auto_process_youtube_via_elevenlabs.sh.

Mandatory:
  <youtube_playlist_url>  URL containing a list= playlist parameter
  --lang CODE             Primary transcription/cleanup language

Selection and languages:
  --videos SPEC           1-based items: 1-6 | 2,4,6 | 1-3,5,7-9
  --lang CODE             Required, with a two-letter base; shortcuts uk/de/en/ru
                          or full codes uk-UA, de-DE, en-US, ru-RU
  --multilingual          Automatically detect every language in each video;
                          no --additional-lang values are required
  --additional-lang CODE  Additional code-switching language; repeatable;
                          accepts the same formats as --lang

With --multilingual or any --additional-lang, Scribe v2 automatically detects
any number of languages. ElevenLabs does not use --additional-lang values as a
restrictive list; they only document expected languages and enable the same
automatic mode. Use --multilingual when the additional languages are unknown.
--lang continues to control cleanup language and output filenames.

Vocabulary (optional, repeatable):
  --custom-vocabulary TERM
  --custom-vocabulary-file FILE
                          UTF-8, one phrase per line; blanks/# comments ignored

Vocabulary sources are merged/deduplicated (maximum: 1000 entries). Each
keyterm must be shorter than 50 characters, contain no more than 5 words, and
exclude < > { } [ ] and backslash. Keyterms add a 20% provider surcharge and
remain compatible with timestamps and diarization.

Forwarded ElevenLabs options:
  --stt-config FILE
  --model MODEL
  --mode verbatim|smart
  --timestamps on|off
  --diarization on|off
  --resume on|off
  --cache-dir DIR

Invalid provider options and keyterms are rejected before playlist download.

Pipeline options:
  --outdir DIR
  --srtoutdir DIR
  --context-file FILE    Repeatable cleanup context
  --overwrite
  --quiet|--error|--info|--debug|--trace

All selected videos are downloaded/reused and preflighted before the first API
upload. Provider-wide authentication/retry failures abort the remaining list.

Examples:
  ./${0##*/} --lang uk 'https://youtube.com/playlist?list=PLAYLIST_ID'
  ./${0##*/} --lang uk --multilingual --videos 1-5 'PLAYLIST_URL'
  ./${0##*/} --lang uk-UA --additional-lang de-DE --videos 1-5 'PLAYLIST_URL'
  ./${0##*/} --lang uk --additional-lang de --additional-lang en \
      --videos 2,4,7 'PLAYLIST_URL'
  ./${0##*/} --lang uk --additional-lang de \
      --custom-vocabulary-file ./terms.txt --videos 1-3 'PLAYLIST_URL'
EOF
    lecture_cleanup_print_forwarded_help
}

need_value() { [[ -n "${2:-}" ]] || { echo "Error: $1 requires a value." >&2; exit 2; }; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) print_help; exit 0 ;;
        --videos) need_value "$1" "${2:-}"; VIDEOS_SPEC="$2"; shift 2 ;;
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
        *)
            [[ -z "$PLAYLIST_URL" ]] || { echo "Error: unexpected argument '$1'." >&2; exit 2; }
            PLAYLIST_URL="$1"
            shift
            ;;
    esac
done

elevenlabs_apply_early_log_level
[[ -n "$PLAYLIST_URL" ]] || { echo "Error: no playlist URL provided." >&2; print_help; exit 2; }
[[ "$PLAYLIST_URL" == *list=* ]] || { echo "Error: URL has no list= parameter." >&2; exit 2; }
[[ -n "$LANG" ]] || { echo "Error: --lang is required." >&2; print_help; exit 2; }
[[ "${LANG,,}" != "auto" ]] || { echo "Error: --lang auto is not allowed in workflows." >&2; exit 2; }
for file in "${CONTEXT_FILES[@]}" "${CUSTOM_VOCABULARY_FILES[@]}"; do
    [[ -f "$file" ]] || { echo "Error: referenced file not found: $file" >&2; exit 2; }
done
command -v yt-dlp >/dev/null 2>&1 || { echo "Error: yt-dlp is required." >&2; exit 2; }
[[ -x "$CHILD_SCRIPT" ]] || { echo "Error: child script missing or not executable: $CHILD_SCRIPT" >&2; exit 2; }

elevenlabs_init || exit $?
elevenlabs_resolve_log_level || exit $?
elevenlabs_validate_options || exit $?

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

YT_DLP_FLAGS=(--flat-playlist --get-id)
(( $(elevenlabs_log_rank "$LOG_LEVEL") >= 3 )) || YT_DLP_FLAGS+=(--quiet --no-warnings)
elevenlabs_info "Batch stage 1/3: reading playlist metadata"
mapfile -t VIDEO_IDS < <(yt-dlp "${YT_DLP_FLAGS[@]}" "$PLAYLIST_URL")
[[ ${#VIDEO_IDS[@]} -gt 0 ]] || { echo "Error: playlist contains no videos." >&2; exit 3; }

declare -A FILTER=()
if [[ -n "$VIDEOS_SPEC" ]]; then
    IFS=',' read -ra PARTS <<< "$VIDEOS_SPEC"
    for raw in "${PARTS[@]}"; do
        part="${raw//[[:space:]]/}"
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            first="${BASH_REMATCH[1]}"; last="${BASH_REMATCH[2]}"
            (( first > last )) && { temp="$first"; first="$last"; last="$temp"; }
            for ((number=first; number<=last; number++)); do FILTER[$number]=1; done
        elif [[ "$part" =~ ^[0-9]+$ && "$part" -gt 0 ]]; then
            FILTER[$part]=1
        else
            echo "Error: invalid --videos item '$part'." >&2
            exit 2
        fi
    done
fi

URLS=()
for index in "${!VIDEO_IDS[@]}"; do
    number=$((index + 1))
    [[ ${#FILTER[@]} -eq 0 || -n "${FILTER[$number]-}" ]] || continue
    URLS+=("https://youtu.be/${VIDEO_IDS[$index]}")
done
[[ ${#URLS[@]} -gt 0 ]] || { echo "Error: no playlist items selected." >&2; exit 3; }

PREFLIGHT_DIR="$(mktemp -d)"
trap 'rm -rf "$PREFLIGHT_DIR"' EXIT
VALID_URLS=()
PRECHECK_FAIL=0
elevenlabs_info "Batch stage 2/3: downloading/reusing and preflighting ${#URLS[@]} video(s)"
for index in "${!URLS[@]}"; do
    manifest="$PREFLIGHT_DIR/$index.json"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" --preflight --preflight-output "$manifest" "${URLS[$index]}"; then
        VALID_URLS+=("${URLS[$index]}")
    else
        rc=$?
        PRECHECK_FAIL=$((PRECHECK_FAIL + 1))
        elevenlabs_warn "Preflight failed: ${URLS[$index]}"
        elevenlabs_is_global_failure "$rc" && exit "$rc"
    fi
done
[[ ${#VALID_URLS[@]} -gt 0 ]] || { echo "Error: no videos passed preflight." >&2; exit 3; }

SUCCESS=0
FAIL="$PRECHECK_FAIL"
for index in "${!VALID_URLS[@]}"; do
    url="${VALID_URLS[$index]}"
    elevenlabs_info "$((index + 1))/${#VALID_URLS[@]} Processing $url"
    if "$CHILD_SCRIPT" "${CHILD_FLAGS[@]}" "$url"; then
        SUCCESS=$((SUCCESS + 1))
    else
        rc=$?
        FAIL=$((FAIL + 1))
        elevenlabs_warn "Failed: $url"
        elevenlabs_is_global_failure "$rc" && exit "$rc"
    fi
done
elevenlabs_info "Done. Success: $SUCCESS / ${#URLS[@]}; Failed: $FAIL"
elevenlabs_info "Batch stage 3/3 complete"
[[ "$FAIL" -eq 0 ]]
