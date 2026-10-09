#!/usr/bin/env bash

# Shared lecture_cleanup.sh options accepted by workflow wrappers. Wrapper-owned
# options such as --input, --lang, --outdir, and --context-file stay in each
# script because their values also control transcription/download stages.

LECTURE_CLEANUP_FLAGS=()
LECTURE_CLEANUP_OPTION_SHIFT=0

lecture_cleanup_add_value_option() {
    local option="$1"
    local value="${2:-}"

    if [[ -z "$value" ]]; then
        echo "Error: $option requires a value." >&2
        return 2
    fi
    LECTURE_CLEANUP_FLAGS+=("$option" "$value")
}

lecture_cleanup_add_flag_option() {
    LECTURE_CLEANUP_FLAGS+=("$1")
}

# Parse one cleanup-only option. Return 1 when the option is not part of the
# shared allowlist, or 2 when a recognized option is missing its value.
lecture_cleanup_parse_option() {
    LECTURE_CLEANUP_OPTION_SHIFT=0
    case "$1" in
        --qc-report|--glossary|--txt-chunk-chars|--txt-overlap-chars|--llm-provider|--request-delay|--retry-attempts|--short-summary-output|--long-summary-output|--short-summary-file-suffix|--long-summary-file-suffix|--long-summary-lang|--chunks|--use-context-overlap|--log-level)
            lecture_cleanup_add_value_option "$1" "${2:-}" || return $?
            LECTURE_CLEANUP_OPTION_SHIFT=2
            ;;
        --include-timecodes|--no-include-timecodes|\
        --include-timecodes-below-headings|--no-include-timecodes-below-headings|\
        --include-src-block-ids|--no-include-src-block-ids|\
        --include-txt-block-ids-for-untimed|--no-include-txt-block-ids-for-untimed|\
        --process-timecodes-by-ai|--no-process-timecodes-by-ai|\
        --short-summary|--no-short-summary|--long-summary|--no-long-summary|\
        --long-summary-references|--no-long-summary-references|--trace)
            lecture_cleanup_add_flag_option "$1"
            LECTURE_CLEANUP_OPTION_SHIFT=1
            ;;
        *)
            return 1
            ;;
    esac
}

lecture_cleanup_print_forwarded_help() {
    cat <<'EOF'

Forwarded lecture cleanup options:
  --qc-report MODE              QC report: outdir|default_outdir|off
  --glossary FILE               Glossary terms, one per line
  --txt-chunk-chars N           Override TXT chunk size
  --txt-overlap-chars N         Override TXT overlap size
  --llm-provider NAME           Override the cleanup LLM provider
  --request-delay SECONDS       Delay between cleanup LLM requests
  --retry-attempts N            Maximum cleanup request attempts
  --short-summary               Enable short-summary generation
  --no-short-summary            Disable short-summary generation
  --long-summary                Enable long-summary generation
  --no-long-summary             Disable long-summary generation
  --short-summary-output MODE   Short-summary destination: append|separate
  --long-summary-output MODE    Long-summary destination: append|separate
  --short-summary-file-suffix S Suffix for a separate short-summary file
  --long-summary-file-suffix S  Suffix for a separate long-summary file
  --long-summary-lang LANG      Long-summary language: default or ISO code
  --long-summary-references     Add source links to long-summary sections
  --no-long-summary-references  Disable long-summary source links
  --chunks SPEC                 Process selected cleanup chunks, e.g. 1,3,7-9
  --use-context-overlap MODE    Overlap source: raw|cleaned|none
  --include-timecodes           Append timecodes to headings when available
  --no-include-timecodes        Do not include I timecodes in headings
  --include-timecodes-below-headings
                                Add B camera timecodes below headings
  --no-include-timecodes-below-headings
                                Disable B camera timecodes
  --include-src-block-ids       Add S block IDs from timestamp seconds
  --no-include-src-block-ids    Disable S block IDs
  --include-txt-block-ids-for-untimed
                                Add ^txt-N to headings without timestamps
  --no-include-txt-block-ids-for-untimed
                                Disable fallback ^txt-N IDs
  --process-timecodes-by-ai     Let the LLM process source timestamps
  --no-process-timecodes-by-ai  Disable LLM-side timestamp processing
  --log-level LEVEL             Workflow logging: quiet|error|info|debug|trace
  --trace                       Trace full provider requests/responses (no credentials)

Configured content modes (set content_mode in config.yaml):
  strict | normal | creative | creativedetailed
  creativeeditoral | creativeeditoral_technical

Workflow wrappers prepare a TXT transcript, so cleanup --input is managed
internally; media wrappers also manage --format. Wrapper-specific help above
documents source, language, output, context, overwrite, and debug options.
EOF
}

# Resolve verbosity before parsing/validation so quiet also covers early failures.
# Workflow wrappers call this once; provider tools keep their own configurations.
lecture_workflow_init_logging() {
    local previous="" arg level="" python="$SCRIPT_DIR/.venv/bin/python"
    for arg in "$@"; do
        [[ "$arg" == -- ]] && break
        case "$arg" in -h|--help) return 0 ;; esac
        if [[ "$previous" == --log-level ]]; then
            level="$arg"
        else
            case "$arg" in
                --quiet|--error|--info|--debug|--trace) level="${arg#--}" ;;
                --log-level=*) level="${arg#*=}" ;;
            esac
        fi
        previous="$arg"
    done
    if [[ -z "$level" ]]; then
        [[ -x "$python" ]] || python=python3
        level="$("$python" -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from scripts.config_loader import load_effective_config; print(load_effective_config(Path(sys.argv[1]))[0].get("logging", {}).get("level", "info"))' "$SCRIPT_DIR")" || return 2
    fi
    case "$level" in
        quiet|error|info|debug|trace) ;;
        *) printf '[ERROR] Invalid logging level: %s\n' "$level" >&2; return 2 ;;
    esac
    LOG_LEVEL="$level"
    LOG_LEVEL_OVERRIDE="$level"
    DEBUG=0
    [[ "$level" == debug || "$level" == trace ]] && DEBUG=1
    LECTURE_CLEANUP_FLAGS+=(--log-level "$level")
    # Keep stdout available in command substitutions used for filenames/metadata.
    # Only the outer workflow's human console is redirected.
    if [[ "$level" == quiet ]]; then
        exec >/dev/null 2>/dev/null
    elif [[ "$level" == error ]]; then
        exec >/dev/null
    fi
    return 0
}
