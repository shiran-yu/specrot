# Labeling instructions (given verbatim to each labeler)

`sample.json` holds 100 citations drawn at random (seed 2026) from the 1,626 citations the README
headline counts: RFC citations in the source and docs of 26 open-source projects that point at an RFC a
newer edition of the same specification has replaced. Each item has the code context (±3 lines), the
cited RFC and its title, and the RFC(s) that replace it per the RFC Editor index.

Label each item independently, from its context only, with one `label`:

- `update`: the text cites the old RFC as the specification the code or docs follow or define behaviour
  by; a reader would be better served by the replacement. This is actionable spec rot.
- `legacy`: the text deliberately refers to the old RFC: compatibility with old peers or formats, a
  history note, a list of all RFCs supported including old ones, a quote of the old text on purpose.
- `identifier`: the number is part of a name (a constant, function, file or module name), not a citation.
- `test`: test vectors or fixtures named after the RFC.
- `not-a-citation`: the match is not a reference to that IETF RFC at all.

When unsure between `update` and `legacy`, choose `legacy`. Add `note` (at most 12 words).
Output: a JSON list of `{"i": <int>, "label": <label>, "note": <text>}`, one per item, nothing else.
