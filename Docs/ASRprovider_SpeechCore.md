# ASR provider: SpeechCore

SpeechCore support lives in the independent `speechcoreai-api/` repository and
is coordinated by the root YouTube/local SpeechCore wrappers. It uploads audio,
polls the remote task, downloads or extracts TXT, and passes the result to
lecture cleanup.

```bash
./StartMe.sh local-speechcore --lang uk ./meeting.m4a
./StartMe.sh youtube-speechcore --lang auto "https://youtu.be/VIDEO_ID"
```

SpeechCore is not yet registered as a multitrack provider. Adding it requires a
`TranscriptionProvider` adapter that converts its response into transcript
event JSON version 1; the merger and complete multitrack pipeline then need no
provider-specific changes.

See [FORMATS.md](FORMATS.md) and [TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md).
