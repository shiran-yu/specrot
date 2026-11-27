# Labeling instructions (given verbatim to each labeler)

`sample.json` holds 100 edits that `specrot fix` proposes in 26 open-source projects. Each item has the
original line (`old`), the rewritten line (`new`), what changed (`change`: old RFC and section → new RFC
and section) and the code context (±3 lines). The replacements come from the RFC Editor's "obsoletes"
data; sections are mapped by matching headings.

Label each item independently, from its context only, with one `label`:

- `correct`: a maintainer could merge this line as is: the text cites the old RFC as the specification
  the code follows, and the new RFC (and section, if any) says the same thing for this purpose.
- `keep`: the old citation is deliberate (legacy behaviour, compatibility, history, a quotation, a list
  of supported RFCs, a protocol or file-format name); the line should not change.
- `wrong`: the line should change, but this rewrite is wrong (wrong document, wrong section, broken text).

When unsure between `correct` and another label, choose the other label. Add `note` (at most 12 words).
Output: a JSON list of `{"i": <int>, "label": <label>, "note": <text>}`, one per item, nothing else.
