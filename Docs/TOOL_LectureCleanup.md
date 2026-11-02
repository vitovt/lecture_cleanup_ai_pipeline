# Tool: lecture cleanup

`lecture_cleanup.sh` activates the main virtual environment and executes
`scripts.run_pipeline`. It transforms one TXT/SRT transcript into structured
Markdown; it does not perform speech recognition.

```bash
./lecture_cleanup.sh \
  --input ./lecture.uk.txt \
  --lang uk \
  --outdir ./output
```

The core loads tracked defaults, local configuration, and CLI overrides;
parses timestamps; chunks with context overlap; calls the selected cleanup LLM
with retries; stitches successful chunks; optionally generates summaries; and
writes Markdown and QC CSV.

Use `./lecture_cleanup.sh --help` for the authoritative option list. Formats are
documented in [FORMATS.md](FORMATS.md). Source-specific shell wrappers manage
their own input paths while validating and forwarding applicable cleanup
options.

## Continuity at chunk boundaries

After chunking and optional small-tail rebalancing, cleanup moves an unfinished
sentence tail to the next fragment when a line ending in sentence punctuation
is found within the preceding 1000 characters and the next chunk still fits
`txt_chunk_chars`. Text and source indices are preserved. If punctuation is
missing or there is insufficient room, the original boundary remains; this
heuristic cannot guarantee complete sentences in unpunctuated ASR output.

`use_context_overlap: cleaned` supplies the previous successful cleaned output
without HTML comments as read-only context. `raw` supplies the input tail.
A skipped or empty predecessor can cause a fallback to raw with a warning.
Context is excluded from the fragment to edit and must not be repeated.
