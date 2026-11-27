# specrot against maintainers' own citation updates

Maintainers of the scanned projects have merged PRs that do what `specrot fix` does: replace citations
of obsolete RFCs. `run.py` takes eight of them (GitHub search: merged PRs with "RFC" in the title in the
26 projects, kept when the diff replaces citations), runs `specrot fix` on each PR's base files and compares
with the merged files. Nobody on this project wrote or chose these edits. Details per line: `results.json`.

| PR | Merged | Replaced citations | Obsolete per specrot | `fix` proposed | Same RFC as the maintainers |
|---|---|---|---|---|---|
| [python/cpython#139435](https://github.com/python/cpython/pull/139435) "Update selected RFC 2822 references to RFC 5322" | 2025-11 | 17 | 17 | 10 | 10 |
| [python/cpython#151275](https://github.com/python/cpython/pull/151275) base64 docstring → RFC 4648 | 2026-06 | 3 | 3 | 2 | 2 |
| [python/cpython#27700](https://github.com/python/cpython/pull/27700) base64 docs → RFC 4648 | 2021-08 | 1 | 1 | 1 | 1 |
| [python/cpython#148](https://github.com/python/cpython/pull/148) RFC 1750 / 3280 / 4366 references | 2017-06 | 5 | 5 | 1 | 1 |
| [django/django#16257](https://github.com/django/django/pull/16257) "Updated documentation and comments for RFC updates" | 2022-11 | 30 | 29 | 11 | 11 |
| [nghttp2/nghttp2#1809](https://github.com/nghttp2/nghttp2/pull/1809) README: new HTTP/2 RFC (kept RFC 7540, added RFC 9113) | 2022-10 | 0 | 0 | 0 | 0 |
| [psf/requests#2087](https://github.com/psf/requests/pull/2087) "Update trivial mentions to RFC 2616" | 2014-06 | 3 | 3 | 0 | 0 |
| [urllib3/urllib3#409](https://github.com/urllib3/urllib3/pull/409) "Update references to RFC 2616" | 2014-06 | 3 | 3 | 1 | 0 |
| **Total** | | **62** | **61** | **26** | **25** |

- **Detection:** specrot calls 61 of the 62 replaced citations obsolete. The 62nd is RFC 1123 (Django), which
  is in force; the maintainers chose to cite RFC 5322's date format instead.
- **Agreement:** where `fix` proposes an edit, it names the RFC the maintainers chose in 25 of 26. The
  26th is a 2014 PR that moved to RFC 7231, which RFC 9110 has replaced since; `fix` proposes RFC 9110
  §15.4.4, the same "303 See Other" section. Of the 9 proposals that carry a section number, 7 name the
  section the maintainers wrote (RFC 7232 §3.1 → RFC 9110 §13.1.1, §4.1 → §15.4.5, RFC 7231 §7.1.1.1 → §5.6.7, ...).
- **Not proposed (36):** 16 citation forms `fix` does not rewrite (quoted text, history wording,
  sections it cannot map safely), 9 in test files (excluded by default), 1 RFC still in force (RFC 1123),
  6 RFCs split across several documents (RFC 2616, 7230), 3 sections with no single matching heading and
  1 chain with a protocol version change. `specrot scan` reports the 26 that are obsolete and outside tests.
- **Lines the maintainers left:** in cpython#139435 `fix` would also change 16 lines the PR did not touch:
  10 cite other RFCs (outside that PR's scope), 6 cite RFC 822/2822 and were left by the maintainers
  (the PR title says "selected"; one is a note that RFC 822 gets time-zone signs wrong). They are still on
  `main` today. A person reviews the diff.
- **Changes made while building this comparison** (each with a test): `fix` now skips a second section
  after the first ("section 14.4 and 3.9", Django) and plural sections before the citation
  ("sections 2.2 and 2.3 of RFC 2396"). The table is the result after both.
- Today's graph is used for every PR, so older PRs are judged against today's replacements.
