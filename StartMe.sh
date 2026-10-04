#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
PROGRAM="./$(basename "$0")"
TARGET=""
HELP_KIND="delegate"
COLOR_MODE="auto"
COLOR_ENABLED=0
C_RESET=""
C_SECTION=""
C_MODE=""
C_EXAMPLE=""
C_ERROR=""

init_colors() {
    case "$COLOR_MODE" in
        always)
            COLOR_ENABLED=1
            ;;
        never)
            COLOR_ENABLED=0
            ;;
        auto)
            local color_count=0
            if [[ -t 1 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]] \
                && command -v tput >/dev/null 2>&1; then
                color_count="$(tput colors 2>/dev/null || printf '0')"
                if [[ "$color_count" =~ ^[0-9]+$ && "$color_count" -ge 8 ]]; then
                    COLOR_ENABLED=1
                fi
            fi
            ;;
    esac

    if [[ "$COLOR_ENABLED" -eq 1 ]]; then
        C_RESET=$'\033[0m'
        C_SECTION=$'\033[1;36m'
        C_MODE=$'\033[1;32m'
        C_EXAMPLE=$'\033[33m'
        C_ERROR=$'\033[1;31m'
    fi
}

colorize_help() {
    local help_type="${1:-detail}"
    if [[ "$COLOR_ENABLED" -ne 1 ]]; then
        cat
        return
    fi

    awk \
        -v reset="$C_RESET" \
        -v section="$C_SECTION" \
        -v mode_color="$C_MODE" \
        -v example="$C_EXAMPLE" \
        -v help_type="$help_type" '
        function colored(color, text) { return color text reset }
        /^(Usage:.*|usage:.*|Global color options.*:|Typical flow:|More help:|Options:|Examples?:|Description:|Mandatory:|Optional:|Notes:|Input modes.*:|Preflight:|Language:|Language format:|Pipeline options:|Groq options:|Gemini transcription options:|Custom vocabulary.*:|Vocabulary.*:|Batch and pipeline options:|Forwarded pipeline options:|Forwarded lecture cleanup options:|Forwarded Groq options:|Forwarded Gemini options:|Selection and language:|Selection and languages:|Detailed command help:|Commands:)$/ {
            print colored(section, $0); next
        }
        /^(Transcript cleanup|YouTube subtitles.*|SpeechCore transcription.*|Groq transcription.*|Gemini code-switching transcription.*|Multitrack transcription and cleanup|Provider-level tools|Setup and maintenance|Utilities)$/ {
            print colored(section, $0); next
        }
        help_type == "overview" && /^  [a-z][a-z-]*$/ {
            print colored(mode_color, $0); next
        }
        help_type == "overview" && /^    Example:/ {
            print colored(example, $0); next
        }
        help_type == "overview" && /^  \.\/StartMe\.sh/ {
            print colored(example, $0); next
        }
        help_type == "detail" && /^  (-[^ ]|--[^ ])/ {
            print colored(mode_color, $0); next
        }
        /^Example:/ { print colored(section, $0); in_example=1; next }
        in_example && /^  / { print colored(example, $0); next }
        { in_example=0; print }
    '
}

print_error() {
    printf '%sError:%s %s\n' "$C_ERROR" "$C_RESET" "$*" >&2
}

