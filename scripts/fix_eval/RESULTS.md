# `specrot fix` precision

Two models label 100 edits drawn by `draw.py` (first 100 by a seeded hash) from everything `specrot fix`
proposes on the 26 showcase checkouts, with [LABELING.md](LABELING.md) and no tools (`../audit/label.py --dir`).

| Round | Edits proposed | Both `correct` | Claude: correct / keep / wrong | GPT: correct / keep / wrong |
|---|---|---|---|---|
| 1 (`round1/`) | 782 | 63 | 63 / 15 / 22 | 80 / 18 / 2 |
| 2 (this folder) | 709 | 67 | 67 / 20 / 13 | 87 / 13 / 0 |

Changes between the rounds, from the round-1 `wrong` labels:
- a chain with a protocol version hop (RFC 4492 -> 8422 -> TLS 1.3) is skipped: stay on 8422 or move is a decision;
- a replacement whose title names a version the old title lacks (RFC 6962 -> CT Version 2.0) is skipped;
- the label of a Markdown reference link (`[RFC 7230, section 6.3.2][]`) is not rewritten.

Round 2's 13 Claude `wrong` labels, checked by hand against the RFC text (`data/raw/txt`) and the RFC Editor index:
- 6 doubt a section number ("unverified"): 8446 §4.2.3 -> 9846 §4.3.3 and §4.2.10 -> §4.3.10 have identical
  headings, and 9846 §4.1 is "The Transcript Hash" (8446 §4.4.1). The edits are right.
- 3 keep an appendix named in prose ("RFC 4960, Appendix B", "Appendix E.6 of RFC8446", which is F.6 in
  RFC 9846): the appendix went stale. Fixed after round 2: a line that names an appendix the pattern did
  not capture is skipped (test `test_fix_skips_version_changes_and_reference_link_labels`).
- 2 dispute the RFC Editor's own `obsoletes` data (9598 obsoletes 8398; 9904 obsoletes 6944). Left as is.
- 1 rewrites a `Refs:` line whose next line already cites the replacement section (undici). `fix` works
  line by line; the diff is reviewed before `--write`.
- 1 rewrites "documented in the RFC 1867" where the next line calls it a historical name (curl). GPT
  labels it `keep` too. Same line-by-line limit.

The labels are model labels, not human ones.
