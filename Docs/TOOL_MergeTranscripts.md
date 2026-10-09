# Tool: merge timestamped TXT

No provider or cleanup call is involved. Inputs use the standard cleanup TXT:
`[HH:MM:SS,mmm] [Speaker] text`. Missing/invalid timestamps are rejected.

```bash
python3 scripts/merge_transcripts.py \
  --file work/sources/host/source.txt \
  --file work/sources/guest/source.txt \
  --offset-ms 0 --offset-ms 250 \
  --output work/combined/session.txt
```

Offsets are milliseconds, in file order. Omit all offsets for zero, or supply
one per file. Negative adjusted timestamps are errors. Equal start times retain
source order. Simultaneous speech and cross-track leakage are preserved.

The merger does not interpret provider JSON or invent utterance end times.
Changing offsets and merging again does not require retranscription.