print_overview() {
    cat <<EOF | colorize_help overview
Usage:
  $PROGRAM
  $PROGRAM help
  $PROGRAM help MODE
  $PROGRAM MODE [MODE_ARGUMENTS...]

Global color options (place before help or MODE):
  --color                 Force colors, including redirected output
  --no-color              Disable colors
  --color=auto|always|never
                          Select automatic, forced, or disabled colors

This is the main entry point for the lecture cleanup project. It does not
reimplement any processing workflow: it explains the available modes and then
delegates detailed help or execution to the corresponding project script.

Typical flow:
  1. Choose the source: transcript, YouTube subtitles, YouTube audio, or local media.
  2. Choose a transcription provider when audio must be transcribed: Gemini,
     Groq, or SpeechCore.
  3. Run detailed help: $PROGRAM help MODE
  4. Run the mode:         $PROGRAM MODE [arguments]

Transcript cleanup
  cleanup
    Clean one existing TXT/SRT transcript with the configured LLM pipeline.
    Example: $PROGRAM cleanup --input lecture.txt --lang uk --outdir ./output

  cleanup-list
    Clean every TXT transcript in a directory, with confirmation.
    Example: $PROGRAM cleanup-list --lang uk --indir ./input

YouTube subtitles (no speech-to-text provider)
  youtube-subtitles
    Download available YouTube subtitles and clean them into Markdown.
    Example: $PROGRAM youtube-subtitles "https://youtu.be/VIDEO_ID"

  youtube-subtitles-list
    Process a playlist through the YouTube subtitle workflow.
    Example: $PROGRAM youtube-subtitles-list --videos 1-5 "PLAYLIST_URL"

  youtube-manual
    Clean a subtitle TXT file already downloaded for a YouTube video.
    Example: $PROGRAM youtube-manual --input video.uk.txt --lang uk --url "VIDEO_URL"

SpeechCore transcription and cleanup
  youtube-speechcore
    Download one YouTube video's audio, transcribe with SpeechCore, then clean it.
    Language defaults to auto; use --lang CODE to override it.
    Example: $PROGRAM youtube-speechcore "https://youtu.be/VIDEO_ID"

  youtube-speechcore-list
    Process selected videos from a playlist through SpeechCore.
    Language defaults to auto and is forwarded to every selected video.
    Example: $PROGRAM youtube-speechcore-list --videos 1-3 "PLAYLIST_URL"

  local-speechcore
    Transcribe and clean one local audio/video file through SpeechCore.
    Example: $PROGRAM local-speechcore --lang uk ./meeting.mp4

  local-speechcore-list
    Process explicit local files or every supported file in the current directory.
    Example: $PROGRAM local-speechcore-list --lang uk --all

Groq transcription, optional pyannote speakers, and cleanup
  youtube-groq
    Download and process one YouTube video through Groq Whisper.
    Language defaults to Groq auto-detection; use --lang CODE as a hint.
    Example: $PROGRAM youtube-groq --diarization off "VIDEO_URL"

  youtube-groq-list
    Preflight and process selected playlist videos through Groq.
    Language defaults to auto and is forwarded to every selected video.
    Example: $PROGRAM youtube-groq-list --videos 1-3 "PLAYLIST_URL"

  local-groq
    Process one local audio/video file through Groq, optionally with speakers.
    Example: $PROGRAM local-groq --lang uk --num-speakers 2 ./meeting.m4a

  local-groq-list
    Preflight cost/size and process multiple local files through Groq.
    Example: $PROGRAM local-groq-list --lang uk --all --oversize-policy chunk

Gemini code-switching transcription and cleanup
  youtube-gemini
    Download one YouTube video's audio and transcribe multilingual speech with Gemini.
    --lang is required; add repeatable --additional-lang for code-switching.
    Example: $PROGRAM youtube-gemini --lang uk --additional-lang de "VIDEO_URL"

  youtube-gemini-list
    Process selected playlist videos with the same Gemini language/vocabulary settings.
    Example: $PROGRAM youtube-gemini-list --lang uk --additional-lang de --videos 1-3 "PLAYLIST_URL"

  local-gemini
    Transcribe and clean one local audio/video file with Gemini.
    Example: $PROGRAM local-gemini --lang uk --additional-lang de ./lesson.m4a

  local-gemini-list
    Preflight and process explicit local files or media in the current directory.
    Example: $PROGRAM local-gemini-list --lang uk --additional-lang de --all

ElevenLabs code-switching transcription and cleanup
  youtube-elevenlabs
    Download one YouTube video's audio and transcribe it with Scribe v2.
    --lang is required; add repeatable --additional-lang for code-switching.
    Example: $PROGRAM youtube-elevenlabs --lang uk --additional-lang de "VIDEO_URL"

  youtube-elevenlabs-list
    Process selected playlist videos with the same Scribe language/keyterms.
    Example: $PROGRAM youtube-elevenlabs-list --lang uk --additional-lang de --videos 1-3 "PLAYLIST_URL"

  local-elevenlabs
    Transcribe and clean one local audio/video file with Scribe v2.
    Example: $PROGRAM local-elevenlabs --lang uk --additional-lang de ./lesson.m4a

  local-elevenlabs-list
    Preflight and process explicit local files or media in the current directory.
    Example: $PROGRAM local-elevenlabs-list --lang uk --additional-lang de --all

Multitrack transcription and cleanup
  multitrack
    Transcribe simultaneous audio tracks, merge speakers on one timeline, and clean once.
    Example: $PROGRAM multitrack --manifest ./webinar.yaml

Provider-level tools
  groq-api
    Run the standalone Groq transcribe/preflight or batch-check CLI.
    Example: $PROGRAM groq-api transcribe --input-file audio.mp3 --lang uk

  diarize
    Run local pyannote speaker diarization without transcription or cleanup.
    Example: $PROGRAM diarize --input-file audio.wav --output-json speakers.json

Setup and maintenance
  setup-main
    Create the main cleanup virtualenv and initial local config files once.
    Example: $PROGRAM setup-main

  setup-groq
    Create/update groq-api/.venv and install Groq dependencies.
    Example: $PROGRAM setup-groq --dev

  setup-diarization
    Install pyannote and configure/validate the local Hugging Face token.
    Example: $PROGRAM setup-diarization

  update-main
    Check or update packages in the main project virtualenv.
    Example: $PROGRAM update-main --check

Utilities
  source-timecodes
    Inspect and transform Markdown heading timestamps, camera links, and source IDs.
    Example: $PROGRAM source-timecodes transform ./notes.md --add-src --overwrite

  add-video-url
    Add a YouTube URL to local timestamps in Markdown headings and camera links.
    Example: $PROGRAM add-video-url -u "https://youtu.be/VIDEO_ID" ./notes.md --overwrite

  download-subtitles
    Download auto-generated subtitles for one YouTube URL into the current directory.
    Example: $PROGRAM download-subtitles "https://youtu.be/VIDEO_ID"

  extract-audio
    Extract audio streams from all MP4 files in the current working directory.
    Example: $PROGRAM extract-audio --debug

  docx-to-markdown
    Convert one DOCX file to Markdown with media in ./_resources.
    Example: $PROGRAM docx-to-markdown ./notes.docx

More help:
  $PROGRAM help local-groq
  $PROGRAM help youtube-speechcore
  $PROGRAM help setup-diarization

Run from any directory; project scripts are resolved relative to StartMe.sh.
cleanup resolves file paths from your working directory and supports
CLEANUP_MDOUTDIR in the project's .env. Other modes pass arguments unchanged.
EOF
}

