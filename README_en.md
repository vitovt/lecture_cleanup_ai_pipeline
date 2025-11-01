# Lecture Cleanup AI Pipeline (English)

The tool transforms long lecture transcripts into readable Markdown for Obsidian and knowledge bases.
It preserves the content without loss, corrects punctuation, capitalization, and typical ASR errors, adds a simple structure, and maintains consistent terminology between text blocks.

* **Input:** `.txt` (lines, optionally with `[HH:MM:SS,mmm]`) or `.srt` (in development due to format variations).
* **Output:** a single `.md` file and a `.csv` QC report.
* Works in overlapping chunks and supports hints for consistent terminology across parts.
* Has three editing modes: `strict`, `normal`, `creative`.

## How It Works (Short Overview)

1. Reads the input file (`.txt` or `.srt`). For `.txt`, timestamps may appear in square brackets at the start of lines.
2. Splits the text into chunks with overlap, avoiding line breaks when possible.
3. Adds “context” from the previous fragment (read-only) — can be `raw`, `cleaned`, or `none`.
4. Sends the fragment to OpenAI with strict prompts.
5. For `.txt` files with timecodes, adds them to fragment headings (same timestamp for all headings within a chunk).
6. Removes duplicates at chunk boundaries during stitching.
7. Collects “merged terms” info and passes it to the next blocks via comments `<!-- merged_terms: ... -->` (only new changes per block).
8. Joins all blocks into a final Markdown document; optionally appends a non-authored summary.
9. Generates a QC report showing how much each fragment was changed.

## Screenshohts

<img width="500" alt="cleanup-pipeline01" src="https://github.com/user-attachments/assets/9a096d90-fe5f-4c7a-8170-3dd25917ee8d" />
<img width="500" alt="cleanup-pipeline02" src="https://github.com/user-attachments/assets/20d11eda-0628-49cf-a987-62340eb19d77" />

---

<img width="500" alt="cleanup-pipeline03" src="https://github.com/user-attachments/assets/bb4cc7b1-eba5-401e-9b50-be5a65bd235e" />
<img width="500" alt="cleanup-pipeline04" src="https://github.com/user-attachments/assets/0d992cd8-ce0f-4f3a-8396-e96e09beeb2d" />

---

## Algorithm (Detailed)

* **Input lines:**

  * TXT: each line is preserved. Lines of the form `[HH:MM:SS,mmm] text` produce timecode headings.
  * SRT: only text is taken. Timecodes for headings are not added. Recommended: convert SRT → line-based TXT with timestamps for full functionality.
* **Chunking (line-preserving):**

  * `chunk_text_line_preserving(...)` groups text up to `txt_chunk_chars` with overlap `txt_overlap_chars`.
  * Context = last `txt_overlap_chars` of the previous chunk (read-only).
* **OpenAI call:**

  * System prompt depends on mode: `strict` / `normal` / `creative`.
  * User prompt includes: language, filler-word lists, aside/joke style, `TERM_HINTS` (hidden), “context,” and the fragment.
* **Terminology normalization:**

  * Extracts `<!-- merged_terms: ... -->` from model output.
  * Builds a global map of canonical → variants.
  * Passes it to the next call as `TERM_HINTS` (hidden, not printed).
  * Keeps only new terms in the current block’s comment.
* **Timecodes:**

  * For TXT with timestamps — appends `[HH:MM:SS]` or `[#t=HH:MM:SS]` to fragment headings.
* **Deduplication:**

  * Compares the end of the previous chunk and start of the next within a window `stitch_dedup_window_chars`; removes duplicates.
* **Summary:**

  * Optionally appends a non-authored summary generated via a separate prompt.
* **QC:**

  * Writes CSV: lengths, similarity to original, modification ratio.

## Installation

1. Install Python 3.10 or newer.
2. Create a `.env` file in the project root (or copy it):

   ```bash
   cp .env_default .env
   ```

   Then set your key:

   ```env
   OPENAI_API_KEY=your_key
   ```
3. Run environment initialization once:

   ```bash
   ./init_once.sh
   ```

   This script creates `.venv` and installs dependencies (`pyyaml`, `openai`).

## Usage

It’s recommended to run via provided `.sh` wrappers — they activate `.venv` and call the Python script with correct flags.
⚠️ **Important:** make sure the latest `openai` package is installed — outdated versions may cause crashes or incorrect behavior!

* **Single file:**

  ```bash
  ./lecture_cleanup.sh --input input/lecture.txt --lang uk
  ```
* **Batch mode (all `.txt` in a directory, default `./input`):**

  ```bash
  ./bulk_cleanup.sh --lang uk
  # or in another folder
  ./bulk_cleanup.sh --lang uk --indir ./notes
  ```

Output files are stored in `./output`:

* `lecture.md` — final Markdown file
* `lecture_qc_report.csv` — QC report

## CLI Flags (Main)

