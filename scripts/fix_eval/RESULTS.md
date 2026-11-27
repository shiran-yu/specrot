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

## Held-out round (`holdout/`)

Fixer frozen at commit 654610a, then `draw.py --holdout`: a new hash salt over the 601 proposed edits that
were not in round 1 or 2 (no line labelled before). Same instructions, same two models.

| Both `correct` | Claude: correct / keep / wrong | GPT: correct / keep / wrong | Both `wrong` | Agreement |
|---|---|---|---|---|
| **74** | 75 / 13 / 12 | 81 / 10 / 9 | 9 | 92% |

The 9 edits both call wrong:
- 4 leave a section number stale that the pattern did not capture: wrapped onto the next line ("RFC 8446,
  Section" / "4.2.11.2"), the slash form "RFC 7231/6.4.4", and a Markdown link definition `[RFC 8446]:`
  whose URL is on the next line. Fixed after this round (tests in
  `test_fix_skips_version_changes_and_reference_link_labels`); this round's numbers are not recomputed.
- 2 map RFC 7230 §3.2 "Header Fields" to RFC 9110 §6.3 "Header Fields" by its identical heading, while the
  field syntax moved to RFC 9110 §5 "Fields": a limit of mapping by heading.
- 1 next-line URL still names RFC 7231 (haproxy); 1 sentence about RFC 6125 is no longer true of RFC 9525
  (CPython); 1 follows the RFC Editor's "RFC 2854 obsoletes RFC 1866" where the cited rule did not move (Django).