resolve_mode() {
    local mode="$1"
    HELP_KIND="delegate"
    case "$mode" in
        cleanup) TARGET="$SCRIPT_DIR/lecture_cleanup.sh" ;;
        cleanup-list) TARGET="$SCRIPT_DIR/bulk_cleanup.sh" ;;
        youtube-subtitles) TARGET="$SCRIPT_DIR/auto_process_youtube.sh" ;;
        youtube-subtitles-list) TARGET="$SCRIPT_DIR/auto_process_youtube_list.sh" ;;
        youtube-manual) TARGET="$SCRIPT_DIR/manual_process_youtube.sh" ;;
        youtube-speechcore) TARGET="$SCRIPT_DIR/auto_process_youtube_via_speechcore.sh" ;;
        youtube-speechcore-list) TARGET="$SCRIPT_DIR/auto_process_youtube_list_via_speechcore.sh" ;;
        local-speechcore) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_speechcore.sh" ;;
        local-speechcore-list) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_speechcore_list.sh" ;;
        youtube-groq) TARGET="$SCRIPT_DIR/auto_process_youtube_via_groq.sh" ;;
        youtube-groq-list) TARGET="$SCRIPT_DIR/auto_process_youtube_list_via_groq.sh" ;;
        local-groq) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_groq.sh" ;;
        local-groq-list) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_groq_list.sh" ;;
        youtube-gemini) TARGET="$SCRIPT_DIR/auto_process_youtube_via_gemini.sh" ;;
        youtube-gemini-list) TARGET="$SCRIPT_DIR/auto_process_youtube_list_via_gemini.sh" ;;
        local-gemini) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_gemini.sh" ;;
        local-gemini-list) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_gemini_list.sh" ;;
        youtube-elevenlabs) TARGET="$SCRIPT_DIR/auto_process_youtube_via_elevenlabs.sh" ;;
        youtube-elevenlabs-list) TARGET="$SCRIPT_DIR/auto_process_youtube_list_via_elevenlabs.sh" ;;
        local-elevenlabs) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_elevenlabs.sh" ;;
        local-elevenlabs-list) TARGET="$SCRIPT_DIR/process_localaudiovideo_via_elevenlabs_list.sh" ;;
        multitrack) TARGET="$SCRIPT_DIR/process_multitrack.sh" ;;
        groq-api) TARGET="$SCRIPT_DIR/groq-api/groq_api.sh" ;;
        diarize) TARGET="$SCRIPT_DIR/pyannote-diarization/pyannote_diarization.sh" ;;
        setup-main) TARGET="$SCRIPT_DIR/init_once.sh"; HELP_KIND="setup-main" ;;
        setup-groq) TARGET="$SCRIPT_DIR/groq-api/setup_venv.sh" ;;
        setup-diarization) TARGET="$SCRIPT_DIR/pyannote-diarization/setup_venv.sh" ;;
        update-main) TARGET="$SCRIPT_DIR/update_venv_packages.sh" ;;
        source-timecodes) TARGET="$SCRIPT_DIR/subtitle-utils/source_timecodes.py" ;;
        add-video-url) TARGET="$SCRIPT_DIR/subtitle-utils/add_video_url.py" ;;
        download-subtitles) TARGET="$SCRIPT_DIR/subtitle-utils/download_youtube_subtitles.sh"; HELP_KIND="download-subtitles" ;;
        extract-audio) TARGET="$SCRIPT_DIR/subtitle-utils/extract-audio.sh"; HELP_KIND="extract-audio" ;;
        docx-to-markdown) TARGET="$SCRIPT_DIR/subtitle-utils/docx2md.sh"; HELP_KIND="docx-to-markdown" ;;
        *) return 1 ;;
    esac
}

