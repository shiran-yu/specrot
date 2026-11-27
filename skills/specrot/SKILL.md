---
name: specrot
description: Check whether an IETF RFC is still current before citing, implementing or quoting it, and find stale RFC citations in a codebase. Use when code, docs, comments or your own answer mention an RFC number (HTTP, TLS, OAuth, JWT, DNS, email, URI, cookies, ...), when implementing a protocol, or when asked which RFC is current for a topic.
---

# specrot: is this RFC still the spec?

Your training data may predate the replacement of the RFC you are about to cite: RFC 8446 (TLS 1.3)
was obsoleted by RFC 9846 in 2026; RFC 7230-7235 by RFC 9110-9112 in 2022; RFC 7540 (HTTP/2) by
RFC 9113. specrot answers from a Relate graph of all 9,869 RFCs built from the RFC Editor index,
so check before you write.

Run commands from the specrot checkout (`uv run specrot ...`), or call the MCP tools of the same
name if the `specrot` MCP server is connected.

## Before citing or implementing an RFC

```bash
uv run specrot check 8446 7540 6749        # level, replacement chain, live updates, errata
uv run specrot check 2616 --json           # machine-readable
```

Levels, most severe first: `obsolete` (a newer edition replaced it: cite the RFC in `current`; if
`current` is empty it was retired without a replacement), `historic` (includes retired protocol
versions such as TLS 1.0 and 1.1: do not implement), `old-version` (only a newer protocol version
exists, e.g. TLS 1.2's RFC 5246: still right if you implement that version), `amended` (still in force,
but read the listed updates; deprecations are flagged), `ok`, `unknown` (no such RFC).

## In a repository

```bash
uv run specrot scan /path/to/repo                 # reader-facing citations outside tests
uv run specrot scan . --markdown                  # table for a PR comment
uv run specrot scan . --fail-on obsolete          # CI gate, exits 1
```

When fixing a finding, update the citation to the current RFC and check the section number still
matches: sections move between versions (RFC 7231 §6.5.1 became RFC 9110 §15.5.1).
Do not change citations that deliberately describe legacy behaviour (an OAuth 1.0 implementation
citing RFC 5849, a parser accepting RFC 2822 obsolete syntax).

## Other questions

```bash
uv run specrot read 9110 --depth 1     # what must I read to implement it (normative closure, depth 1-3)
uv run specrot impact 5280             # what still in force depends on it
uv run specrot search "token revocation"
uv run specrot cypher "MATCH (r:RFC {id:'RFC6749'})<-[:UPDATES]-(u) RETURN u.id, u.title"
```

Graph schema: `(:RFC)-[:OBSOLETES {kind: edition|version|split|retired}]->(:RFC)`, `(:RFC)-[:UPDATES|NORMATIVE_REF|INFORMATIVE_REF]->(:RFC)`,
`(:Series {id:'BCP14'})-[:INCLUDES]->(:RFC)`, `(:Erratum)-[:AMENDS]->(:RFC)`,
`(:RFC)-[:FROM_WG]->(:WorkingGroup)-[:IN_AREA]->(:Area)`,
`(:Project)-[:HAS_FILE]->(:File)-[:CITES {lines}]->(:RFC)` for 26 scanned open-source projects.
RFC properties: `id`, `number`, `title`, `date`, `status`, `obsolete`, `oldVersion`, `verifiedTechnicalErrata`, `url`.
Cypher is Relate's Cypher 25 (no APOC); `(r)<-[:OBSOLETES]-+(n)` follows a chain of any length.
