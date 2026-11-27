# specrot: evidence

The measurements behind the README's numbers, each with the script that reproduces it. Numbers come from `facts.json` (regenerate with `scripts/facts.py`); `tests/test_facts.py` checks them against this file and the README.

**How big is the problem in code?** We scanned 26 well-known open-source projects at pinned commits
(curl, CPython's `Lib`, Go's `net` and `crypto`, Node, undici, OpenSSL, nginx, HAProxy, Netty,
OkHttp, hyper, requests, Django, oauthlib, dnspython, ...). Of **8,034** RFC citations in source
and docs (Sphinx `:rfc:` roles included; tests and identifiers such as `time.RFC1123` excluded), **1,604 (20%)** point at an RFC
that a newer edition of the same specification has replaced, in **24 of 26** projects. Citations of
an older *protocol version* (TLS 1.2's RFC 5246 and its extensions, OAuth 1.0's RFC 5849, Certificate
Transparency v1, the retired TLS 1.0 and 1.1; 376 more) are not counted: they are reported as `old-version`, or `historic` when that version was
itself retired. The most common: RFC 2616 (18 projects), RFC 7230
(16), RFC 7231 (15), RFC 7540 / HTTP/2 (13). Reproduce with `uv run python scripts/showcase.py`;
per-project numbers in [`scripts/showcase-results.json`](scripts/showcase-results.json).

Not every one of these is a mistake. We took 100 of them (then 1,687), the first by a seeded hash
([`scripts/audit/draw.py`](scripts/audit/draw.py)), and had two models label each from its code
context, independently, with the same [instructions](scripts/audit/LABELING.md) and no tools:
Claude Sonnet 5.5 and GPT-6 Luna (through GitHub Copilot). Both labelled **49 of 100** as citing
the old RFC as the specification the code follows, worth updating (58 Claude, 53 GPT); 34 and 42 as
deliberate references to the old text (compatibility, history, a list of supported RFCs); 8 and 5
as scanner errors (an identifier or not a citation at all). The labelers agree on 78% of items
(Cohen's κ 0.60). Three of the 100, Certificate Transparency v1 (RFC 6962) cited by HAProxy and Go,
are no longer counted: both labelers had called them deliberate, and CT 2.0 is now a `version` edge,
so the labelled sample is kept as drawn. These are model labels, not human ones, and they vary between runs: earlier runs on samples
sharing 95 or more of these items gave 62 and 54 (git history of `scripts/audit/`). [`scripts/audit/label.py`](scripts/audit/label.py)
reruns a labeler into new files, `raw/` keeps each full prompt, reply and model (the instructions
still name the earlier population, 1,645, as given to the labelers), and
[`scripts/audit/score.py`](scripts/audit/score.py) recomputes the summary. specrot reports; a person
decides, and `.specrot-ignore` records the decision.

**Do maintainers make these changes?** Yes, by hand. CPython merged "Update selected RFC 2822 references
to RFC 5322" in 2025; Django merged "Updated documentation and comments for RFC updates" in 2022. A fixed
GitHub search over the 26 projects, with a rule that does not use specrot, finds 17 merged PRs that
replace RFC citations ([`scripts/maintainer_eval/`](scripts/maintainer_eval/RESULTS.md), every candidate
and reason in `cohort.json`). Replaying them: maintainers replaced **113** citations; specrot calls **106**
obsolete, and the other 7 correct a wrong RFC number or swap an RFC that is in force. `fix` proposes an
edit for 50 of the 106 (`scan` reports all of them) and names the maintainers' RFC in **47 of 50**; of 19
proposals with a section, 16 match the maintainers' section (RFC 7232 §3.1 → RFC 9110 §13.1.1). Nobody
on this project chose these edits; two `fix` rules and Sphinx `:rfc:` support were added while building
the comparison, which RESULTS.md lists.

**Upstream PRs from specrot (open):** [nginx/nginx#2051](https://github.com/nginx/nginx/pull/2051) (RFC 8941 →
RFC 9651 in the Priority parser comments, qualified after review: the parser keeps RFC 8941's types) and
[encode/httpx#3874](https://github.com/encode/httpx/pull/3874) (RFC 7230/7231 → RFC 9110 sections). Both
were generated with `specrot fix` and reviewed line by line before opening.

**How big is the problem for coding agents?** We asked Claude Haiku 5.5 and Claude Sonnet 5.5 (via
`claude -p`) "which RFC is the current specification for X? If several RFCs together form it, list
them" for 34 protocols, under three conditions. **No tools:** Haiku included an obsolete RFC in its
answer for **10 of 34** (2 times alone, 8 times listed beside the current one, e.g. "RFC 8259, RFC
7159" for JSON); Sonnet gave only the obsolete RFC for **2 of 34**, exactly the two replaced in 2026
(TLS 1.3 → RFC 9846, DHCPv6 → RFC 9915). **Web search allowed** (the only tools in that arm): the
models took more than one turn, i.e. called a tool, on 16 (Haiku) and 4 (Sonnet) of the 34 questions
and still named an obsolete RFC for 1 and 2, each time in a one-turn answer from memory. **specrot
MCP server attached** (its tools only): every answer took a tool call and none named an obsolete
RFC, **34 of 34**; 32 (Haiku) and 33 (Sonnet) named every RFC of the current specification, the
others one part of a split (RFC 9112 alone for HTTP/1.1). One sample per question, so single
answers vary between runs (5 of Haiku's 10 no-tool misses were right, without a tool call, in the web
arm); turns, not tool traces, are recorded. The answer key is the RFC Editor's own `OBSOLETES`
data read from the graph (the documents in force at the end of the chain from each topic's classic
RFC); [`check_key.py`](scripts/agent_eval/check_key.py) checks, against the RFC Editor's per-RFC
records (`obsoleted_by`) outside the graph, that no RFC in any of the 34 keys is obsoleted and that each
seed RFC not in its key is. It does not check that a key lists every part of a split. Prompt, questions, answers and script in [`scripts/agent_eval/`](scripts/agent_eval/).