print_custom_help() {
    case "$HELP_KIND" in
        setup-main)
            cat <<EOF | colorize_help detail
Usage: $PROGRAM setup-main

Runs init_once.sh. It creates the main .venv, installs the cleanup pipeline's
Python dependencies, and copies .env_default/config.yaml.example when their
local counterparts do not exist. This mode is intended for first-time setup;
it exits when .venv already exists.
EOF
            ;;
        download-subtitles)
            cat <<EOF | colorize_help detail
Usage: $PROGRAM download-subtitles <youtube_url>

Detects the video's original auto-generated subtitle language, downloads SRT
with yt-dlp, and converts it to the project's timestamped TXT format in the
current working directory.

Example:
  $PROGRAM download-subtitles "https://youtu.be/VIDEO_ID"
EOF
            ;;
        extract-audio)
            cat <<EOF | colorize_help detail
Usage: $PROGRAM extract-audio [--debug]

Scans the current working directory for *.mp4 files and extracts each first
audio stream without re-encoding when possible. Existing outputs are skipped;
AAC/M4A re-encoding is used as a fallback when stream copying fails.

Example:
  cd ./recordings && /path/to/StartMe.sh extract-audio --debug
EOF
            ;;
        docx-to-markdown)
            cat <<EOF | colorize_help detail
Usage: $PROGRAM docx-to-markdown <file.docx>

Converts one DOCX document to Markdown using pandoc and writes extracted media
under ./_resources in the current working directory.

Example:
  $PROGRAM docx-to-markdown ./notes.docx
EOF
            ;;
        *) return 1 ;;
    esac
}

