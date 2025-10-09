\
import os, argparse, json, yaml, sys, csv
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

def call_openai(client: OpenAI, model: str, system_prompt: str, user_prompt: str, chunk_text: str, lang: str, parasites: List[str], aside_style: str, glossary: List[str]) -> str:
    # fill template
    template = build_user_prompt(lang, parasites, aside_style, glossary)
    prompt = template.format(
        LANG=lang,
        PARASITES=", ".join(parasites),
        GLOSSARY=glossary if glossary else "—",
        ASIDE_STYLE=("курсив (*...*)" if aside_style == "italic" else "цитатний блок (> ...)"),
        CHUNK_TEXT=chunk_text,
    )

    resp = client.responses.create(
        model=model,
        temperature=0,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    # Support text output from Responses API
    if resp.output and len(resp.output) and resp.output[0].content and len(resp.output[0].content):
        return resp.output_text
    # Fallbacks:
    try:
        return resp.output_text
    except Exception:
        pass
    # Last resort
    return ""

def call_openai_summary(client: OpenAI, model: str, system_prompt: str, full_markdown: str) -> str:
    from pathlib import Path
    summary_tmpl_path = Path(__file__).parent.parent / "prompts" / "summary_prompt.md"
    with open(summary_tmpl_path, "r", encoding="utf-8") as f:
        sum_prompt = f.read()
    resp = client.responses.create(
        model=model,
        temperature=0,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": sum_prompt + "\n\n<<<\n" + full_markdown + "\n>>>"},
        ],
    )
    try:
        return resp.output_text
    except Exception:
        return ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to .srt or .txt")
    ap.add_argument("--format", choices=["srt", "txt"], help="Force input format (otherwise inferred)")
    ap.add_argument("--outdir", default="out/session1", help="Output directory")
    ap.add_argument("--lang", required=True, choices=["ru", "uk", "en"], help="Language of the lecture")
    ap.add_argument("--glossary", default=None, help="Path to glossary terms (one per line)")
    ap.add_argument("--chunk-seconds", type=int, default=None)
    ap.add_argument("--overlap-seconds", type=int, default=None)
    ap.add_argument("--txt-chunk-chars", type=int, default=None)
    ap.add_argument("--txt-overlap-chars", type=int, default=None)
    args = ap.parse_args()

    base = Path(__file__).parent.parent
    cfg = read_config(str(base / "config.yaml"))

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
    include_timecodes = bool(cfg.get("include_timecodes_in_headings", True))
    aside_style = cfg.get("highlight_asides_style", "italic")
    allow_minor_reordering = bool(cfg.get("allow_minor_reordering", True))

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
            )
        except Exception as e:
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
        summary = call_openai_summary(client, model, system_prompt, full_markdown)
        if summary.strip():
            summary_heading = cfg.get("summary_heading", "## Підсумок (не авторський)")
            full_markdown = full_markdown.rstrip() + "\n\n" + summary_heading + "\n\n" + summary + "\n"
        else:
            print("Summary generation returned empty output.")

    # Write outputs
    (outdir / "lecture.md").write_text(full_markdown, encoding="utf-8")
    # QC report
    with open(outdir / "qc_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["chunk_id","start","end","orig_len","cleaned_len","similarity","change_ratio"])
        w.writeheader()
        for r in qc_rows:
            w.writerow(r)

    if fail_count == 0:
        print("All chunks processed successfully.")
    else:
        print(f"Completed with {fail_count} failure(s) out of {total_chunks} chunk(s).")
    print(f"Done. Markdown: {outdir/'lecture.md'}")
    print(f"QC report: {outdir/'qc_report.csv'}")

if __name__ == "__main__":
    main()
