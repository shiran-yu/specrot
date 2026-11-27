# specrot

Find the dead RFCs your code still cites. specrot puts every IETF RFC and how they relate into one
Relate graph file, so a developer, a CI job or a coding agent can ask "is this still the spec, and
if not, what replaced it?"

```console
$ uv run specrot check 8446
✗ OBSOLETE  RFC8446  The Transport Layer Security (TLS) Protocol Version 1.3  (2018-08, Proposed Standard)
├── replaced by (OBSOLETES chains to documents still in force)
│   └── RFC8446 → RFC9846  The Transport Layer Security (TLS) Protocol Version 1.3  (new edition of the same specification)
└── 11 verified technical errata  https://www.rfc-editor.org/errata/rfc8446
```

## Use case

Protocol code is full of comments like `// see RFC 7230, section 3.3.2`. RFCs are never edited
after publication; they are *obsoleted* or *updated* by later RFCs. HTTP/1.1 has been rewritten
twice since RFC 2616 (RFC 7230–7235 in 2014, RFC 9110–9112 in 2022), TLS 1.3's own RFC 8446 was
replaced by RFC 9846 in July 2026, and OAuth 2.0 (RFC 6749) is amended by a security best practice
(RFC 9700) that deprecates parts of it. A citation that was right when it was written quietly
starts pointing a reader, a reviewer or an AI coding agent at the wrong text.

**Who benefits:** maintainers of protocol libraries (HTTP clients and servers, TLS stacks, DNS,
mail, OAuth/JWT), security reviewers checking that an implementation follows the current spec,
and coding agents, whose training data predates recent replacements.

**How big is the problem in code?** We scanned 26 well-known open-source projects at pinned commits
(curl, CPython's `Lib`, Go's `net` and `crypto`, Node, undici, OpenSSL, nginx, HAProxy, Netty,
OkHttp, hyper, requests, Django, oauthlib, dnspython, ...). Of **8,044** RFC citations in source
and docs (Sphinx `:rfc:` roles included; tests and identifiers such as `time.RFC1123` excluded), **1,687 (21%)** point at an RFC
that a newer edition of the same specification has replaced, in **24 of 26** projects. Citations of
an older *protocol version* (TLS 1.2's RFC 5246, OAuth 1.0's RFC 5849, the retired TLS 1.0 and 1.1;
303 more) are not counted: they are reported as `old-version`, or `historic` when that version was
itself retired. The most common: RFC 2616 (18 projects), RFC 7230
(16), RFC 7231 (15), RFC 7540 / HTTP/2 (13). Reproduce with `uv run python scripts/showcase.py`;
per-project numbers in [`scripts/showcase-results.json`](scripts/showcase-results.json).

