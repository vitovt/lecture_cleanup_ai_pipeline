Context: This is a lecture fragment (ASR-recognized, may contain audio-specific errors) to be read in a knowledge base (Obsidian) and searched later. Follow the active System-mode rules (STRICT/NORMAL/CREATIVE) exactly.

{SOURCE_CONTEXT_BLOCK}Language of this fragment: {LANG}
Filler words for this language (remove only if safe): [{PARASITES}]
Glossary (verbatim, may be empty): {GLOSSARY_OR_DASH}
Asides style: {ASIDE_STYLE}

Tasks (ASR-aware cleanup + reader-friendly structure within mode limits):
1) Restore correct punctuation and casing/diacritics; fix obvious transcription artifacts and duplicated words that carry no meaning.
2) Correct unambiguous ASR mis-hearings and homophones by context; never normalize “by frequency”. If unsure, keep original.
3) Keep code, math, filenames, commands, citations unchanged (except punctuation/casing fixes around them).
4) Structure only where implied: suitable headings, bullet/numbered lists, **bold**/**italics**; visually separate asides/jokes using the specified style.
5) For headings use #, ##, ###, ####, #####
6) For short explanations aside from the main idea use markdown quote >
7) Apply reordering/splitting/merging only if permitted by the active System mode. No additions; preserve meaning 1:1.

Important continuity policy:
- You may be given a read-only CONTEXT to ensure continuity. It is glue only.
- Do NOT repeat, paraphrase, or output the CONTEXT.
- Output must contain ONLY the cleaned FRAGMENT (Markdown), nothing else.

Term normalization hints (DO NOT OUTPUT):
- These hints are accumulated from earlier fragments to keep terminology consistent across chunks.
- Use only when consistent with the FRAGMENT and GLOSSARY; do not override the FRAGMENT's meaning.
- Never echo these hints in the output.
<<<
{TERM_HINTS}
>>>

Timecodes policy (if applicable):
- Add timecodes only to headings generated from the FRAGMENT itself.
- Never add or duplicate timecodes for headings that exist only in CONTEXT.
- Do not place timecodes elsewhere.

Output: Markdown ONLY (no prefixes, no explanations, no context echoes).

Previous fragment context (same file, READ-ONLY, DO NOT OUTPUT):
- This is text from earlier chunks of the same recording.
- Use it only for continuity (who speaks, what they refer to, correct headings).
- Do NOT repeat, paraphrase, or output any of it directly.
- Can be empty if it is the first fragment
<<<
{CONTEXT_TEXT}
>>>

FRAGMENT (EDIT AND OUTPUT ONLY):
<<<
{CHUNK_TEXT}
>>>

After the fragment, append zero or more HTML comments documenting edits (comments only; no visible text after them):
- <!-- fixed: ... --> objective punctuation/casing/duplicate-word fixes.
- <!-- filler_removed: ... --> safely removed fillers (language-dependent).
- <!-- merged_terms: "variant1, variant2" -> "normalized_term"; ... --> (normal/creative; optional in normal).
- <!-- rephrased: ... --> (normal/creative).
- <!-- unsure: ... --> ambiguities preserved verbatim.
