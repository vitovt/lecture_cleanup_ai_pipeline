# Architecture

The project is assembled from replaceable command-line modules. High-level
pipelines coordinate acquisition, ASR, speaker attribution, transcript
normalization, merging, and LLM cleanup without embedding provider logic.

## Layers

1. `StartMe.sh` exposes complete user workflows. See [ENTRYPOINT_StartMe.md](ENTRYPOINT_StartMe.md).
2. Pipeline wrappers coordinate source-specific stages. See
   [PIPELINE_WholeSystem.md](PIPELINE_WholeSystem.md),
   [PIPELINE_LocalMedia.md](PIPELINE_LocalMedia.md),
   [PIPELINE_YouTube.md](PIPELINE_YouTube.md), and
   [PIPELINE_Multitrack.md](PIPELINE_Multitrack.md).
3. Standalone tools perform one transformation and can be composed without
   `StartMe.sh`. See [TOOL_TranscribeTracks.md](TOOL_TranscribeTracks.md),
   [TOOL_MergeTranscripts.md](TOOL_MergeTranscripts.md),
   [TOOL_LectureCleanup.md](TOOL_LectureCleanup.md), and
   [TOOL_SubtitleUtilities.md](TOOL_SubtitleUtilities.md).
4. Provider adapters isolate external ASR behavior. See
   [ASRprovider_Groq.md](ASRprovider_Groq.md) and
   [ASRprovider_SpeechCore.md](ASRprovider_SpeechCore.md).
5. Provider-neutral event documents form the boundary between transcription
   and timeline merging. See [FORMATS.md](FORMATS.md).
6. Speaker detection is an optional provider-independent component. See
   [COMPONENT_Diarization.md](COMPONENT_Diarization.md).

The documentation entry point is [GLOSSARY.md](GLOSSARY.md).
