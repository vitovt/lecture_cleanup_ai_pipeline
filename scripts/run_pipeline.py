\
import os, argparse, json, yaml, sys, csv, traceback
from typing import List, Dict
from openai import OpenAI
from pathlib import Path

from utils import parse_srt, chunk_segments_by_time, chunk_text, add_timecodes_to_headings, similarity_ratio

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

def build_user_prompt(lang: str, parasites: List[str], aside_style: str, glossary_terms: List[str]) -> str:
    from pathlib import Path
    # load template
    tmpl_path = Path(__file__).parent.parent / "prompts" / "user_template.md"
    with open(tmpl_path, "r", encoding="utf-8") as f:
        tmpl = f.read()
    return tmpl

def call_openai(client: OpenAI, model: str, system_prompt: str, user_prompt: str, chunk_text: str, lang: str, parasites: List[str], aside_style: str, glossary: List[str], temperature: float = 1.0, top_p: float = None, debug: bool = False, label: str = None) -> str:
    # fill template
    template = build_user_prompt(lang, parasites, aside_style, glossary)
    prompt = template.format(
        LANG=lang,
        PARASITES=", ".join(parasites),
        GLOSSARY=glossary if glossary else "—",
        ASIDE_STYLE=("курсив (*...*)" if aside_style == "italic" else "цитатний блок (> ...)"),
        CHUNK_TEXT=chunk_text,
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to .srt or .txt")
    ap.add_argument("--format", choices=["srt", "txt"], help="Force input format (otherwise inferred)")
    ap.add_argument("--outdir", default="output", help="Output directory")
    ap.add_argument("--lang", required=True, choices=["ru", "uk", "en"], help="Language of the lecture")
    ap.add_argument("--glossary", default=None, help="Path to glossary terms (one per line)")
    ap.add_argument("--chunk-seconds", type=int, default=None)
    ap.add_argument("--overlap-seconds", type=int, default=None)
    ap.add_argument("--txt-chunk-chars", type=int, default=None)
    ap.add_argument("--txt-overlap-chars", type=int, default=None)
    ap.add_argument("--debug", action="store_true", help="Enable verbose logging and print all OpenAI requests/responses")
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
    if args.chunk_seconds: cfg["chunk_seconds"] = args.chunk_seconds
    if args.overlap_seconds: cfg["overlap_seconds"] = args.overlap_seconds
    if args.txt_chunk_chars: cfg["txt_chunk_chars"] = args.txt_chunk_chars
    if args.txt_overlap_chars: cfg["txt_overlap_chars"] = args.txt_overlap_chars

    lang = args.lang
    model = cfg.get("model", "gpt-5.1")
    temperature = cfg.get("temperature", 1)
    top_p = cfg.get("top_p", None)
    include_timecodes = bool(cfg.get("include_timecodes_in_headings", True))
    aside_style = cfg.get("highlight_asides_style", "italic")
    allow_minor_reordering = bool(cfg.get("allow_minor_reordering", True))
    if debug:
        print(f"[DEBUG] Settings -> model={model}, temperature={temperature}, top_p={top_p}, lang={lang}")
        print(f"[DEBUG] Options -> include_timecodes={include_timecodes}, aside_style={aside_style}, reordering={allow_minor_reordering}")

    # Load parasites for the language
    parasites_map = cfg.get("parasites", {})
    parasites_path = parasites_map.get(lang)
    parasites = load_list(str(base / parasites_path)) if parasites_path else []
    glossary = load_list(args.glossary) if args.glossary else []

    # Decide format
    in_path = Path(args.input)
    if args.format:
        fmt = args.format
    else:
        ext = in_path.suffix.lower()
        fmt = "srt" if ext == ".srt" else "txt"
    if debug:
        print(f"[DEBUG] Input: {in_path} | format={fmt} | outdir={outdir if 'outdir' in locals() else args.outdir}")

    # Prepare chunks
    if fmt == "srt":
        segments = parse_srt(str(in_path))
        chunks = chunk_segments_by_time(
            segments,
            chunk_seconds=cfg.get("chunk_seconds", 240),
            overlap_seconds=cfg.get("overlap_seconds", 8),
        )
    else:
        txt = load_text(str(in_path))
        chunks = chunk_text(
            txt,
            chunk_chars=cfg.get("txt_chunk_chars", 6500),
            overlap_chars=cfg.get("txt_overlap_chars", 500),
        )
    total_chunks = len(chunks)
    print(f"Prepared {total_chunks} chunk(s). Starting processing…")
    if debug and fmt == "srt":
        if len(chunks):
            first = chunks[0]
            last = chunks[-1]
            print(f"[DEBUG] First chunk: start={first.get('start')} end={first.get('end')} len={len(first.get('text',''))}")
            print(f"[DEBUG] Last  chunk: start={last.get('start')} end={last.get('end')} len={len(last.get('text',''))}")
    if debug and fmt == "txt":
        if len(chunks):
            print(f"[DEBUG] First chunk length={len(chunks[0].get('text',''))}; last chunk length={len(chunks[-1].get('text',''))}")

    # Load prompts
    system_prompt = (base / "prompts" / "system.md").read_text(encoding="utf-8")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    client = OpenAI()  # uses OPENAI_API_KEY env var

    # Process chunks
    cleaned_blocks = []
    qc_rows = []
    ok_count = 0
    fail_count = 0
    for idx, ch in enumerate(chunks, 1):
        print(f"[{idx}/{total_chunks}] Processing…", end="", flush=True)
        original_text = ch["text"]
        try:
            cleaned = call_openai(
                client=client,
                model=model,
                system_prompt=system_prompt,
                user_prompt="",  # not used directly
                chunk_text=original_text,
                lang=lang,
                parasites=parasites,
                aside_style=aside_style,
                glossary=glossary,
                temperature=temperature,
                top_p=top_p,
                debug=debug,
                label=f"chunk {idx}/{total_chunks}"
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
        # Optionally add timecodes to headings for SRT
        if fmt == "srt" and include_timecodes:
            cleaned = add_timecodes_to_headings(cleaned, ch["start"])
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

    # Merge
    full_markdown = "\n\n".join(cleaned_blocks)

    # Append summary
    if cfg.get("append_summary", True):
        print("Generating summary…")
        summary = call_openai_summary(
            client, model, system_prompt, full_markdown,
            temperature=temperature, top_p=top_p,
            debug=debug, label="summary"
        )
        if summary.strip():
            summary_heading = cfg.get("summary_heading", "## Підсумок (не авторський)")
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
