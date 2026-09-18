# Speech-to-text benchmarks

This document records reproducible comparisons of STT providers and modes used
by this project. Keep the source media, provider responses, metadata, and final
transcripts when adding a result. A transcript without its raw response is not
sufficient for diagnosing provider and formatter behavior.

## UK-DE-CODE-SWITCH-2026-09-17-001

### Purpose

Compare STT providers and modes on a code-switched lesson containing:

- Ukrainian as the main teaching language;
- German physics terminology;
- German answers from the student;
- informal Ukrainian and Russian speech around the lesson material.

The comparison checks whether Gemini custom vocabulary provides enough benefit
to justify disabling word timestamps, and whether ElevenLabs `scribe_v2`
preserves the German parts more reliably.

### Source recording

| Field | Value |
| --- | --- |
| YouTube URL | `https://www.youtube.com/watch?v=2ONuv2UreIg` |
| Video ID | `2ONuv2UreIg` |
| Local title | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17` |
| Duration | `4600.656` seconds (`01:16:40.656`) |
| Audio | `input/autoyoutube-gemini/Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].mp3` |
| ElevenLabs audio copy | `input/autoyoutube-elevenlabs/Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].mp3` |
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

The file contains 221 non-comment lines. At the time of this run, two
accidental Markdown code-fence lines were treated as ordinary terms, producing
the 219 entries recorded in metadata. The current parser ignores those fence
lines and produces 217 unique entries from the same file.

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

### Test 3: ElevenLabs with word timestamps

Command:

```bash
./auto_process_youtube_via_elevenlabs.sh \
  --lang uk-UA \
  --additional-lang de-DE \
  'https://www.youtube.com/watch?v=2ONuv2UreIg' \
  --debug
