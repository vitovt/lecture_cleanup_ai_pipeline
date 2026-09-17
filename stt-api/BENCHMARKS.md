# Speech-to-text benchmarks

This document records reproducible comparisons of STT providers and modes used
by this project. Keep the source media, provider responses, metadata, and final
transcripts when adding a result. A transcript without its raw response is not
sufficient for diagnosing provider and formatter behavior.

## GEMINI-UK-DE-2026-09-17-001

### Purpose

Evaluate whether Gemini `gemini-3.5-transcribe` improves transcription of a
code-switched lesson containing:

- Ukrainian as the main teaching language;
- German physics terminology;
- German answers from the student;
- informal Ukrainian and Russian speech around the lesson material.

The comparison also checks whether custom vocabulary provides enough benefit
to justify disabling word timestamps.

### Source recording

| Field | Value |
| --- | --- |
| YouTube URL | `https://www.youtube.com/watch?v=2ONuv2UreIg` |
| Video ID | `2ONuv2UreIg` |
| Local title | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17` |
| Duration | `4600.656` seconds (`01:16:40.656`) |
| Audio | `input/autoyoutube-gemini/Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].mp3` |
| Audio size | `31,939,341` bytes |
| Audio SHA-256 | `55505fb4444cce1d976f952e2842843605d7f38e380f862be2c306216be1bc5c` |

All paths in this report are relative to the repository root. The complete
local repository path at the time of the test was:

```text
/home/vitovt/Desktop/Недороблені-недопушені_проги/lecture_cleanup_pipeline
```

The current workspace may be mounted under a different absolute prefix. Use
the repository-relative paths above rather than relying on the recorded
absolute path.

> **Storage warning:** `input/` is excluded by `.gitignore`. The source audio
> and benchmark outputs described below are local test artifacts and are not
> restored by cloning the Git repository. Preserve or back them up separately.

### Test 1: languages with word timestamps

Command:

```bash
./auto_process_youtube_via_gemini.sh \
  --lang uk-UA \
  --additional-lang de-DE \
  'https://www.youtube.com/watch?v=2ONuv2UreIg'
