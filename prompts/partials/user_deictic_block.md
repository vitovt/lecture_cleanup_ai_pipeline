Deictic anchoring:
- Enabled: {DEICTIC_MODE} ; valid: on | off
- Max per paragraph: {DEICTIC_MAX_PER_PARAGRAPH}
- Max per fragment: {DEICTIC_MAX_PER_FRAGMENT}
- Unknown marker: {DEICTIC_UNKNOWN}
- Lookback window: {DEICTIC_WINDOW_SENTENCES} sentences within the FRAGMENT (ignore CONTEXT)
- Allowed referent sources (priority):
  1) Explicit labels in THIS FRAGMENT (table headers/rows, axis labels, legend entries, list heads)
  2) Headings/subheadings within THIS FRAGMENT
  3) GLOSSARY terms (verbatim)
- Placement: insert immediately after the deictic token or its noun phrase.
- Wrapper/decoration: use the configured deictic wrapper and decoration (not the general aside style).
- Never anchor inside code blocks, math, citations, or links.
- The language-specific deictic word list is indicative, not exhaustive. Rely on context and meaning first; do NOT anchor purely by keyword match.

Wrapper settings:
- Wrapper open: {DEICTIC_WRAPPER_OPEN}
- Wrapper close: {DEICTIC_WRAPPER_CLOSE}
- Prefix: {DEICTIC_PREFIX}
- Name quotes: {DEICTIC_NAME_QUOTES_OPEN}…{DEICTIC_NAME_QUOTES_CLOSE}
- Decorate: {DEICTIC_DECORATE}

Language deictic hints (indicative only): [{DEICTIC_HINTS}]