Not every one of these is a mistake. We took 100 of the 1,687, the first by a seeded hash
([`scripts/audit/draw.py`](scripts/audit/draw.py)), and had two models label each from its code
context, independently, with the same [instructions](scripts/audit/LABELING.md) and no tools:
Claude Sonnet 5.5 and GPT-6 Luna (through GitHub Copilot). Both labelled **49 of 100** as citing
the old RFC as the specification the code follows, worth updating (58 Claude, 53 GPT); 34 and 42 as
deliberate references to the old text (compatibility, history, a list of supported RFCs); 8 and 5
as scanner errors (an identifier or not a citation at all). The labelers agree on 78% of items
(Cohen's κ 0.60). These are model labels, not human ones, and they vary between runs: earlier runs on samples
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
edit for 49 of the 106 (`scan` reports all of them) and names the maintainers' RFC in **46 of 49**; of 19
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

**Which relationships matter:**

| Question | Graph walk |
|---|---|
| What replaced this RFC? | follow `OBSOLETES` backwards, any length, to documents nobody obsoletes (`2616 → 7230 → 9112`); each edge has a `kind`: new *edition*, newer protocol *version*, *split* into several documents, or *retired* by a deprecation notice |
| Is it still in force but changed? | `UPDATES` from documents still in force; titles saying *Deprecating/Prohibiting* are flagged; verified technical `Erratum` nodes |
| What must I read to implement it? | `NORMATIVE_REF` closure, references to `BCP`/`STD` series resolved to member RFCs, obsolete targets swapped for replacements |
| Who is affected if it changes? | `NORMATIVE_REF` backwards from documents still in force |
| Where does section 6.5.1 of RFC 7231 live now? | `(:Section)-[:CONTINUES_AS]->+(:Section)` to a section of a document still in force: §6.5.1 *400 Bad Request* → RFC 9110 §15.5.1; 2616 §14.20 → 7231 → 9110 §10.1.1 |
| Which projects still cite it? | `(:Project)-[:HAS_FILE]->(:File)-[:CITES]->(:RFC)` |

## How it uses Relate

- **Mode: single file** — [`store/rfc.rl`](store/rfc.rl) (8 MB).
- **Why this mode:** the graph is a dataset that ships with the code: one file to commit, clone,
  open read-only from the Python package, the `relate` CLI and the MCP server, and replace as a
  whole when the RFC index changes. Nothing to start, no server. Writes (`scan --save`) go to the
  same file; reads open it with `read_only=True`.
- **What the graph models:** 9,869 `RFC`s, 377 `Series` (BCP/STD/FYI), 8,215 `Erratum`, 532
  `WorkingGroup`s in 16 `Area`s, 51,671 `Section`s, and 26 scanned `Project`s with 2,442 `File`s.
  Relationships: 1,546 `OBSOLETES`, 2,172 `UPDATES`, 58,954 `NORMATIVE_REF`, 69,790 `INFORMATIVE_REF`,
  `INCLUDES`, `AMENDS`, `FROM_WG`, `IN_AREA`, `HAS_FILE`, `CITES`, `HAS_SECTION`, and 29,352
  `CONTINUES_AS` between sections of an RFC and its replacements (27,799 with an identical heading). Of the normative references,
  42,164 are RFC→RFC as recorded by the Datatracker, 8,112 point at a BCP/STD series, and 8,678 are
  derived from those series' members (marked `{via: 'BCP14'}`).
- **Relate features used:** embedded Python API (`relate-db`), Cypher 25 quantified path patterns
  (`(r)<-[:OBSOLETES]-+(n)`), hop-by-hop traversal over id sets for the normative closure,
  `EXISTS {}` / `COUNT {}` subqueries,
  uniqueness constraints and indexes, a BM25 `FULLTEXT INDEX` with the `SEARCH` clause, the
  `relate` CLI (`clone` to compact the store, `serve --mcp` / `--bolt` for exploration), and an MCP
  server of our own for agents.

```
(:RFC)-[:OBSOLETES {kind}]->(:RFC)           (:RFC)-[:UPDATES]->(:RFC)        (:Series)-[:INCLUDES]->(:RFC)
(:RFC)-[:NORMATIVE_REF|INFORMATIVE_REF]->(:RFC|:Series)
(:Erratum)-[:AMENDS]->(:RFC)                 (:RFC)-[:FROM_WG]->(:WorkingGroup)-[:IN_AREA]->(:Area)
(:Project)-[:HAS_FILE]->(:File)-[:CITES {lines, readerLines, sections}]->(:RFC)
(:RFC)-[:HAS_SECTION]->(:Section)-[:CONTINUES_AS {exact}]->(:Section)
```

## Setup and run

Prerequisites: Python 3.10+ and [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
No account, key or server.

```bash
git clone https://github.com/shiran-yu/specrot && cd specrot
uv run specrot check 2616 8446 6749     # first run installs dependencies (~10 s)
```

Without uv: `python -m venv .venv && . .venv/bin/activate && pip install -e . && specrot check 2616`.

**No install at all:** open the [in-browser explorer](https://shiran-yu.github.io/specrot/) (or
`python3 -m http.server -d docs 8000` in a clone). It runs the Relate WebAssembly build in the tab
and rebuilds a subset of the graph there in about 3 s: RFCs, series, `OBSOLETES` with kinds,
`UPDATES`, the 50,842 RFC-level normative references and the 26 projects (no errata, working groups
or informative references), from [`docs/data/graph.json`](docs/data/graph.json), which
`scripts/export_web.py` exports because the WASM build cannot open a `.rl` file. The sections and
`CONTINUES_AS` load from `docs/data/sections.json` on the first section lookup
([`#rfc=7231&s=6.5.1`](https://shiran-yu.github.io/specrot/#rfc=7231&s=6.5.1)). It offers check
with a lineage graph and section lookup, paste-and-scan, the 26-project table with links to the exact lines on
GitHub, and a Cypher console.

Then:

```bash
uv run specrot scan /path/to/any/repo          # stale RFC citations, with file:line and the fix
uv run specrot scan . --markdown               # a table to paste into a PR
uv run specrot scan . --fail-on obsolete       # CI gate: exit 1 on obsolete citations
uv run specrot fix .                           # unified diff: RFC and section rewritten where unambiguous
uv run specrot check "RFC 7231 §6.5.1"         # where that section lives now (RFC 9110 §15.5.1)
uv run specrot read 9110 --depth 2             # normative reading list for an implementation (depth 1-3)
uv run specrot impact 5280                     # what still in force depends on RFC 5280 (depth 1-3)
uv run specrot check "BCP 14" "STD 66"         # series resolve to their member RFCs
uv run specrot search "token revocation"       # full-text search over titles and abstracts
uv run specrot cypher "MATCH (p:Project)-[:HAS_FILE]->()-[:CITES]->(r:RFC {id:'RFC2616'}) RETURN DISTINCT p.name"
```

### In CI

```yaml
# .github/workflows/specrot.yml
on: [pull_request]
jobs:
  specrot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: shiran-yu/specrot@main      # writes a report to the job summary, fails on obsolete citations
```

Citations that deliberately describe legacy behaviour go in a `.specrot-ignore` at the scanned root:

```
RFC5849  oauthlib/oauth1/*   # this module implements OAuth 1.0
RFC5246                      # we still ship TLS 1.2
```

### For coding agents

MCP server (tools `check_rfcs`, `scan_path`, `scan_text`, `reading_list`, `dependents`,
`search_rfcs`, `get_schema`, `read_cypher`; bad input comes back as an error message that says how
to fix the call):

```bash
claude mcp add specrot -- uv run --directory "$PWD" specrot mcp
```

Skill: copy [`skills/specrot`](skills/specrot/SKILL.md) into `.claude/skills/` (or your agent's
skills folder). It tells the agent to check an RFC before citing or implementing it.

### Explore the raw graph

With the [Relate CLI](https://relatedb.ai/docs/get-started/install/)
(`curl -sSfL https://relatedb.ai/install.sh | bash`):

```bash
relate query --database store/rfc.rl --read-only                    # interactive Cypher shell
relate serve --database store/rfc.rl --read-only --mcp stdio        # Relate's own MCP server
relate serve --database store/rfc.rl --read-only --bolt 7687 --bolt-identity Neo4j/5.26.0
```

Some queries to try:

```cypher
// the longest replacement chain in the RFC series (32 hops, 1988 to 2013)
MATCH p = (old:RFC)<-[:OBSOLETES]-+(new:RFC)
WHERE NOT new.obsolete AND NOT EXISTS { (old)-[:OBSOLETES]->() }
RETURN length(p) AS hops, [x IN nodes(p) | x.id] AS chain, new.title ORDER BY hops DESC LIMIT 3;

// documents still in force that normatively cite an obsolete RFC
MATCH (a:RFC)-[:NORMATIVE_REF]->(b:RFC) WHERE NOT a.obsolete AND b.obsolete
RETURN b.id, b.title, count(a) AS citedBy ORDER BY citedBy DESC LIMIT 10;
```

## Where the data lives

- **Store:** [`store/rfc.rl`](store/rfc.rl), a single-file Relate store, committed.
- **Sources** (metadata only, no RFC full text): the
  [RFC Editor index](https://www.rfc-editor.org/rfc-index.xml), the
  [RFC Editor errata API](https://www.rfc-editor.org/api/v1/errata.json) (submitter names dropped),
  and normative/informative references from the
  [IETF Datatracker API](https://datatracker.ietf.org/api/v1/doc/relateddocument/).
- **Rebuild:** `uv run specrot build` downloads into `data/raw/` (git-ignored; ~1 min, plus ~40 min once for the 2,221 RFC texts used for sections) and rewrites
  the store; `uv run python scripts/showcase.py` re-scans the 26 projects at the commits pinned in
  [`scripts/showcase.json`](scripts/showcase.json).
- Code: [`specrot/build.py`](specrot/build.py) (graph model and load),
  [`specrot/graph.py`](specrot/graph.py) (all queries), [`specrot/scan.py`](specrot/scan.py),
  [`specrot/mcp_server.py`](specrot/mcp_server.py).

## Limits

- "Obsolete" is the RFC Editor's relation, not a judgement of the code. The edge `kind` (edition,
  version, split, retired) is inferred from the two titles at build time (deprecation wording;
  differing version numbers in a *protocol's* title, as in TLS 1.2 → 1.3, IMAP 4rev1 → 4rev2,
  RTSP → RTSP 2.0, while PKCS #1 v2.1 → v2.2 is a new edition and IPv6 or HTTP/1.1 in a title is not
  a version change; tests in `tests/test_specrot.py::test_obsoletes_kind`; number of successors), so it can be wrong for an unusual title. All 45
  `version` edges are listed by `MATCH (n)-[e:OBSOLETES {kind:'version'}]->(o) RETURN o.title, n.title`.
  Six edges are marked `redesign` by hand, each with its reason (`build.REDESIGN`: RFC 6874 → 9844,
  TCP MD5 → TCP-AO, HTML 2.0 and form upload → text/html, BSD syslog → RFC 5424, Cookie2 → RFC 6265):
  the replacement is a different design, so `fix` leaves those citations to a person. Only the 76
  pairs `fix` proposes on the 26 projects were reviewed; other edges may hide the same case.
  Citations that deliberately describe legacy behaviour are reported like any other; list them in
  `.specrot-ignore`.
- Citations are found with a regular expression. Media types such as `message/rfc822` are skipped;
  identifiers (`time.RFC1123`, `rfc2822_date`) and test files are excluded by default
  (`--all-kinds` includes them).
- Sections are mapped by heading: a section continues as the section of the replacement with the
  same heading (a near-identical one is marked `~`/reworded and never rewritten by `fix`). Of the 297
  distinct obsolete (RFC, section) pairs cited in the 26 projects, 223 have a home in a current RFC
  (208 by identical heading; `facts.json` `sections`); a section whose content moved under a new heading
  gets none, and about 1% of headings parsed from the plain text are noise (addresses, ASN.1 lines). The
  headings come from the RFC Editor's plain-text RFCs (`data/raw/txt`, fetched by `specrot build`).
- `specrot fix` rewrites only unambiguous citations and prints a diff; it leaves code names
  (`RFC_4122`, `rfc_822`), protocol strings (`RFC822.TEXT`), quoted examples, lines that already talk
  about history or the replacement, and files that are not UTF-8 alone, and `--write` changes only the
  lines in the diff. It also skips chains that change protocol version and appendices named in prose.
  On a held-out sample of 100 edits (the fixer frozen first, no line seen in the earlier rounds), both
  model labelers called **74** mergeable as is and 9 wrong; 4 of the 9 were stale section numbers the
  pattern missed, fixed since, and 2 a section mapped by an identical heading whose content moved
  ([`scripts/fix_eval/RESULTS.md`](scripts/fix_eval/RESULTS.md), with the two earlier rounds). 34 to 42 of 100 stale citations are
  deliberate (the audit above), so a person reviews the diff before committing.
- The Datatracker records references for most RFCs, but not for every early one (pre-1990s RFCs
  mostly have none).
- The store reflects the sources on the day it was built (see `git log store/rfc.rl`).

Levels used everywhere (CLI, MCP, CI, browser), most severe first: `obsolete` (a newer edition
replaced it, or it was retired), `historic` (including retired protocol versions such as TLS 1.0
and 1.1), `old-version` (only a newer protocol version exists, the old one is still in use: TLS 1.2),
`amended` (in force, updated or with verified technical errata), `ok`, `unknown` (not in the index).

## Built with

Relate 1.3 (`relate-db` Python package, Relate CLI), Python, rich, the MCP Python SDK.
AI tools: the code, data pipeline and docs were written with Claude Code (Anthropic). The audit
labels come from two models (Claude and a GPT model through GitHub Copilot), not from people; the
agent evaluation runs Claude models through the `claude` CLI.
This is a new project started for the Relate by Neo4j Hackathon; no earlier code is reused.

MIT licence. RFC metadata © IETF Trust, used under the IETF Trust Legal Provisions.
