Deictic anchoring (visible, inline):
- Goal: mark deictic references (“this/that/these/those”, “цей/ця/це/ці/той/та/те/ті”, “hier/dort”, etc.) with a short visible anchor ONLY when the referent is unambiguously named earlier in THIS FRAGMENT.
- Anchor format: use the configured deictic wrapper and decoration, e.g., ⟦anchor: «<referent name>»⟧ in the fragment’s language, verbatim; no translation.
- Hard limits: ≤ {DEICTIC_MAX_PER_PARAGRAPH} per paragraph and ≤ {DEICTIC_MAX_PER_FRAGMENT} per fragment. Never inside code, math, citations, or links.
- If the referent is uncertain without inference, insert ⟦anchor: {DEICTIC_UNKNOWN}⟧ and add an end-of-block comment: <!-- unsure: deictic unresolved -->.
- Do not reorder or paraphrase. Insert the anchor immediately after the deictic token or its noun phrase (“this metric ⟦anchor: «Recall»⟧ …”).
- Do not normalize by frequency; use only names already present in THIS FRAGMENT or in the GLOSSARY (verbatim).