show_mode_help() {
    local mode="$1"
    if ! resolve_mode "$mode"; then
        print_error "unknown mode $(printf '%q' "$mode")."
        printf 'Run %s to list available modes.\n' "$PROGRAM" >&2
        return 2
    fi
    if [[ "$HELP_KIND" != "delegate" ]]; then
        print_custom_help
        return
    fi
    if [[ ! -x "$TARGET" ]]; then
        print_error "mode script is missing or not executable: $TARGET"
        return 2
    fi
    if [[ "$mode" == "cleanup" ]]; then
        {
            "$TARGET" --help
            cat <<'EOF'

StartMe cleanup paths:
  Relative --input, --outdir, --context-file and --glossary paths are resolved
  from the directory where StartMe.sh is invoked. Both --option value and
  --option=value forms are supported.

Markdown output directory:
  --outdir overrides CLEANUP_MDOUTDIR in the project's .env. Without either,
  the default is the project's output directory. Relative CLEANUP_MDOUTDIR
  paths are also resolved from the invocation directory.
  Example .env setting: CLEANUP_MDOUTDIR="$HOME/Desktop/obsidian"
  QC CSV output remains controlled by --qc-report.
EOF
        } | colorize_help detail
    else
        "$TARGET" --help | colorize_help detail
    fi
}

cleanup_absolute_path() {
    case "$1" in
        /*) printf '%s' "$1" ;;
        *) printf '%s/%s' "$PWD" "$1" ;;
    esac
}

cleanup_output_default() (
    # Keep .env assignments isolated from the dispatcher and other modes.
    if [[ -f "$SCRIPT_DIR/.env" ]]; then
        # shellcheck disable=SC1091
        source "$SCRIPT_DIR/.env"
    fi
    printf '%s' "${CLEANUP_MDOUTDIR:-}"
)

prepare_cleanup_args() {
    CLEANUP_ARGS=()
    local has_outdir=0 option value outdir
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --input|--outdir|--context-file|--glossary)
                option="$1"
                if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
                    print_error "$option requires a path."
                    return 2
                fi
                CLEANUP_ARGS+=("$option" "$(cleanup_absolute_path "$2")")
                [[ "$option" != "--outdir" ]] || has_outdir=1
                shift 2
                ;;
            --input=*|--outdir=*|--context-file=*|--glossary=*)
                option="${1%%=*}"
                value="${1#*=}"
                if [[ -z "$value" ]]; then
                    print_error "$option requires a path."
                    return 2
                fi
                CLEANUP_ARGS+=("$option=$(cleanup_absolute_path "$value")")
                [[ "$option" != "--outdir" ]] || has_outdir=1
                shift
                ;;
            *)
                CLEANUP_ARGS+=("$1")
                shift
                ;;
        esac
    done
    if [[ "$has_outdir" -eq 0 ]]; then
        outdir="$(cleanup_output_default)"
        if [[ -n "$outdir" ]]; then
            CLEANUP_ARGS+=(--outdir "$(cleanup_absolute_path "$outdir")")
        fi
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --color)
            COLOR_MODE="always"
            shift
            ;;
        --no-color)
            COLOR_MODE="never"
            shift
            ;;
        --color=auto|--color=always|--color=never)
            COLOR_MODE="${1#--color=}"
            shift
            ;;
        --color=*)
            printf 'Error: --color expects auto, always, or never.\n' >&2
            exit 2
            ;;
        *)
            break
            ;;
    esac
done

init_colors

if [[ $# -eq 0 ]]; then
    print_overview
    exit 0
fi

case "$1" in
    help|-h|--help)
        shift
        if [[ $# -eq 0 ]]; then
            print_overview
        elif [[ $# -eq 1 ]]; then
            show_mode_help "$1"
        else
            print_error "help accepts at most one MODE."
            exit 2
        fi
        exit 0
        ;;
esac

MODE="$1"
shift
if ! resolve_mode "$MODE"; then
    print_error "unknown mode $(printf '%q' "$MODE")."
    printf 'Run %s to list available modes.\n' "$PROGRAM" >&2
    exit 2
fi
if [[ ! -x "$TARGET" ]]; then
    print_error "mode script is missing or not executable: $TARGET"
    exit 2
fi

if [[ "$MODE" == "cleanup" ]]; then
    for argument in "$@"; do
        if [[ "$argument" == "-h" || "$argument" == "--help" ]]; then
            show_mode_help "$MODE"
            exit 0
        fi
    done
    prepare_cleanup_args "$@"
    exec "$TARGET" "${CLEANUP_ARGS[@]}"
fi

exec "$TARGET" "$@"
