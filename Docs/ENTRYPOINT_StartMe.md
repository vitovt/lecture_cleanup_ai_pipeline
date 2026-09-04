# Entry point: StartMe

`StartMe.sh` is the high-level dispatcher for complete workflows. Run it from
any directory; delegated project scripts are resolved relative to `StartMe.sh`.

```bash
./StartMe.sh
./StartMe.sh help MODE
./StartMe.sh MODE [arguments]
```

Workflow modes include transcript cleanup, YouTube subtitles, YouTube/local
Groq and SpeechCore transcription, batch variants, and `multitrack`. Provider
and maintenance modes expose Groq, diarization, setup, update, and conversion
operations where direct access is useful.

```bash
./StartMe.sh cleanup --input lecture.txt --lang uk
./StartMe.sh local-groq --lang auto ./meeting.m4a
./StartMe.sh multitrack --manifest ./webinar.yaml
```

Use `--color`, `--no-color`, or `--color=auto|always|never` before the mode.
Detailed, current options come from `./StartMe.sh help MODE`.

Low-level multitrack transcription and merging are intentionally not StartMe
modes. They remain standalone modules documented in
[TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md) and
[TOOL_MergeTranscripts.md](TOOL_MergeTranscripts.md).
