### Source traceability

The source document contains stable Obsidian block identifiers attached to its
section headings. Timed sections use `^src-NNNN`; untimed sections use
`^txt-N`.

Preserve source traceability in the long summary:

- Every generated `###` or `####` section must contain a compact source
  reference on the very next line after its heading, with no blank line between
  the heading and the reference.
- Use exact existing source block identifiers. Never invent, modify, normalize,
  translate, or reconstruct an identifier.
- For a timed source section whose timestamp is displayed in the source, use:

  `↩ [[{SOURCE_LINK_PREFIX}^src-NNNN|Source · HH:MM:SS]]`

- Copy the displayed timestamp exactly in normalized `HH:MM:SS` form. If the
  source heading has no displayed timestamp, use `Source` as the link label.
- For an untimed source section, use:

  `↩ [[{SOURCE_LINK_PREFIX}^txt-N|Source]]`

- If one summary section combines material from several source sections,
  include all materially relevant references on one line:

  `↩ [[{SOURCE_LINK_PREFIX}^src-706|Source · 00:11:46]] · [[{SOURCE_LINK_PREFIX}^src-882|00:14:42]] · [[{SOURCE_LINK_PREFIX}^txt-3|Source]]`

- Prefer the smallest set of source references that covers the summarized
  material.
- Do not add a source reference merely because a section is nearby in the
  document.
- Never link a statement to a source section that does not contain or support
  it.
- Use only source IDs that literally occur in the input. Never generate a
  source ID from a timestamp or from memory.
