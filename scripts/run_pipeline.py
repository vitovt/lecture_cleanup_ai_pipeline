#!/usr/bin/env python3
import os, argparse, yaml, sys, csv, traceback, time, re
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path

from aiadapters.factory import create_llm_adapter
from aiadapters.base import LLMAdapter
from scripts.logging_helper import (
    set_log_level,
    log_debug,
    log_info,
    log_warn,
    log_error,
    log_trace,
    log_trace_block,
)

from scripts.utils import (
    add_timecodes_to_headings,
    similarity_ratio,
    parse_timestamped_txt_lines,
    chunk_text_line_preserving,
    dedup_overlapping_boundary,
    strip_edit_comments,
    extract_merged_terms_map,
    merge_term_maps,
    diff_term_maps,
    serialize_term_hints_json,
    rewrite_merged_terms_comments,
    build_context_overlap,
    strip_all_html_comments,
)

def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def load_list(path: str) -> List[str]:
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(ln)
    return out

def read_config(cfg_path: str) -> dict:
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_env_from_env_file(root: Path) -> bool:
    """Load key=value pairs from a .env file into process environment.

    Supports optional 'export ' prefix. Returns True if at least one key
    from the file was set.
    """
    env_path = root / ".env"
    if not env_path.exists():
        return False
    loaded_any = False
    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("export "):
                    line = line[7:].lstrip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v:
                    os.environ[k] = v
                    loaded_any = True
    except Exception:
        pass
    return loaded_any

def build_user_prompt(lang: str, parasites: List[str], aside_style: str, timecodes_policy: str) -> str:
    # load template
    tmpl_path = Path(__file__).parent.parent / "prompts" / "user_template.md"
    with open(tmpl_path, "r", encoding="utf-8") as f:
        tmpl = f.read()
    return tmpl

def _parse_chunks_spec(spec: str, total: int) -> Optional[set[int]]:
    """Parse a comma/dash-separated chunks spec into a set of 1-based indices.

    Examples:
      '1,3,7' -> {1,3,7}
      '4-7' -> {4,5,6,7}
      '1,2,3,7-9,23' -> {1,2,3,7,8,9,23}

    Out-of-range numbers are ignored. Returns an empty set if nothing valid.
    """
    if not spec:
        return None
    out: set[int] = set()
    for part in str(spec).split(','):
        p = part.strip()
        if not p:
            continue
        if '-' in p:
            try:
                a_str, b_str = p.split('-', 1)
                a = int(a_str)
                b = int(b_str)
            except Exception:
                continue
            if a > b:
                a, b = b, a
            for i in range(a, b + 1):
                if 1 <= i <= total:
                    out.add(i)
        else:
            try:
                i = int(p)
            except Exception:
                continue
            if 1 <= i <= total:
                out.add(i)
    return out

def _extract_retry_after_seconds(msg: str) -> Optional[float]:
    """Best-effort parse of provider-suggested retry-after seconds from error text.
    Supports patterns like 'retry in 17.8s' and 'retry_delay { seconds: 17 }'.
    """
    if not msg:
        return None
    m = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)s", msg, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    m2 = re.search(r"retry_delay\s*\{\s*seconds:\s*([0-9]+)\s*\}", msg, re.IGNORECASE)
    if m2:
        try:
            return float(m2.group(1))
        except Exception:
            return None
    return None

def _build_timecodes_policy_text(include_timecodes: bool, ai_handles: bool, has_timecodes: bool) -> str:
    """
    Build the timecode policy block for the prompt based on settings and input availability.
    """
    base_rules = (
        "- Never add or duplicate timecodes for headings that exist only in CONTEXT.\n"
        "- Do not place timecodes elsewhere."
    )
    if not include_timecodes:
        return "- Timecodes are not requested for this fragment."
    if not has_timecodes:
        return "- No timecodes detected in this fragment."
    if ai_handles:
        return (
            "- Timecodes are present in the FRAGMENT; use them to timestamp every heading you output.\n"
            "- Append the matching timecode at the end of each heading as: — [HH:MM:SS](#t=HH:MM:SS).\n"
            "- Pick the timestamp closest to the heading's content (if multiple, choose the earliest within that span).\n"
            "- Remove raw [HH:MM:SS,mmm] markers from the body text; do not invent timecodes when none apply.\n"
            + base_rules
        )
    return "- Add timecodes only to headings generated from the FRAGMENT itself.\n" + base_rules

