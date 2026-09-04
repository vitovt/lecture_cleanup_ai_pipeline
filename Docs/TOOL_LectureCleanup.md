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
