# Component: speaker diarization

Public workflow terminology:

- `--diarization off`: no detection; multitrack source uses its exact display name.
- `--diarization pyannote`: local Pyannote; available through the Groq adapter.
- `--diarization provider`: native Gemini/ElevenLabs speaker attribution.

The ambiguous public value `on` is removed. Groq is a separate installed
repository whose internal CLI still receives its native boolean switch from
the adapter; this is not an accepted public workflow alias.

In multitrack mode configure detection independently per source. One detected
speaker uses the exact name; several become Name_01, Name_02, etc. Without
`--name`, the name is Source_ID. Labels are numbered by first appearance.
`--num-speakers N` is an expected count: supported by Pyannote and native
ElevenLabs, rejected for Gemini. Count disagreement is a warning.

Whole-source local diarization can span ASR chunks. Native diarization requiring
independent provider requests is rejected in multitrack mode: numeric speaker
IDs cannot be assumed to identify the same person in different requests.
No automatic backend fallback or cross-source speaker identity matching occurs.

The independent local tool remains available:

```bash
./StartMe.sh diarize --input-file meeting.wav \
  --output-json meeting.speakers.json --num-speakers auto
```