```

Configuration recorded in metadata:

- provider: `gemini`;
- model: `gemini-3.5-transcribe`;
- languages: `uk-UA`, `de-DE`;
- word timestamps: enabled;
- custom vocabulary: none;
- diarization: disabled;
- chunks: 4.

Artifacts are stored in:

```text
input/autoyoutube-gemini/test1/
```

| Artifact | File | Size | SHA-256 |
| --- | --- | ---: | --- |
| Final transcript | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.txt` | 71,142 bytes | `cc8fb453db92fc6aba692d3d064952f98d27e78c55f64b866b881a77fa9893df` |
| Raw provider result | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.raw.json` | 866,822 bytes | `19514be5cc6dc3c57b367eb04177f113b5f1de649d1cb5ccb5fd1ba6581265b7` |
| Normalized events | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.events.json` | 109,323 bytes | `72dd6f9f89108e95d984df6e50d534e5aab1bd722aeb94faaad5fde0d1d9f44a` |
| Run metadata | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.metadata.json` | 1,099 bytes | `ea2ec3a5997bef240bd32b53c14b33a232480423cc5cb2b6491294d00e8f420b` |
| Per-chunk cache | `.stt-cache/*.json` | 4 files | not recorded |

The files were moved into `test1/` after generation. Paths embedded in the
metadata therefore still refer to their original parent directory.

### Test 2: custom vocabulary without timestamps

Command:

```bash
./auto_process_youtube_via_gemini.sh \
  --lang uk \
  --additional-lang de \
  --timestamps off \
  --custom-vocabulary-file ./input/autoyoutube-gemini/vocab-de.txt \
  'https://youtu.be/2ONuv2UreIg' \
  --info
```

The short language codes were normalized to `uk-UA` and `de-DE`.

Configuration recorded in metadata:

- provider: `gemini`;
- model: `gemini-3.5-transcribe`;
- languages: `uk-UA`, `de-DE`;
- word timestamps: disabled;
- merged custom vocabulary: 219 entries;
- diarization: disabled;
- chunks: 2.

Vocabulary source:

```text
input/autoyoutube-gemini/vocab-de.txt
```

Vocabulary SHA-256:

```text
899ef2561a8b18aed7982452cc8d006724c8fa1212008077b6a8726f6a00b844
```

The file contains 221 non-comment lines, which become 219 unique entries after
merging. Two of the submitted entries are accidental Markdown code-fence
lines. The vocabulary parser currently treats both as ordinary terms.

Artifacts are stored in:

```text
input/autoyoutube-gemini/test2/
```

| Artifact | File | Size | SHA-256 |
| --- | --- | ---: | --- |
| Final transcript | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.txt` | 56,696 bytes | `b4dabd38c92cac7be72b4c5677ce5ef74baa43f92aad3a59bda69a1326aeae1f` |
| Raw provider result | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.raw.json` | 57,031 bytes | `de8cc486cb26712bd7228b080adae1552b3036f0beba32c6289a0da830015531` |
| Normalized events | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.events.json` | 2 bytes (`[]`) | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| Run metadata | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.metadata.json` | 1,102 bytes | `c73edb3039c435deba921c2f826f58b2930f853af693e2de2d19697dcd89747e` |
| Per-chunk cache | `.stt-cache/*.json` | 2 files | not recorded |

The files were moved into `test2/` after generation. Paths embedded in the
metadata therefore still refer to their original parent directory.

### Quantitative comparison

The raw transcript token counts below use the same Unicode word-token
extraction for both provider results. They are comparison metrics rather than
linguistic word counts.

| Metric | Test 1 | Test 2 |
| --- | ---: | ---: |
| Raw transcript tokens | 6,266 | 5,495 |
| Final TXT lines | 557 | 1 |
| Normalized events | 557 | 0 |
| Exact vocabulary entries found | 1 | 1 |
| Tokens containing `ä`, `ö`, `ü`, or `ß` | 0 | 0 |
| `напівпровід...` occurrences | 17 | 16 |
| `діод...` occurrences | 42 | 41 |
| `світлодіод...` occurrences | 17 | 18 |
| `електрон...` occurrences | 65 | 58 |
| `рекомбінац...` occurrences | 4 | 4 |

Test 2 contains approximately 12.3% fewer raw transcript tokens. A sequence
comparison produced a ratio of approximately `0.878`: about 94% of Test 2 can
be matched sequentially inside Test 1, while about 82.4% of Test 1 can be
matched inside Test 2. This indicates similar core Ukrainian content with Test
1 retaining more conversational material, although duplicate timestamp output
also inflates Test 1.

Only `LED` from the merged vocabulary occurs in either transcript. It appears
without vocabulary in Test 1 as well, so this is not evidence of vocabulary
improving recognition. Representative expected terms absent from both results
include:

```text
Halbleiter
Halbleiterdiode
Leuchtdiode
Gleichstrom
Wechselstrom
Durchlassrichtung
Sperrrichtung
Ladungsträger
Elektronen
Löcher
Dotierung
Rekombination
Sperrschicht
Anode
Kathode
Vorwiderstand
Photonen
```

### Qualitative findings

1. The main Ukrainian physics content is broadly similar in both results.
2. Neither mode successfully preserves German code-switching.
3. Test 1 sometimes produces Cyrillic phonetic approximations, for example
   `Richtig/Falsch` as `Ріштік/Фальш`.
4. A likely German `breiter` is rendered as `Bright Brighter` in Test 1.
5. Test 2 appears to omit several German answers or leave gaps around prompts
   asking the student to read or answer in German.
6. Test 2 contains mixed-script corruption such as `згодen`.
7. Test 1 is more useful downstream because it preserves source timestamps for
   navigation and `^src-SECONDS` identifiers.
8. Test 2 produces one long plain-text line and can only support untimed
   identifiers such as `^txt-N`.

Test 1 also exposed a formatter/normalization issue independent of STT quality:

- one timestamp regression from `00:39:24` to approximately `00:38:15`;
- seven exact duplicate normalized events;
- repeated content around that regression.

This should be fixed separately and considered when comparing transcript
lengths.

### Limitations

This is not a controlled vocabulary-only A/B test. Enabling vocabulary also
required disabling word timestamps, which changed:

- Gemini response structure;
- chunk duration;
- chunk count from 4 to 2;
- transcript formatting.

Therefore the test shows that vocabulary did **not visibly improve** German
recognition, but it does not prove that vocabulary itself caused omissions.

There is no manually corrected reference transcript, so word error rate and
language-specific error rate cannot be calculated. Request latency, provider
cost, and end-to-end processing time were not recorded and must not be inferred
from these artifacts.

### Decision

For this recording, prefer Test 1 over Test 2:

- custom vocabulary did not recover the German terminology;
- losing timestamps is not justified by the observed result;
- Test 1 provides better traceability and more complete conversational
  coverage.

The Gemini integration remains useful as a provider implementation and as a
benchmark baseline, but this result does not establish it as a solution for
Ukrainian/German code-switching.

### Next controlled comparison

Use short clips rich in German speech instead of repeating the complete
76-minute recording. Useful regions identified from Test 1 include:

- around `00:04:40`, where the student is asked to read terminology;
- `00:34:20` through `00:40:00`, containing German questions and answers.

Run the same extracted audio files through:

1. Gemini without timestamps and without vocabulary;
2. Gemini without timestamps and with a cleaned, focused vocabulary of roughly
   20–40 terms that are known to occur in the clip;
3. Groq as the existing baseline;
4. ElevenLabs using the same languages, audio, and target vocabulary.

For every future provider, record:

- exact command and provider/model version;
- audio SHA-256 so all providers use identical bytes;
- language and vocabulary settings;
- timestamps, diarization, chunk size, and chunk count;
- raw response, normalized events, metadata, and final TXT;
- exact recognition of the known German terms and answers;
- omissions, phonetic substitutions, and incorrect language/script;
- processing time and estimated API cost;
- timestamp monotonicity and duplicate-event count.

Do not rank providers from cleaned final prose alone. Compare their raw
responses first, then evaluate formatter behavior separately.