def call_llm(
    adapter: LLMAdapter,
    model: str,
    system_prompt: str,
    chunk_text: str,
    lang: str,
    parasites: List[str],
    aside_style: str,
    glossary: List[str],
    timecodes_policy: str,
    temperature: float = 1.0,
    top_p: float = None,
    debug: bool = False,
    trace: bool = False,
    label: str = None,
    context_text: str = "",
    term_hints_text: str = "",
    source_context_text: str = "",
) -> str:
    # fill template
    template = build_user_prompt(lang, parasites, aside_style, timecodes_policy)

    # Map aside style to prompt-friendly label
    aside_map = {
        "italic": "italics (*...*)",
        "italics": "italics (*...*)",
        "blockquote": "blockquote (> ...)",
        "quote": "blockquote (> ...)",
    }
    aside_style_en = aside_map.get(aside_style, "italics (*...*)")

    # Join lists for prompt
    parasites_str = ", ".join(parasites) if parasites else ""
    glossary_str = "—" if not glossary else ", ".join(glossary)

    # Optional per-file source context block to inject right after the generic Context sentence
    if (source_context_text or "").strip():
        source_block = (
            "Source file context (read-only, DO NOT OUTPUT):\n<<<\n" + source_context_text.strip() + "\n>>>\n\n"
        )
    else:
        source_block = ""

    prompt = template.format(
        LANG=lang,
        PARASITES=parasites_str,
        GLOSSARY_OR_DASH=glossary_str,   # << matches EN template
        ASIDE_STYLE=aside_style_en,
        CHUNK_TEXT=chunk_text,
        CONTEXT_TEXT=(context_text or ""),
        TERM_HINTS=(term_hints_text or ""),
        SOURCE_CONTEXT_BLOCK=source_block,
        TIMECODES_POLICY=timecodes_policy,
    )

    # Build request parameters, honoring config temperature/top_p when provided
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    trace_label = f" [{label}]" if label else ""
    if trace:
        log_trace(f"LLM request BEGIN{trace_label}")
        log_trace(f"Model: {model} | temperature: {temperature} | top_p: {top_p}")
        log_trace_block("System prompt", system_prompt)
        log_trace_block("User prompt", prompt)
        log_trace(f"LLM request END{trace_label}")
    out_text = adapter.generate(
        messages,
        model=model,
        temperature=temperature,
        top_p=top_p,
        debug=(debug or trace),
        label=label,
    )
    if trace:
        log_trace(f"LLM response BEGIN{trace_label}")
        log_trace_block("LLM response", out_text)
        log_trace(f"LLM response END{trace_label}")
    return out_text

def call_llm_summary(adapter: LLMAdapter, model: str, full_markdown: str, temperature: float = 1.0, top_p: float = None, debug: bool = False, trace: bool = False, label: str = None) -> str:
    from pathlib import Path
    base = Path(__file__).parent.parent
    summary_system_path = base / "prompts" / "summary_system.md"
    summary_user_path = base / "prompts" / "summary_user.md"
    summary_system_content = summary_system_path.read_text(encoding="utf-8")
    summary_user_content = summary_user_path.read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": summary_system_content},
        {"role": "user", "content": summary_user_content + "\n\n<<<\n" + full_markdown + "\n>>>"},
    ]
    trace_label = f" [{label}]" if label else ""
    if trace:
        log_trace(f"Summary request BEGIN{trace_label}")
        log_trace(f"Model: {model} | temperature: {temperature} | top_p: {top_p}")
        log_trace_block("System prompt (summary)", summary_system_content)
        log_trace_block("User prompt (summary)", summary_user_content)
        log_trace_block("Document (full markdown)", full_markdown)
        log_trace(f"Summary request END{trace_label}")
    out_text = adapter.generate(
        messages,
        model=model,
        temperature=temperature,
        top_p=top_p,
        debug=(debug or trace),
        label=label,
    )
    if trace:
        log_trace(f"Summary response BEGIN{trace_label}")
        log_trace_block("Summary response", out_text)
        log_trace(f"Summary response END{trace_label}")
    return out_text

