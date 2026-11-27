# specrot against maintainers' own citation updates

Maintainers of the scanned projects merge PRs that do by hand what `specrot fix` does: replace citations
of obsolete RFCs. Nobody on this project wrote or chose these edits.

**Cohort** ([`cohort.py`](cohort.py), every candidate and reason in [`cohort.json`](cohort.json)): the GitHub
search `repo:<r> is:pr is:merged RFC in:title` over the 26 scanned projects gives 198 candidates (Go, curl,
OpenSSL and HAProxy merge outside GitHub PRs and give none; okhttp could not be searched). A PR is included
when, in some modified file, a removed line cites RFC N and the added lines cite another RFC and not N; this
rule does not use specrot's graph. 34 PRs pass; 17 of them are backports of another PR (title starting with
"["), which leaves **17 PRs**.

**Method** ([`run.py`](run.py), per line in [`results.json`](results.json)): fetch each PR's changed files at
its base and merge commits, run `specrot fix` on the base files, and compare every citation the maintainers
replaced (cited on a changed base line, absent from the merged block) with fix's proposal. Citations
include Sphinx `:rfc:` roles. Today's graph is used, so a 2014 PR is judged against today's replacements.

| PR | Merged | Replaced citations | Obsolete per specrot | `fix` proposed | Same RFC as the maintainers | `fix` edits on lines the PR left |
|---|---|---|---|---|---|---|
| [aio-libs/aiohttp#7661](https://github.com/aio-libs/aiohttp/pull/7661) Update Python parser for RFCs 9110/9112 | 2023-10 | 2 | 2 | 1 | 0 | 3 |
| [django/django#16257](https://github.com/django/django/pull/16257) Updated documentation and comments for RFC updates | 2022-11 | 54 | 53 | 21 | 21 | 0 |
| [django/django#12142](https://github.com/django/django/pull/12142) Used more specific links to RFCs | 2019-11 | 1 | 1 | 1 | 1 | 3 |
| [django/django#11132](https://github.com/django/django/pull/11132) Updated spelling and RFCs in HttpOnly cookie docs | 2019-03 | 2 | 2 | 0 | 0 | 0 |
| [nghttp2/nghttp2#2855](https://github.com/nghttp2/nghttp2/pull/2855) CertLookupTree based on RFC 9525 rules | 2026-09 | 1 | 1 | 1 | 0 | 2 |
| [nghttp2/nghttp2#2854](https://github.com/nghttp2/nghttp2/pull/2854) Client TLS certificate validation based on RFC 9525 | 2026-09 | 1 | 1 | 1 | 1 | 3 |
| [nodejs/node#58753](https://github.com/nodejs/node/pull/58753) doc: fix wrong RFC number in http2 | 2025-06 | 2 | 0 | 0 | 0 | 3 |
| [psf/requests#2087](https://github.com/psf/requests/pull/2087) Update trivial mentions to RFC 2616 | 2014-06 | 3 | 3 | 0 | 0 | 0 |
| [python/cpython#153126](https://github.com/python/cpython/pull/153126) Fix RFC references in imaplib | 2026-07 | 3 | 3 | 0 | 0 | 0 |
| [python/cpython#151275](https://github.com/python/cpython/pull/151275) `base64` docstring → RFC 4648 | 2026-06 | 3 | 3 | 2 | 2 | 0 |
| [python/cpython#142262](https://github.com/python/cpython/pull/142262) Docs: fix RFC index reference for TLS 1.3 | 2025-12 | 2 | 0 | 0 | 0 | 3 |
| [python/cpython#139435](https://github.com/python/cpython/pull/139435) Update selected RFC 2822 references to RFC 5322 | 2025-11 | 22 | 22 | 15 | 15 | 17 |
| [python/cpython#27700](https://github.com/python/cpython/pull/27700) updated RFC references (base64) | 2021-08 | 4 | 4 | 4 | 4 | 0 |
| [python/cpython#24137](https://github.com/python/cpython/pull/24137) Fix id of 'Internet Message Format' RFC | 2021-04 | 2 | 0 | 0 | 0 | 2 |
| [python/cpython#173](https://github.com/python/cpython/pull/173) Update urllib quoting to RFC 3986 | 2017-02 | 2 | 2 | 1 | 1 | 10 |
| [python/cpython#148](https://github.com/python/cpython/pull/148) Updated reference for RFC 1750 and RFC 3280 | 2017-06 | 6 | 6 | 1 | 1 | 3 |
| [urllib3/urllib3#409](https://github.com/urllib3/urllib3/pull/409) Update references to RFC 2616 | 2014-06 | 3 | 3 | 1 | 0 | 0 |
| **Total (17 PRs)** | | **113** | **106** | **49** | **46** | **49** |

- **Detection.** specrot calls 106 of the 113 replaced citations obsolete. The other 7 are not obsolescence:
  6 correct a wrong RFC number (RFC 8466 for 8446, 5233 for 5322, 1993 in node) and 1 swaps RFC 1123, in
  force, for RFC 5322 (Django). Every replaced citation of an obsolete RFC is flagged.
- **Proposals.** `fix` proposes an edit for 49 of the 106 (46%); `specrot scan` reports the rest. The others
  are forms it does not rewrite (quoted text, history wording, sections it cannot map), test files,
  RFCs split across several documents (RFC 2616, 7230) and chains with a version change.
- **Agreement.** In 46 of the 49 proposals `fix` names the RFC the maintainers chose. The 3 others: a 2014
  PR whose target, RFC 7231, has been replaced since (fix: RFC 9110 §15.4.4, the same "303 See Other"
  section); aiohttp moved RFC 7230 §3.1.1 "Request Line" to RFC 9110 where fix proposes RFC 9112 §3
  "Request Line"; nghttp2 deleted the line instead. Of 19 proposals with a section number, 16 name the
  section the maintainers wrote (RFC 7232 §3.1 → RFC 9110 §13.1.1, §4.1 → §15.4.5, RFC 7231 §7.1.1.1 → §5.6.7).
- **Lines the PRs left.** `fix` would also change 49 lines the PRs did not touch: mostly other RFCs outside
  each PR's scope (cpython#173 is about urllib quoting, its file cites much else), and in cpython#139435
  ("selected" in its title) 6 RFC 822/2822 lines the maintainers left, still on `main`. A person reviews the diff.
- **Changes made while building this** (each with a test): `fix` skips a second section after the first
  ("section 14.4 and 3.9"), plural sections before the citation ("sections 2.2 and 2.3 of RFC 2396"), and
  `scan`/`fix` now read Sphinx `:rfc:` roles, which a judge found missing (the first version of this table
  counted 62 replacements because roles were invisible). The table is the result after these changes.
- Rerun: `cohort.py` and `run.py` need a `GITHUB_TOKEN` (60 unauthenticated API calls an hour are not enough).
