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
OkHttp, hyper, requests, Django, oauthlib, dnspython, ...). Of **7,596** RFC citations in source
and docs (tests and identifiers such as `time.RFC1123` excluded), **1,645 (22%)** point at an RFC
that a newer edition of the same specification has replaced, in **24 of 26** projects. Citations of
an older *protocol version* (TLS 1.2's RFC 5246, OAuth 1.0's RFC 5849, the retired TLS 1.0 and 1.1;
272 more) are not counted: they are reported as `old-version`, or `historic` when that version was
itself retired. The most common: RFC 2616 (17 projects), RFC 7230
(16), RFC 7231 (15), RFC 7540 / HTTP/2 (13). Reproduce with `uv run python scripts/showcase.py`;
per-project numbers in [`scripts/showcase-results.json`](scripts/showcase-results.json).

Not every one of these is a mistake. We drew 100 of the 1,645 at random (seed 2026,
[`scripts/audit/draw.py`](scripts/audit/draw.py)) and had two models label each from its code
context, independently, with the same [instructions](scripts/audit/LABELING.md) and no tools:
Claude Sonnet 5.5 and GPT-6 Luna (through GitHub Copilot). Both labelled **62 of 100** as citing
the old RFC as the specification the code follows, worth updating; 30 (Claude) and 28 (GPT) as
deliberate references to the old text (compatibility, history, a list of supported RFCs); none as a
false match. The labelers agree on 86% of items (Cohen's κ 0.70). These are model labels, not
human ones. [`scripts/audit/label.py`](scripts/audit/label.py) reruns a labeler, `raw/` keeps each
full prompt and reply, and [`scripts/audit/score.py`](scripts/audit/score.py) recomputes the
summary. specrot reports; a person decides, and `.specrot-ignore` records the decision.

**How big is the problem for coding agents?** We asked Claude Haiku 5.5 and Claude Sonnet 5.5 (via
`claude -p`) "which RFC is the current specification for X? If several RFCs together form it, list
them" for 34 protocols, under three conditions. **No tools:** Haiku included an obsolete RFC in its
answer for **10 of 34** (2 times alone, 8 times listed beside the current one, e.g. "RFC 8259, RFC
7159" for JSON); Sonnet gave only the obsolete RFC for **2 of 34**, exactly the two replaced in 2026
(TLS 1.3 → RFC 9846, DHCPv6 → RFC 9915). **Web search allowed:** the models searched on 16 (Haiku)
and 4 (Sonnet) of the 34 questions and still missed 1 and 2, each time answering from memory
without searching. **specrot MCP server attached:** they consulted it on every question and
answered **34 of 34**. One sample per question. The answer key is the RFC Editor's own `OBSOLETES`
data read from the graph (the documents in force at the end of the chain from each topic's classic
RFC). Prompt, questions, transcripts and script in [`scripts/agent_eval/`](scripts/agent_eval/).

**Which relationships matter:**

| Question | Graph walk |
|---|---|
| What replaced this RFC? | follow `OBSOLETES` backwards, any length, to documents nobody obsoletes (`2616 → 7230 → 9112`); each edge has a `kind`: new *edition*, newer protocol *version*, *split* into several documents, or *retired* by a deprecation notice |
| Is it still in force but changed? | `UPDATES` from documents still in force; titles saying *Deprecating/Prohibiting* are flagged; verified technical `Erratum` nodes |
| What must I read to implement it? | `NORMATIVE_REF` closure, references to `BCP`/`STD` series resolved to member RFCs, obsolete targets swapped for replacements |
| Who is affected if it changes? | `NORMATIVE_REF` backwards from documents still in force |
| Which projects still cite it? | `(:Project)-[:HAS_FILE]->(:File)-[:CITES]->(:RFC)` |

## How it uses Relate

- **Mode: single file** — [`store/rfc.rl`](store/rfc.rl) (5 MB).
- **Why this mode:** the graph is a dataset that ships with the code: one file to commit, clone,
  open read-only from the Python package, the `relate` CLI and the MCP server, and replace as a
  whole when the RFC index changes. Nothing to start, no server. Writes (`scan --save`) go to the
  same file; reads open it with `read_only=True`.
- **What the graph models:** 9,869 `RFC`s, 377 `Series` (BCP/STD/FYI), 8,215 `Erratum`, 532
  `WorkingGroup`s in 16 `Area`s, and 26 scanned `Project`s with 2,372 `File`s.
  Relationships: 1,546 `OBSOLETES`, 2,172 `UPDATES`, 58,954 `NORMATIVE_REF`, 69,790 `INFORMATIVE_REF`,
  `INCLUDES`, `AMENDS`, `FROM_WG`, `IN_AREA`, `HAS_FILE`, `CITES`. Of the normative references,
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
`scripts/export_web.py` exports because the WASM build cannot open a `.rl` file. It offers check
with a lineage graph, paste-and-scan, the 26-project table with links to the exact lines on
GitHub, and a Cypher console.

Then:

```bash
uv run specrot scan /path/to/any/repo          # stale RFC citations, with file:line and the fix
uv run specrot scan . --markdown               # a table to paste into a PR
uv run specrot scan . --fail-on obsolete       # CI gate: exit 1 on obsolete citations
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
- **Rebuild:** `uv run specrot build` downloads into `data/raw/` (git-ignored, ~1 min) and rewrites
  the store; `uv run python scripts/showcase.py` re-scans the 26 projects at the commits pinned in
  [`scripts/showcase.json`](scripts/showcase.json).
- Code: [`specrot/build.py`](specrot/build.py) (graph model and load),
  [`specrot/graph.py`](specrot/graph.py) (all queries), [`specrot/scan.py`](specrot/scan.py),
  [`specrot/mcp_server.py`](specrot/mcp_server.py).

## Limits

- "Obsolete" is the RFC Editor's relation, not a judgement of the code. The edge `kind` (edition,
  version, split, retired) is inferred from the two titles at build time (deprecation wording;
  differing version numbers in a *protocol's* title, as in TLS 1.2 → 1.3, while PKCS #1 v2.1 → v2.2
  is a new edition; number of successors), so it can be wrong for an unusual title. All 19
  `version` edges are listed by `MATCH (n)-[e:OBSOLETES {kind:'version'}]->(o) RETURN o.title, n.title`.
  Citations that deliberately describe legacy behaviour are reported like any other; list them in
  `.specrot-ignore`.
- Citations are found with a regular expression. Media types such as `message/rfc822` are skipped;
  identifiers (`time.RFC1123`, `rfc2822_date`) and test files are excluded by default
  (`--all-kinds` includes them). Section numbers are kept but not mapped to the new document.
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