These flags are passed to `scripts/run_pipeline.py` via the `.sh` wrappers.

* `--input` *(required)* — path to `.txt` or `.srt`
* `--format` — `txt` or `srt` (auto-detected if omitted)
* `--outdir` — output folder (default `output`)
* `--lang` — `ru`, `uk`, `en`
* `--glossary` — path to glossary file (one term per line)
* `--txt-chunk-chars` — chunk size in characters (overrides config)
* `--txt-overlap-chars` — overlap size in characters
* `--include-timecodes` — include timecodes in headings (for TXT)
* `--use-context-overlap {raw,cleaned,none}` — type of context for next fragment
* `--debug` — detailed logging (includes prompts/responses)

**Examples**

```bash
# Basic run (Ukrainian, TXT auto-detected)
./lecture_cleanup.sh --input input/lec1.txt --lang uk

# SRT (still experimental)
./lecture_cleanup.sh --input input/lec1.srt --lang uk --format srt

# Custom chunk size and overlap
./lecture_cleanup.sh --input input/lec1.txt --lang uk \
  --txt-chunk-chars 6000 --txt-overlap-chars 600

# Use cleaned overlap context
./lecture_cleanup.sh --input input/lec1.txt --lang uk --use-context-overlap cleaned

# With glossary and timecodes
./lecture_cleanup.sh --input input/lec1.txt --lang uk --glossary data/my_glossary.txt --include-timecodes

# Enable debug mode
./lecture_cleanup.sh --input input/lec1.txt --lang uk --debug
```

## Configuration (`config.yaml`)

Most options can be overridden via CLI flags.

* `language`: lecture language (`ru`, `uk`, `en`)
* `model`: OpenAI model (`gpt-5.1`, `gpt-5-mini`, etc.)
* `temperature`: 0–2 (use moderate for cleanup modes). For GPT-5 must allways = 1
* `top_p`: top-p sampling (keep 1.0 for determinism)
* `format`: `txt` or `srt` (overrides auto-detection)
* `txt_chunk_chars`: chunk size (default 6500)
* `txt_overlap_chars`: overlap size (default 500)
* `use_context_overlap`: `raw`, `cleaned`, or `none` (`raw` = default)
* `stitch_dedup_window_chars`: deduplication window (null = same as overlap, 0 = off)
* `include_timecodes_in_headings`: add timecodes to headings (for TXT)
* `content_mode`: `strict` / `normal` / `creative`

  * `strict`: minimal surface corrections only
  * `normal`: readable phrasing, minor reorderings allowed
  * `creative`: freer structuring; prioritizes contextual term normalization to avoid frequent ASR biases
* `suppress_edit_comments`: remove HTML comments from final Markdown
* `highlight_asides_style`: `italic` or `blockquote` for asides/jokes
* `append_summary`: append summary at end of document
* `summary_heading`: heading title for summary section
* `parasites`: paths to filler-word lists by language

### Overlap Context Source

* `txt_overlap_chars` defines max context length.
* Source: `raw` or `cleaned` (without HTML comments). If `cleaned` empty → fallback to `raw` with warning.
* Truncation order:

  1. Whole lines
  2. If too long — cut by sentences (`.!?…`)
  3. If first sentence still too long — cut by words; if word too long — tail within budget
* No service markers; natural order; total length ≤ budget.

## Terminology Control Between Blocks

* Model records normalized terms in `<!-- merged_terms: ... -->`.
* Pipeline aggregates them and passes as `TERM_HINTS` to the next calls.
* Comments show only new entries per block.
* If later blocks introduce new variants, they are merged into clusters with one canonical form.

## Directory Structure

* `input/` — put `.txt` or `.srt` here
* `output/` — final `.md` and `_qc_report.csv`
* `data/parasites_*.txt` — filler-word lists
* `prompts/` — system and user prompt templates
* `scripts/run_pipeline.py` — main logic
* `scripts/slides_stub.py` — placeholder for slide text/image support
* `init_once.sh`, `lecture_cleanup.sh`, `bulk_cleanup.sh` — run wrappers

## Tips

* Create `.env` and never commit your API key.
* Keep `suppress_edit_comments: false` for debugging changes.
* Use `--debug` to inspect prompts and responses.

## Limitations

* **SRT** still experimental; several variants exist.

  * Currently processed without assigning timecodes to headings.
  * Will likely include an auto-standardizer to unify formats into timestamped TXT.
* Terminology matching depends on model output; if normalization not recorded, hint won’t appear.
* Supported languages: RU / UK / EN / DE (filler-word dictionaries). Others can work without dictionaries.
* Timecodes are approximate (per chunk start). Use smaller chunks for finer granularity.
* Summary generation sends the full cleaned text at once:

  * doubles token usage
  * may crash if exceeds model context window.

## License

This project is provided under the **MIT [LICENSE](LICENSE)** and distributed **WITHOUT ANY WARRANTY OF ANY KIND**.