```

Configuration recorded in metadata:

- provider: `elevenlabs`;
- model: `scribe_v2`;
- requested languages: `uk-UA`, `de-DE`;
- provider language mode: automatic detection;
- detected language: `ukr`, probability `0.9654081463813782`;
- word timestamps: enabled;
- custom vocabulary/keyterms: none;
- diarization: disabled;
- chunks: 1.

Artifacts are stored in:

```text
input/autoyoutube-elevenlabs/
```

| Artifact | File | Size | SHA-256 |
| --- | --- | ---: | --- |
| Source audio | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].mp3` | 31,939,341 bytes | `55505fb4444cce1d976f952e2842843605d7f38e380f862be2c306216be1bc5c` |
| Final transcript | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.txt` | 78,480 bytes | `b7340f1da0c43ca13923a2310887f23dbd998a1e846ea3356ab729742977cfb8` |
| Raw provider result | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.raw.json` | 983,946 bytes | `05a3c5bb688eee7df59264e66a2935dfbae9b6517ae6db52121e5160ba1455d8` |
| Normalized events | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.events.json` | 121,701 bytes | `b65b9504f891c9c5d0ca0e129bd46de3272023ca5f12b1f6e5658c036188b898` |
| Run metadata | `Напівпровідники - діод, світлодіод, рекомбінація - 2026-09-17 [2ONuv2UreIg].uk.metadata.json` | 1,246 bytes | `8f544e068ea9810e07f2eea0fe37d90386cdb449c2abced12b33a7e893f51d3c` |
| Per-chunk cache | `.stt-cache/0b52da99f8f6e8e21cf3d0010cd4f3754a8e878e993091d3c94a4928354e233a.json` | 819,109 bytes | `31786e34af66b1470c58f12cf9a17c640ea2906b57b23f6060984353ab281780` |

The ElevenLabs and Gemini MP3 hashes are identical. All three tests therefore
use the same source audio bytes.

### Quantitative comparison

The raw transcript token counts below use the same Unicode word-token
extraction for all provider results. They are comparison metrics rather than
linguistic word counts. Exact vocabulary matches are case-insensitive checks
against the cleaned 217-entry `vocab-de.txt` list; Test 3 did not submit that
list to ElevenLabs.

| Metric | Test 1: Gemini timestamps | Test 2: Gemini vocabulary | Test 3: ElevenLabs |
| --- | ---: | ---: | ---: |
| Raw transcript tokens | 6,266 | 5,495 | 6,852 |
| Final TXT lines | 557 | 1 | 600 |
| Normalized events | 557 | 0 | 600 |
| Exact vocabulary entries found | 1 | 1 | 47 |
| Latin-script tokens | 90 | 53 | 535 |
| Tokens containing `ä`, `ö`, `ü`, or `ß` | 0 | 0 | 38 |
| `напівпровід...` occurrences | 17 | 16 | 18 |
| `діод...` occurrences | 42 | 41 | 44 |
| `світлодіод...` occurrences | 17 | 18 | 17 |
| `електрон...` occurrences | 65 | 58 | 70 |
| `рекомбінац...` occurrences | 4 | 4 | 3 |
| Timestamp regressions | 1 | not applicable | 0 |
| Exact duplicate normalized events | 7 | not applicable | 0 |

Test 3 contains approximately 9.4% more raw transcript tokens than Test 1 and
24.7% more than Test 2. The additional text is not merely formatting: a
substantial part consists of German speech missing from the Gemini results.
The count of Latin-script tokens rises from 90 in Gemini Test 1 to 535 in
ElevenLabs Test 3.

A rough sequence comparison between Tests 1 and 3 gives a ratio of `0.823`:
about 86.2% of the Gemini Test 1 tokens can be matched sequentially in Test 3,
while about 78.7% of Test 3 can be matched in Test 1. This supports the manual
observation that the Ukrainian core is similar while ElevenLabs retains
additional code-switched speech. It is not an accuracy score.

Only `LED` from the cleaned vocabulary occurs in either Gemini transcript, and
it already appears without vocabulary in Test 1. ElevenLabs Test 3, without
keyterms, contains exact matches for 47 list entries. Some are generic words,
so that number must not be interpreted as 47 independently verified technical
terms.

Of the following 17 representative German terms that were absent from both
Gemini results, ElevenLabs captured 12 exactly:

```text
Halbleiter
Leuchtdiode
Gleichstrom
Wechselstrom
Durchlassrichtung
Ladungsträger
Elektronen
Löcher
Dotierung
Rekombination
Sperrschicht
Photonen
```

The five still absent as exact forms are `Halbleiterdiode`, `Sperrrichtung`,
`Anode`, `Kathode`, and `Vorwiderstand`. The transcript does contain the
near-form `Sperrichtung`, with one `r` missing.

### Qualitative findings

1. The main Ukrainian physics content is broadly similar across all three
   results.
2. ElevenLabs is substantially better at preserving Ukrainian/German
   code-switching in this recording, including whole German clauses rather
   than isolated loanwords.
3. Around `00:04:45`, ElevenLabs records `Gleichstrom, Wechselstrom`; the
   corresponding Gemini output omits both terms.
4. Around `00:37:55`, ElevenLabs records `P an plus, N an minus ist
   Durchlassrichtung. Richtig, falsch?`; Gemini retains only surrounding
   Ukrainian speech.
5. Around `01:05:00`, ElevenLabs retains a multi-sentence German explanation
   containing `Elektronen und Löcher`, `p-n-Übergang`, `Rekombination`,
   `Sperrschicht`, `Energie`, and `Photonen`. Gemini reduces much of this
   passage to phonetic fragments such as `Дан`, `Шикзона`, and `шпершик`.
6. Gemini Test 1 also renders `Richtig/Falsch` as `Ріштік/Фальш`, while Test 2
   appears to omit several German answers entirely.
7. ElevenLabs is not error-free. Examples that require audio or screen context
   to resolve include `über Widerhold`, `Durchlassstück`, and the inconsistent
   `Sperrsicht`/`Sperrschicht`. A likely German `breiter` still appears as
   English `Brighter`.
8. Some German orthography loses diacritics, for example `hinzufugen` and
   `stossen`, although other occurrences correctly contain `ü`, `ö`, or `ß`.
9. Grammatical errors in student answers must not automatically be classified
   as STT errors; the transcript may accurately preserve spoken learner
   German.
10. ElevenLabs reports one global detected language (`ukr`) rather than
    language metadata per segment, even though the transcript itself preserves
    both languages.
11. Test 3 preserves timestamps and is directly usable for downstream
    navigation and `^src-SECONDS` identifiers. Test 2 can only support untimed
    identifiers such as `^txt-N`.

Gemini Test 1 also exposed a formatter/normalization issue independent of STT
quality:

- one timestamp regression from `00:39:24` to approximately `00:38:15`;
- seven exact duplicate normalized events;
- repeated content around that regression.

ElevenLabs Test 3 contains 6,865 timestamped word records covering `00:00:00.2`
through `01:16:38.168`. Its word timestamps and 600 normalized events are
monotonic, with no exact duplicate records found. This makes the Test 3 length
and event count more trustworthy than Test 1 for this run.

### Limitations

Tests 1 and 2 are not a controlled vocabulary-only A/B test. Enabling Gemini
vocabulary also required disabling word timestamps, which changed:

- Gemini response structure;
- chunk duration;
- chunk count from 4 to 2;
- transcript formatting.

Therefore those two tests show that Gemini vocabulary did **not visibly
improve** German recognition, but they do not prove that vocabulary itself
caused omissions.

Test 3 uses the same source audio but a different provider, response format,
timestamp implementation, and chunk count. It does not use the custom
vocabulary. The comparison is sufficient to reveal a large practical
difference on this recording, but it does not isolate which provider feature
caused that difference.

There is no manually corrected reference transcript, so word error rate and
language-specific error rate cannot be calculated. Request latency, provider
cost, and end-to-end processing time were not recorded and must not be inferred
from these artifacts. Provider behavior may also change with model updates, so
the command, model name, raw response, and hashes must remain attached to this
result.

### Decision

For this recording, prefer ElevenLabs Test 3:

- it preserves materially more German terminology and complete German clauses;
- it keeps word timestamps and therefore source traceability;
- it has no observed timestamp regressions or duplicate normalized events;
- it preserves at least as much of the core Ukrainian lesson content by the
  available proxy measures.

Within Gemini, Test 1 remains preferable to Test 2 because custom vocabulary
did not recover German speech and does not justify losing timestamps. Gemini
remains useful as a provider implementation and baseline, but these results do
not support it for Ukrainian/German code-switching in this lecture.

This is a recording-specific decision, not a universal provider ranking.

### Next controlled comparison

Use short clips rich in German speech instead of repeating the complete
76-minute recording. Useful regions identified from Test 1 include:

- around `00:04:40`, where the student is asked to read terminology;
- `00:34:20` through `00:40:00`, containing German questions and answers.

Run the extracted short clips through:

1. ElevenLabs without keyterms, matching Test 3;
2. ElevenLabs with a focused list of roughly 20–40 terms known to occur;
3. Gemini without timestamps and without vocabulary;
4. Gemini without timestamps and with the same focused vocabulary;
5. Groq as the existing baseline.

Create a manually corrected reference for those clips before calculating word
or term error rates. The next ElevenLabs keyterm run is especially useful
because Test 3 already succeeds without keyterms and ElevenLabs can retain word
timestamps when keyterms are supplied.

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
