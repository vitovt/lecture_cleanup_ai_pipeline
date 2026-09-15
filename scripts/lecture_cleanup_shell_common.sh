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
        --qc-report|--glossary|--txt-chunk-chars|--txt-overlap-chars|--llm-provider|--request-delay|--retry-attempts|--summary-mode|--summary-output|--long-summary-lang|--chunks|--use-context-overlap|--log-level)
            lecture_cleanup_add_value_option "$1" "${2:-}" || return $?
            LECTURE_CLEANUP_OPTION_SHIFT=2
            ;;
        --include-timecodes|--process-timecodes-by-ai|--no-process-timecodes-by-ai|--trace)
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
  --summary-mode MODE           Summaries: disabled|short|long|both
  --summary-output MODE         Summary destination: append|separate
  --long-summary-lang LANG      Long-summary language: default or ISO code
  --chunks SPEC                 Process selected cleanup chunks, e.g. 1,3,7-9
  --use-context-overlap MODE    Overlap source: raw|cleaned|none
  --include-timecodes           Append timecodes to headings when available
  --process-timecodes-by-ai     Let the LLM process source timestamps
  --no-process-timecodes-by-ai  Disable LLM-side timestamp processing
  --log-level LEVEL             Cleanup logging: quiet|error|info|debug|trace
  --trace                       Trace full cleanup prompts and responses

Configured content modes (set content_mode in config.yaml):
  strict | normal | creative | creativedetailed
  creativeeditoral | creativeeditoral_technical

Workflow wrappers prepare a TXT transcript, so cleanup --input is managed
internally; media wrappers also manage --format. Wrapper-specific help above
documents source, language, output, context, overwrite, and debug options.
EOF
}
