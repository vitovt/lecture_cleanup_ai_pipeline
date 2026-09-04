# Tool: merge transcripts

`scripts/merge_transcripts.py` combines provider-neutral event documents. It
does not call an ASR provider or the cleanup LLM.

## Merge a resolved session

```bash
python3 scripts/merge_transcripts.py \
  --manifest ./multitrack-work/resolved-manifest.yaml \
  --output-base ./multitrack-work/combined/webinar.uk \
  --format events --format txt --format srt
```

## Merge explicit event files

```bash
python3 scripts/merge_transcripts.py \
  --file ./tracks/00-host.events.json \
  --file ./tracks/01-guest.events.json \
  --output-base ./combined/webinar \
  --format txt
```

The tool applies each document's `offset_ms`, rejects events shifted before
zero, sorts by start/end/track order, and preserves simultaneous events. The
default output format is custom TXT. Formats are repeatable and documented in
[FORMATS.md](FORMATS.md).

To resynchronize without another ASR request, edit offsets in the resolved
manifest and run this tool again.