def main():
    ap = argparse.ArgumentParser(
        description=(
            "Turn long lecture transcripts into clean Markdown with CONTEXT-overlap,\n"
            "mode-specific editing (normal/strict/creative), and stitching dedup."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("--input", required=True, help="Path to .srt or .txt")
    ap.add_argument("--format", choices=["srt", "txt"], help="Force input format (otherwise inferred)")
    ap.add_argument("--outdir", default="output", help="Output directory")
    ap.add_argument("--lang", required=True, choices=["ru", "uk", "en", "de"], help="Language of the lecture")
    ap.add_argument("--glossary", default=None, help="Path to glossary terms (one per line)")
    # effective chunking params
    ap.add_argument("--txt-chunk-chars", type=int, default=None)
    ap.add_argument("--txt-overlap-chars", type=int, default=None)
    ap.add_argument("--debug", action="store_true", help="Enable debug logging (no full prompts/responses)")
    ap.add_argument("--trace", action="store_true", help="Enable trace logging: print full LLM prompts and responses (large, sensitive)")
    ap.add_argument("--llm-provider", default=None, help="Override LLM provider: openai|gemini|dummy|...")
    ap.add_argument("--request-delay", type=float, default=None, help="Delay in seconds between LLM requests (0 = no delay)")
    ap.add_argument("--retry-attempts", type=int, default=None, help="Retry failed LLM requests up to N times (1 = no retry)")
    ap.add_argument("--chunks", type=str, default=None, help="Process only specified chunks, e.g. '1,3,7-9' (1-based indices)")
    ap.add_argument("--use-context-overlap", dest="use_context_overlap", choices=["raw","cleaned","none"], help="Source of overlap: raw ASR tail, cleaned previous tail, or none")
    # Per-input context files (user-level context). Can be passed multiple times; concatenated in order.
    ap.add_argument(
        "--context-file",
        dest="context_files",
        action="append",
        default=None,
        help=(
            "Path to a file with per-input context to inject into the USER prompt right after the generic 'Context'\n"
            "sentence. Can be provided multiple times; blocks are concatenated in the given order."
        ),
    )
    ap.add_argument("--include-timecodes", dest="include_timecodes", action="store_true", default=None, help="Append timecodes to headings when available")
    tc_group = ap.add_mutually_exclusive_group()
    tc_group.add_argument(
        "--process-timecodes-by-ai",
        dest="process_timecodes_by_ai",
        action="store_true",
        default=None,
        help="Let the LLM consume timestamps and add per-heading timecodes itself (TXT with timestamps)",
    )
    tc_group.add_argument(
        "--no-process-timecodes-by-ai",
        dest="process_timecodes_by_ai",
        action="store_false",
        help="Disable LLM-side timecode handling; rely on post-processing instead",
    )
    tc_group.set_defaults(process_timecodes_by_ai=None)
    args = ap.parse_args()

    base = Path(__file__).parent.parent
    cfg = read_config(str(base / "config.yaml"))
    # Resolve logging verbosity from config and CLI
    level = str(cfg["logging"]["level"]).strip().lower()
    if args.debug:
        level = "debug"
    if args.trace:
        level = "trace"

    debug = (level in ("debug", "trace"))
    trace = (level == "trace")
    set_log_level(level)
    if debug:
        log_debug(f"Debug mode: {level}")

    # Load .env (keys for any provider); adapter will validate required ones
    load_env_from_env_file(base)

    # override config
    if args.txt_chunk_chars: cfg["txt_chunk_chars"] = args.txt_chunk_chars
    if args.txt_overlap_chars: cfg["txt_overlap_chars"] = args.txt_overlap_chars
    if args.include_timecodes is not None: cfg["include_timecodes_in_headings"] = bool(args.include_timecodes)
    if args.process_timecodes_by_ai is not None: cfg["process_timecodes_by_ai"] = bool(args.process_timecodes_by_ai)

    lang = args.lang
    # Resolve provider + effective model params with backward compatibility
    def _effective_llm_params(cfg: Dict, provider_override: Optional[str]) -> Dict:
        llm = cfg["llm"]
        provider = provider_override or llm["provider"]
        p_cfg = llm[provider]
        return {
            "model": p_cfg["model"],
            "temperature": p_cfg.get("temperature"),
            "top_p": p_cfg.get("top_p"),
            "provider": provider,
        }
    _llm = _effective_llm_params(cfg, args.llm_provider)
    model = _llm["model"]
    temperature = _llm.get("temperature")
    top_p = _llm.get("top_p")
    # Basic validation to catch missing required model setting
    if not model:
        log_error("Missing model in config under llm.<provider>.model")
        sys.exit(1)
    # Delay between LLM requests (seconds). Config llm.request_delay_seconds; CLI overrides.
    cfg_llm = cfg["llm"]
    request_delay = float(cfg_llm.get("request_delay_seconds", 0.0) or 0.0)
    if args.request_delay is not None:
        request_delay = max(0.0, float(args.request_delay))
    # Retry settings: prefer CLI, else per-provider llm.<provider>.retry.*, else global retry.*
    cfg_retry_global = cfg.get("retry", {})
    provider_name = _llm['provider']
    cfg_retry_provider = cfg_llm.get(provider_name, {}).get("retry", {})
    attempts = int(cfg_retry_provider.get("attempts", cfg_retry_global.get("attempts", 1)) or 1)
    if args.retry_attempts is not None:
        attempts = max(1, int(args.retry_attempts))
    pause_between_attempts = float(cfg_retry_provider.get("pause_seconds", cfg_retry_global.get("pause_seconds", 0.0)) or 0.0)
    include_timecodes = bool(cfg.get("include_timecodes_in_headings", True))
    process_timecodes_by_ai = bool(cfg.get("process_timecodes_by_ai", False))
    aside_style = cfg.get("highlight_asides_style", "italic")
    # Overlap source (assumes validated config)
    overlap_source = str(cfg.get("use_context_overlap", "raw")).lower()
    if args.use_context_overlap:
        overlap_source = args.use_context_overlap
    # sentence delimiters for overlap selection
    sentence_delimiters = str(cfg.get("overlap_sentence_delimiters", ".!?…"))
    stitch_dedup_window = int(cfg.get("stitch_dedup_window_chars", cfg.get("txt_overlap_chars", 500)) or 0)
    content_mode = str(cfg.get("content_mode", "normal")).strip().lower()
    suppress_edit_comments = bool(cfg.get("suppress_edit_comments", True))
    if debug:
        log_debug(f"Settings -> provider={_llm['provider']}, model={model}, temperature={temperature}, top_p={top_p}, lang={lang}, delay={request_delay}s, retries={attempts} x pause {pause_between_attempts}s")
        log_debug(f"Options -> include_timecodes={include_timecodes}, process_timecodes_by_ai={process_timecodes_by_ai}, aside_style={aside_style}")
        log_debug(f"Overlap -> source={overlap_source}, sentence_delimiters={sentence_delimiters!r}, stitch_dedup_window_chars={stitch_dedup_window}")
        log_debug(f"Content mode -> {content_mode}; suppress_edit_comments={suppress_edit_comments}")

    # Load parasites for the language
    parasites_map = cfg.get("parasites", {})
    parasites_path = parasites_map.get(lang)
    parasites = load_list(str(base / parasites_path)) if parasites_path else []
    glossary = load_list(args.glossary) if args.glossary else []

    # Decide format
    in_path = Path(args.input)
    cfg_format = str(cfg.get("format", "")).strip().lower()
    if args.format:
        fmt = args.format
    elif cfg_format in ("srt", "txt"):
        fmt = cfg_format
    else:
        ext = in_path.suffix.lower()
        fmt = "srt" if ext == ".srt" else "txt"
    if debug:
        log_debug(f"Input: {in_path} | format={fmt} | outdir={args.outdir}")

    if not in_path.exists():
        log_error(f"Input file not found: {in_path}")
        sys.exit(1)
    try:
        file_size = in_path.stat().st_size
    except Exception:
        file_size = 0
    if file_size < 150:
        log_error("input text is too small, there is nothing to format in so small text.")
        sys.exit(1)

    # Prepare chunks
    input_text = load_text(str(in_path))
    if not input_text.strip():
        log_error("Input file is empty after trimming whitespace.")
        sys.exit(1)

    src_lines: List[str] = []
    per_line_time: List[Optional[float]] = []
    has_line_timestamps = False
    timecodes_available = False
    timecodes_handled_by_ai = False
    if fmt == "txt":
        parsed_lines = parse_timestamped_txt_lines(input_text, keep_raw=True)
        has_line_timestamps = any(item["time"] is not None for item in parsed_lines)
        timecodes_available = has_line_timestamps
        timecodes_handled_by_ai = bool(include_timecodes and process_timecodes_by_ai and timecodes_available)
        src_lines = [item.get("raw", item["text"]) if timecodes_handled_by_ai else item["text"] for item in parsed_lines]
        per_line_time = [item["time"] for item in parsed_lines]
        if debug:
            log_debug(f"TXT lines: {len(src_lines)} | timestamped={has_line_timestamps} | ai_timecodes={timecodes_handled_by_ai}")
    else:  # srt -> extract text lines only
        for raw in input_text.splitlines():
            ln = raw.strip("\ufeff")
            if not ln:
                src_lines.append("")
                per_line_time.append(None)
                continue
            if ln.isdigit():
                continue
            if "-->" in ln:
                continue
            src_lines.append(ln)
            per_line_time.append(None)
        if debug:
            log_debug(f"SRT content lines (without times): {len(src_lines)}")

    if not any(l.strip() for l in src_lines):
        log_error("Input contains no textual content after preprocessing.")
        sys.exit(1)

    timecodes_policy_text = _build_timecodes_policy_text(include_timecodes, timecodes_handled_by_ai, timecodes_available)

    # Chunk (line-preserving)
    chunks = chunk_text_line_preserving(
        src_lines,
        chunk_chars=cfg.get("txt_chunk_chars", 6500),
        overlap_chars=cfg.get("txt_overlap_chars", 500),
    )

    # For timestamped TXT, set chunk 'start' based on first new line's timestamp
    if fmt == "txt" and has_line_timestamps:
        for ch in chunks:
            start_time = None
            overlap_n = int(ch.get("_overlap_units", 0))
            units = ch.get("_units", [])
            if overlap_n < len(units):
                seq = units[overlap_n:]
            else:
                seq = []
            for u in seq:
                oi = u.get("orig")
                if oi is not None and 0 <= oi < len(per_line_time):
                    t = per_line_time[oi]
                    if t is not None:
                        start_time = t
                        break
            ch["start"] = start_time

    total_chunks = len(chunks)
    log_info(f"Prepared {total_chunks} chunk(s). Starting processing…")
    if debug and total_chunks:
        log_debug(f"First chunk length={len(chunks[0].get('text',''))}; last chunk length={len(chunks[-1].get('text',''))}; count={len(chunks)}")

    # Optional selection of specific chunks to process
    selected_chunks: Optional[set[int]] = None
    if args.chunks:
        selected_chunks = _parse_chunks_spec(args.chunks, total_chunks)
        if debug:
            log_debug(f"Chunk selection spec='{args.chunks}' -> {sorted(selected_chunks or [])}")

    # Load system prompt according to mode
    mode_to_file = {
        "normal": base / "prompts" / "system_normal.md",
        "strict": base / "prompts" / "system_strict.md",
        "creative": base / "prompts" / "system_creative.md",
    }
    spath = mode_to_file.get(content_mode)
    if spath is None or not spath.exists():
        # Fallback to legacy system.md
        spath = base / "prompts" / "system.md"
    system_prompt = spath.read_text(encoding="utf-8")
    # If provided, read one or more per-input context files (injected into USER prompt, not system)
    source_file_context = ""
    if args.context_files:
        parts: List[str] = []
        for p in args.context_files:
            with open(p, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    parts.append(t)
        if parts:
            # Keep order; join with a blank line between contexts
            source_file_context = "\n\n".join(parts)

    outdir = Path(args.outdir)
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        probe = outdir / ".write_test.tmp"
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        probe.unlink(missing_ok=True)
    except Exception as e:
        log_error(f"Output directory is not writable: {outdir} ({e})")
        sys.exit(1)

    # Select adapter
    try:
        adapter = create_llm_adapter(cfg, provider_override=args.llm_provider, project_root=base)
        if debug:
            log_debug(f"Using LLM adapter: {adapter.name()}")
    except Exception as e:
        log_error(f"Failed to initialize LLM adapter: {e}")
        sys.exit(1)

    # Process chunks
    cleaned_blocks = []
    qc_rows = []
    ok_count = 0
    fail_count = 0
    # Accumulate normalized term variants across chunks
    from scripts.utils import coalesce_term_map, build_alias_index, remap_keys_to_canonical
    known_terms = {}
    prev_raw_fragment = ""
    last_cleaned_fragment = ""
    # Keep previous plain cleaned text for dedup window (avoid wrapper comments interference)
    prev_for_dedup: Optional[str] = None
    effective_chunk_chars = int(cfg.get("txt_chunk_chars", 6500) or 6500)

    for idx, ch in enumerate(chunks, 1):
        # Prepare raw fragment for this chunk and compute context from previous chunk based on configured source
        units = ch.get("_units", [])
        overlap_n = int(ch.get("_overlap_units", 0))
        fragment_text = "\n".join(u["text"] for u in units[overlap_n:])

        # Skip chunks not in selection (if provided). Maintain prev_raw_fragment for better context continuity.
        if selected_chunks is not None and idx not in selected_chunks:
            log_info(f"[{idx}/{total_chunks}] Skipping…")
            # Advance raw fragment for potential future context even if not processed
            prev_raw_fragment = fragment_text
            continue

        log_info(f"[{idx}/{total_chunks}] Processing…")
        # Build context from tail of previous fragment/output
        if idx == 1:
            context_text = ""
            used_source = "none" if overlap_source == "none" else overlap_source
        else:
            used_source = overlap_source
            cleaned_available = bool((last_cleaned_fragment or "").strip())
            # If previous chunk wasn't processed and user asked for cleaned overlap,
            # we fallback to raw to keep continuity with immediately preceding text.
            prev_chunk_processed = (selected_chunks is None or (idx - 1) in (selected_chunks or set()))
            if used_source == "cleaned" and not prev_chunk_processed:
                log_warn("Cleaned overlap requested but previous chunk was skipped; using raw overlap instead")
                used_source = "raw"
            elif used_source == "cleaned" and not cleaned_available:
                # Check after stripping comments too
                if not (strip_all_html_comments(last_cleaned_fragment or "").strip()):
                    log_warn("Cleaned overlap requested but empty; falling back to raw")
                    used_source = "raw"
            context_text = build_context_overlap(
                prev_raw_text=prev_raw_fragment or "",
                prev_cleaned_text=last_cleaned_fragment or "",
                source=used_source,
                max_chars=int(cfg.get("txt_overlap_chars", 500) or 0),
                sentence_delimiters=sentence_delimiters,
            )
        if debug and idx > 1:
            log_debug(f"Chunk {idx}: overlap_source={used_source}; prev_raw_len={len(prev_raw_fragment)}; prev_cleaned_len={len(last_cleaned_fragment)}; CONTEXT chars={len(context_text)}; FRAGMENT chars={len(fragment_text)}")
        # Build term-hints block from previously observed merges
        # Present coalesced, single-canonical-per-cluster hints to the model
        coalesced_for_hints = coalesce_term_map(known_terms)
        term_hints_text = serialize_term_hints_json(coalesced_for_hints)
        original_text = fragment_text
        cleaned = ""
        attempt_i = 1
        while attempt_i <= attempts:
            try:
                # Optional delay before the first attempt on this chunk (inter-request pacing)
                if attempt_i == 1 and request_delay > 0 and idx > 1:
                    if debug:
                        log_debug(f"Sleeping {request_delay}s before first attempt for chunk {idx}")
                    time.sleep(request_delay)
                cleaned = call_llm(
                    adapter=adapter,
                    model=model,
                    system_prompt=system_prompt,
                    chunk_text=original_text,
                    lang=lang,
                    parasites=parasites,
                    aside_style=aside_style,
                    glossary=glossary,
                    timecodes_policy=timecodes_policy_text,
                    temperature=temperature,
                    top_p=top_p,
                    debug=debug,
                    trace=trace,
                    label=f"chunk {idx}/{total_chunks} (attempt {attempt_i}/{attempts})",
                    context_text=context_text,
                    term_hints_text=term_hints_text,
                    source_context_text=source_file_context,
                )
                # consider empty response as failure deserving a retry
                if not (cleaned or "").strip():
                    raise RuntimeError("Empty response text")
                break
            except Exception as e:
                provider_name = adapter.name()
                is_last = (attempt_i >= attempts)
                if debug:
                    log_debug(traceback.format_exc().rstrip())
                # Determine if retriable based on exception type
                retriable = isinstance(e, (Exception,))  # placeholder, refined below
                from aiadapters.base import LLMAuthError, LLMRateLimitError, LLMConnectionError, LLMUnknownError
                if isinstance(e, (LLMAuthError, LLMUnknownError)):
                    retriable = False
                elif isinstance(e, (LLMRateLimitError, LLMConnectionError)):
                    retriable = True
                else:
                    # other exceptions (including RuntimeError for empty text) -> retryable
                    retriable = True
                if not retriable or is_last:
                    log_error(f"{provider_name} failed on chunk {idx}/{total_chunks} (attempt {attempt_i}/{attempts}): {e}")
                    cleaned = ""
                    break
                else:
                    suggested = _extract_retry_after_seconds(str(e)) if isinstance(e, (LLMRateLimitError,)) else None
                    if suggested and suggested > 0:
                        wait_for = suggested + (pause_between_attempts or 0.0)
                    else:
                        wait_for = pause_between_attempts
                    log_warn(f"{provider_name} error on chunk {idx}/{total_chunks} (attempt {attempt_i}/{attempts}): {e}. Retrying after {wait_for or 0}s…")
                    if wait_for and wait_for > 0:
                        time.sleep(wait_for)
                    attempt_i += 1
        status = "OK" if cleaned and cleaned.strip() else "FAILED"
        if status == "OK":
            ok_count += 1
        else:
            fail_count += 1
        # Extract term merges; keep only per-chunk new ones in comments; accumulate for next chunks
        if cleaned:
            current_map = extract_merged_terms_map(cleaned)
            if current_map:
                # Compute only-new variants vs known_terms (before merging)
                only_new = diff_term_maps(current_map, known_terms)
                # Build combined map and coalesce to determine canonical keys
                combined = {}
                merge_term_maps(combined, known_terms)
                merge_term_maps(combined, current_map)
                combined = coalesce_term_map(combined)
                alias_index = build_alias_index(combined)
                # Remap per-chunk new items to canonical keys
                only_new_rekeyed = remap_keys_to_canonical(only_new, alias_index)
                # Rewrite comments to include only the per-chunk new items (canonicalized)
                cleaned = rewrite_merged_terms_comments(cleaned, only_new_rekeyed, prefer_style="auto")
                # Accumulate into known_terms and keep coalesced keys for future hints
                merge_term_maps(known_terms, current_map)
                known_terms = coalesce_term_map(known_terms)
        # For TXT inputs that had per-line timestamps, add link-style stamp (unless AI handled timecodes itself)
        if include_timecodes and not timecodes_handled_by_ai and fmt == "txt" and has_line_timestamps and ch.get("start") is not None:
            if debug:
                log_debug(f"Adding timecodes to chunk`s headings; start: {ch['start']}")
            cleaned = add_timecodes_to_headings(cleaned, ch["start"], as_link=True)
        # Stitch-time deduplication against previous output (use plain previous text)
        if prev_for_dedup and stitch_dedup_window > 0:
            prev = prev_for_dedup
            deduped, removed, mode = dedup_overlapping_boundary(prev, cleaned, stitch_dedup_window)
            if removed > 0 and debug:
                log_debug(f"Dedup removed {removed} {('lines' if mode=='lines' else mode)} from start of chunk {idx} before stitching")
            cleaned = deduped
        # Optionally strip edit comments in the final output
        if suppress_edit_comments:
            cleaned = strip_edit_comments(cleaned)
        # Wrap each part with start/end comments
        start_comment = f"<!-- STARTING: processing; Chunk size: {effective_chunk_chars}; Part [{idx}/{total_chunks}] -->"
        end_comment = f"<!-- END: of part [{idx}/{total_chunks}] -->"
        wrapped = f"{start_comment}\n{cleaned}\n{end_comment}"
        cleaned_blocks.append(wrapped)
        # Update previous-plain text for next dedup window
        prev_for_dedup = cleaned
        sim = similarity_ratio(original_text, cleaned)
        qc_rows.append({
            "chunk_id": idx,
            "start": ch["start"] if ch["start"] is not None else "",
            "end": ch["end"] if ch["end"] is not None else "",
            "orig_len": len(original_text),
            "cleaned_len": len(cleaned),
            "similarity": round(sim, 4),
            "change_ratio": round(1.0 - sim, 4),
        })
        remaining = total_chunks - idx
        log_info(f"{status} | done: {ok_count}, failed: {fail_count}, left: {remaining}")
        # Update previous fragments for next-iteration overlap
        prev_raw_fragment = fragment_text
        if status == "OK":
            last_cleaned_fragment = cleaned

    # Merge
    full_markdown = "\n\n".join(cleaned_blocks)

    # Append summary
    if cfg.get("append_summary", True):
        log_info("Generating summary…")
        summary = ""
        attempt_i = 1
        while attempt_i <= attempts:
            try:
                # Optional delay before the first attempt on summary
                if attempt_i == 1 and request_delay > 0:
                    if debug:
                        log_debug(f"Sleeping {request_delay}s before summary request")
                    time.sleep(request_delay)
                summary = call_llm_summary(
                    adapter, model, strip_edit_comments(full_markdown),
                    temperature=temperature, top_p=top_p,
                    debug=debug, trace=trace, label=f"summary (attempt {attempt_i}/{attempts})",
                )
                if not (summary or "").strip():
                    raise RuntimeError("Empty response text (summary)")
                break
            except Exception as e:
                provider_name = adapter.name()
                is_last = (attempt_i >= attempts)
                if debug:
                    log_debug(traceback.format_exc().rstrip())
                from aiadapters.base import LLMAuthError, LLMRateLimitError, LLMConnectionError, LLMUnknownError
                if isinstance(e, (LLMAuthError, LLMUnknownError)):
                    log_error(f"{provider_name} summary generation failed (attempt {attempt_i}/{attempts}): {e}")
                    summary = ""
                    break
                elif isinstance(e, (LLMRateLimitError, LLMConnectionError)):
                    if is_last:
                        log_error(f"{provider_name} summary generation failed (attempt {attempt_i}/{attempts}): {e}")
                        summary = ""
                        break
                    suggested = _extract_retry_after_seconds(str(e)) if isinstance(e, (LLMRateLimitError,)) else None
                    if suggested and suggested > 0:
                        wait_for = suggested + (pause_between_attempts or 0.0)
                    else:
                        wait_for = pause_between_attempts
                    log_warn(f"{provider_name} summary error (attempt {attempt_i}/{attempts}): {e}. Retrying after {wait_for or 0}s…")
                    if wait_for and wait_for > 0:
                        time.sleep(wait_for)
                    attempt_i += 1
                else:
                    log_error(f"{provider_name} summary generation failed (attempt {attempt_i}/{attempts}): {e}")
                    summary = ""
                    break
        if summary.strip():
            summary_heading = cfg.get("summary_heading", "## Non-authorial AI generated summary")
            full_markdown = full_markdown.rstrip() + "\n\n" + summary_heading + "\n\n" + summary + "\n"
        else:
            log_warn("Summary generation returned empty output.")

    # Write outputs
    outfile_md = outdir / f"{in_path.stem}.md"
    outfile_md.write_text(full_markdown, encoding="utf-8")
    # QC report
    qc_path = outdir / f"{in_path.stem}_qc_report.csv"
    with open(qc_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["chunk_id","start","end","orig_len","cleaned_len","similarity","change_ratio"])
        w.writeheader()
        for r in qc_rows:
            w.writerow(r)

    if fail_count == 0:
        log_info("All chunks processed successfully.")
    else:
        log_warn(f"Completed with {fail_count} failure(s) out of {total_chunks} chunk(s).")
    log_info(f"Done. Markdown: {outfile_md}")
    log_info(f"QC report: {qc_path}")

if __name__ == "__main__":
    main()
