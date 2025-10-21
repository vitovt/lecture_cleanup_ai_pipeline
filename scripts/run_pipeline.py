#!/usr/bin/env python3
import os, argparse, yaml, sys, csv, traceback
from typing import List, Optional
from openai import OpenAI
from pathlib import Path

from utils import (
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

def load_api_key_from_env_file(root: Path) -> bool:
    """Load OPENAI_API_KEY from a .env file at project root.

    Prefers .env over existing environment variable. Returns True if a key
    was found in .env and set into os.environ, else False.
    """
    env_path = root / ".env"
    if not env_path.exists():
        return False
    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                # support optional 'export ' prefix
                if line.lower().startswith("export "):
                    line = line[7:].lstrip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k != "OPENAI_API_KEY":
                    continue
                v = v.strip().strip('"').strip("'")
                if v:
                    os.environ["OPENAI_API_KEY"] = v
                    print("Loaded OPENAI_API_KEY from .env")
                    return True
    except Exception:
        # Fail silent, fallback to environment
        pass
    return False

def build_user_prompt(lang: str, parasites: List[str], aside_style: str) -> str:
    # load template
    tmpl_path = Path(__file__).parent.parent / "prompts" / "user_template.md"
    with open(tmpl_path, "r", encoding="utf-8") as f:
        tmpl = f.read()
    return tmpl

def call_openai(
    client: OpenAI,
    model: str,
    system_prompt: str,
    chunk_text: str,
    lang: str,
    parasites: List[str],
    aside_style: str,
    glossary: List[str],
    temperature: float = 1.0,
    top_p: float = None,
    debug: bool = False,
    label: str = None,
    context_text: str = "",
    term_hints_text: str = "",
) -> str:
    # fill template
    template = build_user_prompt(lang, parasites, aside_style)

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

    prompt = template.format(
        LANG=lang,
        PARASITES=parasites_str,
        GLOSSARY_OR_DASH=glossary_str,   # << matches EN template
        ASIDE_STYLE=aside_style_en,
        CHUNK_TEXT=chunk_text,
        CONTEXT_TEXT=(context_text or ""),
        TERM_HINTS=(term_hints_text or ""),
    )

    # Build request parameters, honoring config temperature/top_p when provided
    params = {
        "model": model,
        "temperature": temperature,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    if top_p is not None:
        params["top_p"] = top_p
    if debug:
        print("===== DEBUG: OpenAI request BEGIN" + (f" [{label}]" if label else "") + " =====")
        print(f"Model: {model} | temperature: {temperature} | top_p: {top_p}")
        print("-- System prompt --\n" + system_prompt)
        print("-- User prompt --\n" + prompt)
        print("===== DEBUG: OpenAI request END =====")
    resp = client.responses.create(**params)
    # Decide output text once to allow logging
    out_text = None
    try:
        if resp.output and len(resp.output) and resp.output[0].content and len(resp.output[0].content):
            out_text = resp.output_text
    except Exception:
        out_text = None
    if out_text is None:
        try:
            out_text = resp.output_text
        except Exception:
            out_text = ""
    if debug:
        print("===== DEBUG: OpenAI response BEGIN" + (f" [{label}]" if label else "") + " =====")
        print(out_text)
        print("===== DEBUG: OpenAI response END =====")
    return out_text

def call_openai_summary(client: OpenAI, model: str, system_prompt: str, full_markdown: str, temperature: float = 1.0, top_p: float = None, debug: bool = False, label: str = None) -> str:
    from pathlib import Path
    summary_tmpl_path = Path(__file__).parent.parent / "prompts" / "summary_prompt.md"
    with open(summary_tmpl_path, "r", encoding="utf-8") as f:
        sum_prompt = f.read()
    params = {
        "model": model,
        "temperature": temperature,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": sum_prompt + "\n\n<<<\n" + full_markdown + "\n>>>"},
        ],
    }
    if top_p is not None:
        params["top_p"] = top_p
    if debug:
        print("===== DEBUG: OpenAI request BEGIN" + (f" [{label}]" if label else "") + " =====")
        print(f"Model: {model} | temperature: {temperature} | top_p: {top_p}")
        print("-- System prompt --\n" + system_prompt)
        # Show entire request for transparency (can be large)
        from pathlib import Path as _Path
        print("-- User prompt (summary) --\n" + (open((_Path(__file__).parent.parent / "prompts" / "summary_prompt.md"), "r", encoding="utf-8").read()))
        print("-- Document (full markdown) --\n" + full_markdown)
        print("===== DEBUG: OpenAI request END =====")
    resp = client.responses.create(**params)
    out_text = ""
    try:
        out_text = resp.output_text
    except Exception:
        out_text = ""
    if debug:
        print("===== DEBUG: OpenAI response BEGIN" + (f" [{label}]" if label else "") + " =====")
        print(out_text)
        print("===== DEBUG: OpenAI response END =====")
    return out_text

def main():
    ap = argparse.ArgumentParser(
        description=(
            "Turn long lecture transcripts into clean Markdown with CONTEXT-overlap, "
            "mode-specific editing (normal/strict/creative), and stitching dedup. "
            "All config.yaml options can be overridden via dedicated flags or --set KEY=VALUE (supports dotted keys)."
        )
    )
    ap.add_argument("--input", required=True, help="Path to .srt or .txt")
    ap.add_argument("--format", choices=["srt", "txt"], help="Force input format (otherwise inferred)")
    ap.add_argument("--outdir", default="output", help="Output directory")
    ap.add_argument("--lang", required=True, choices=["ru", "uk", "en"], help="Language of the lecture")
    ap.add_argument("--glossary", default=None, help="Path to glossary terms (one per line)")
    # effective chunking params
    ap.add_argument("--txt-chunk-chars", type=int, default=None)
    ap.add_argument("--txt-overlap-chars", type=int, default=None)
    ap.add_argument("--debug", action="store_true", help="Enable verbose logging and print all OpenAI requests/responses")
    ap.add_argument("--use-context-overlap", dest="use_context_overlap", choices=["raw","cleaned","none"], help="Source of overlap: raw ASR tail, cleaned previous tail, or none")
    ap.add_argument("--include-timecodes", dest="include_timecodes", action="store_true", default=None, help="Append timecodes to headings when available")
    args = ap.parse_args()

    base = Path(__file__).parent.parent
    cfg = read_config(str(base / "config.yaml"))
    debug = bool(args.debug)
    if debug:
        print("Debug mode enabled")

    # API key resolution: prefer .env, else CLI environment
    has_dotenv_key = load_api_key_from_env_file(base)
    if not has_dotenv_key:
        # Try existing env (e.g., provided via CLI: OPENAI_API_KEY=... python ...)
        if os.environ.get("OPENAI_API_KEY"):
            print("Using OPENAI_API_KEY from environment")
        else:
            print(
                "ERROR: OPENAI_API_KEY not found. Provide it in .env or as an environment variable before the command.",
                file=sys.stderr,
            )
            sys.exit(1)

    # override config
    if args.txt_chunk_chars: cfg["txt_chunk_chars"] = args.txt_chunk_chars
    if args.txt_overlap_chars: cfg["txt_overlap_chars"] = args.txt_overlap_chars
    if args.include_timecodes is not None: cfg["include_timecodes_in_headings"] = bool(args.include_timecodes)

    lang = args.lang
    model = cfg.get("model", "gpt-5.1")
    temperature = cfg.get("temperature", 1)
    top_p = cfg.get("top_p", None)
    include_timecodes = bool(cfg.get("include_timecodes_in_headings", True))
    aside_style = cfg.get("highlight_asides_style", "italic")
    # Overlap source (backward compatible)
    cfg_overlap_source = cfg.get("use_context_overlap", None)
    if isinstance(cfg_overlap_source, str) and cfg_overlap_source.lower() in ("raw","cleaned","none"):
        overlap_source = cfg_overlap_source.lower()
    elif isinstance(cfg_overlap_source, bool):
        overlap_source = "raw" if cfg_overlap_source else "none"
    else:
        overlap_source = "raw"
    if args.use_context_overlap:
        overlap_source = args.use_context_overlap
    # sentence delimiters for overlap selection
    try:
        sentence_delimiters = str(cfg.get("overlap_sentence_delimiters", ".!?…"))
    except Exception:
        sentence_delimiters = ".!?…"
    stitch_dedup_window = int(cfg.get("stitch_dedup_window_chars", cfg.get("txt_overlap_chars", 500)) or 0)
    content_mode = (cfg.get("content_mode", "normal") or "normal").strip().lower()
    suppress_edit_comments = bool(cfg.get("suppress_edit_comments", True))
    if debug:
        print(f"[DEBUG] Settings -> model={model}, temperature={temperature}, top_p={top_p}, lang={lang}")
        print(f"[DEBUG] Options -> include_timecodes={include_timecodes}, aside_style={aside_style}")
        print(f"[DEBUG] Overlap -> source={overlap_source}, sentence_delimiters={sentence_delimiters!r}, stitch_dedup_window_chars={stitch_dedup_window}")
        print(f"[DEBUG] Content mode -> {content_mode}; suppress_edit_comments={suppress_edit_comments}")

    # Load parasites for the language
    parasites_map = cfg.get("parasites", {})
    parasites_path = parasites_map.get(lang)
    parasites = load_list(str(base / parasites_path)) if parasites_path else []
    glossary = load_list(args.glossary) if args.glossary else []

    # Decide format
    in_path = Path(args.input)
    cfg_format = (cfg.get("format") or "").strip().lower() if isinstance(cfg.get("format"), str) else None
    if args.format:
        fmt = args.format
    elif cfg_format in ("srt", "txt"):
        fmt = cfg_format
    else:
        ext = in_path.suffix.lower()
        fmt = "srt" if ext == ".srt" else "txt"
    if debug:
        print(f"[DEBUG] Input: {in_path} | format={fmt} | outdir={outdir if 'outdir' in locals() else args.outdir}")

    # Prepare chunks
    input_text = load_text(str(in_path))
    if not input_text.strip():
        print("ERROR: input file is empty after trimming whitespace.", file=sys.stderr)
        sys.exit(1)

    src_lines: List[str] = []
    per_line_time: List[Optional[float]] = []
    has_line_timestamps = False
    if fmt == "txt":
        parsed_lines = parse_timestamped_txt_lines(input_text)
        has_line_timestamps = any(item["time"] is not None for item in parsed_lines)
        src_lines = [item["text"] for item in parsed_lines]
        per_line_time = [item["time"] for item in parsed_lines]
        if debug:
            print(f"[DEBUG] TXT lines: {len(src_lines)} | timestamped={has_line_timestamps}")
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
            print(f"[DEBUG] SRT content lines (without times): {len(src_lines)}")

    if not any(l.strip() for l in src_lines):
        print("ERROR: input contains no textual content after preprocessing.", file=sys.stderr)
        sys.exit(1)

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
    print(f"Prepared {total_chunks} chunk(s). Starting processing…")
    if debug and total_chunks:
        print(f"[DEBUG] First chunk length={len(chunks[0].get('text',''))}; last chunk length={len(chunks[-1].get('text',''))}; count={len(chunks)}")

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

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    client = OpenAI()  # uses OPENAI_API_KEY env var

    # Process chunks
    cleaned_blocks = []
    qc_rows = []
    ok_count = 0
    fail_count = 0
    # Accumulate normalized term variants across chunks
    from copy import deepcopy
    from utils import coalesce_term_map, build_alias_index, remap_keys_to_canonical
    known_terms = {}
    prev_raw_fragment = ""
    last_cleaned_fragment = ""
    for idx, ch in enumerate(chunks, 1):
        print(f"[{idx}/{total_chunks}] Processing…", end="", flush=True)
        # Prepare raw fragment for this chunk and compute context from previous chunk based on configured source
        units = ch.get("_units", [])
        overlap_n = int(ch.get("_overlap_units", 0))
        fragment_text = "\n".join(u["text"] for u in units[overlap_n:])
        # Build context from tail of previous fragment/output
        if idx == 1:
            context_text = ""
            used_source = "none" if overlap_source == "none" else overlap_source
        else:
            used_source = overlap_source
            cleaned_available = bool((last_cleaned_fragment or "").strip())
            if used_source == "cleaned" and not cleaned_available:
                # Check after stripping comments too
                if not (strip_all_html_comments(last_cleaned_fragment or "").strip()):
                    print("\n[WARN] cleaned overlap requested but empty; falling back to raw", file=sys.stderr)
                    used_source = "raw"
            context_text = build_context_overlap(
                prev_raw_text=prev_raw_fragment or "",
                prev_cleaned_text=last_cleaned_fragment or "",
                source=used_source,
                max_chars=int(cfg.get("txt_overlap_chars", 500) or 0),
                sentence_delimiters=sentence_delimiters,
            )
        if debug and idx > 1:
            print(f"\n[DEBUG] Chunk {idx}: overlap_source={used_source}; prev_raw_len={len(prev_raw_fragment)}; prev_cleaned_len={len(last_cleaned_fragment)}; CONTEXT chars={len(context_text)}; FRAGMENT chars={len(fragment_text)}")
        # Build term-hints block from previously observed merges
        # Present coalesced, single-canonical-per-cluster hints to the model
        coalesced_for_hints = coalesce_term_map(known_terms)
        term_hints_text = serialize_term_hints_json(coalesced_for_hints)
        original_text = fragment_text
        try:
            cleaned = call_openai(
                client=client,
                model=model,
                system_prompt=system_prompt,
                chunk_text=original_text,
                lang=lang,
                parasites=parasites,
                aside_style=aside_style,
                glossary=glossary,
                temperature=temperature,
                top_p=top_p,
                debug=debug,
                label=f"chunk {idx}/{total_chunks}",
                context_text=context_text,
                term_hints_text=term_hints_text,
            )
        except Exception as e:
            if debug:
                print(f"[DEBUG] Exception during OpenAI call for chunk {idx}: {e}")
                traceback.print_exc()
            cleaned = ""
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
        # For TXT inputs that had per-line timestamps, add link-style stamp
        if include_timecodes and fmt == "txt" and has_line_timestamps and ch.get("start") is not None:
            if debug:
                print(f"[DEBUG] Adding timecodes to chunk`s headings; start: {ch['start']}")
            cleaned = add_timecodes_to_headings(cleaned, ch["start"], as_link=True)
        # Stitch-time deduplication against previous output
        if cleaned_blocks and stitch_dedup_window > 0:
            prev = cleaned_blocks[-1]
            deduped, removed, mode = dedup_overlapping_boundary(prev, cleaned, stitch_dedup_window)
            if removed > 0 and debug:
                print(f"[DEBUG] Dedup removed {removed} {('lines' if mode=='lines' else mode)} from start of chunk {idx} before stitching")
            cleaned = deduped
        # Optionally strip edit comments in the final output
        if suppress_edit_comments:
            cleaned = strip_edit_comments(cleaned)
        cleaned_blocks.append(cleaned)
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
        print(f" {status} | done: {ok_count}, failed: {fail_count}, left: {remaining}")
        # Update previous fragments for next-iteration overlap
        prev_raw_fragment = fragment_text
        if status == "OK":
            last_cleaned_fragment = cleaned

    # Merge
    full_markdown = "\n\n".join(cleaned_blocks)

    # Append summary
    if cfg.get("append_summary", True):
        print("Generating summary…")
        summary = call_openai_summary(
            client, model, system_prompt, full_markdown,
            temperature=temperature, top_p=top_p,
            debug=debug, label="summary",
        )
        if summary.strip():
            summary_heading = cfg.get("summary_heading", "## Non-authorial AI generated summary")
            full_markdown = full_markdown.rstrip() + "\n\n" + summary_heading + "\n\n" + summary + "\n"
        else:
            print("Summary generation returned empty output.")

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
        print("All chunks processed successfully.")
    else:
        print(f"Completed with {fail_count} failure(s) out of {total_chunks} chunk(s).")
    print(f"Done. Markdown: {outfile_md}")
    print(f"QC report: {qc_path}")

if __name__ == "__main__":
    main()
