Context: This is a lecture fragment to be read in a knowledge base (Obsidian) and searched later for reference.
Do NOT generalize, shorten, omit, or reinterpret.

Language of this fragment: {LANG}
Filler words for this language (remove only if safe): [{PARASITES}]
Glossary (verbatim, may be empty): {GLOSSARY_OR_DASH}
Asides style: {ASIDE_STYLE}

Tasks (Light cleanup + Reader-friendly structuring):
1) Restore correct punctuation and casing.
2) Fix only obvious slips and duplicate words that carry no meaning.
3) Keep jokes/asides; visually separate them using the specified style.
4) Markdown formatting only: suitable headings, bullet/numbered lists, **bold**/**italics** where helpful for readability.
5) No additions. Minimal word-reordering is allowed if and only if meaning remains 1:1. When unsure about a term, keep the original spelling.

Important continuity policy:
- You may be given a read-only CONTEXT to ensure continuity. It is glue only.
- The model MUST NOT repeat or output the CONTEXT. Do not paraphrase or restate it.
- The output must contain ONLY the cleaned FRAGMENT (Markdown), nothing else.
- Do not re-emit any headings or timecodes that appear only in CONTEXT.

Timecodes policy (if applicable by instructions):
- Only add timecodes to headings generated from the FRAGMENT.
- Never add or duplicate timecodes for headings that exist only in CONTEXT.
- Do not put timecodes anywhere else.

Output: Markdown ONLY (no prefixes, no explanations, no context echoes).

CONTEXT (DO NOT OUTPUT):
<<<
{CONTEXT_TEXT}
>>>

FRAGMENT (EDIT AND OUTPUT ONLY):
<<<
{CHUNK_TEXT}
>>>
