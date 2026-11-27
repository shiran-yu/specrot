"""MCP server (stdio) so a coding agent checks spec currency before it cites or implements an RFC.

    claude mcp add specrot -- uv run --directory /path/to/specrot specrot mcp
"""
from __future__ import annotations

import functools
import re
import threading
from pathlib import Path

import relate
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import graph, scan

INSTRUCTIONS = """specrot holds every IETF RFC and how they relate (OBSOLETES, UPDATES, normative and
informative references, BCP/STD series, errata) in a Relate graph built from the RFC Editor index.
Before you cite, implement or quote an RFC, call check_rfcs: your training data may predate the
replacement (e.g. RFC 8446 for TLS 1.3 was obsoleted by RFC 9846 in 2026). Use scan_path on a
repository to find stale citations, reading_list for what an implementation must read, and
read_cypher for anything else (schema: get_schema)."""

server = MCPServer(name="specrot", instructions=INSTRUCTIONS)
_local = threading.local()


def explained(fn):
    """Turn bad input and Relate errors into a ToolError whose message tells the agent how to fix the call."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except graph.InputError as e:
            raise ToolError(str(e)) from e
        except relate.Error as e:
            write = re.search(r"(?i)read.?only|write|\b(create|merge|delete|set|remove)\b", str(e))
            raise ToolError(f"Relate rejected the query: {e}. ("
                            + ("The store is read-only. " if write else "")
                            + "get_schema lists labels, relationship types and properties.)") from e
    return wrapper


def _conn():
    # Relate connections are thread-affine: one read-only connection per worker thread.
    if getattr(_local, "conn", None) is None:
        _local.conn = graph.connect()
    return _local.conn


@server.tool()
def check_rfcs(rfcs: list[str]) -> list[dict]:
    """Status of RFCs ("2616", "RFC 7231", "BCP 14", or with a section: "RFC 7231 §6.5.1", "7231#6.5.1"; for an
    obsolete RFC section_now says where that section lives in the replacement). Level (obsolete, historic, old-version, amended, ok,
    unknown), replacement chains with their kind (edition, version, split, retired, redesign) and same_version (the newest edition on the old protocol version), live updates with
    deprecations flagged, verified technical errata, BCP/STD series. A bad id gives an error item, not a failure."""
    out = []
    for x in rfcs:
        try:
            out.append(graph.check(_conn(), x).to_dict())
        except graph.InputError as e:
            out.append({"input": x, "error": str(e)})
    return out


@server.tool()
@explained
def scan_path(path: str, include_ok: bool = False, include_tests_and_identifiers: bool = False) -> dict:
    """Find RFC citations in a file or directory (git-tracked files) and judge each cited RFC.
    By default skips citations in test files and identifiers such as time.RFC1123."""
    too_big: list[str] = []
    cites = [c for c in scan.find_citations(Path(path), skipped=too_big) if include_tests_and_identifiers or c.actionable]
    findings = scan.judge(_conn(), cites)
    keep = [f for f in findings if include_ok or f.verdict.level != "ok"]
    return {"citations": len(cites), "rfcs": len(findings), "skipped_large_files": too_big,
            "counts": {k: sum(1 for f in findings if f.verdict.level == k) for k in scan.LEVELS},
            "findings": [_brief(f) for f in keep]}


@server.tool()
@explained
def scan_text(text: str) -> list[dict]:
    """Judge the RFC citations in a snippet of code, a doc or a draft answer you are about to give."""
    return [_brief(f) for f in scan.judge(_conn(), scan.find_in_text(text))]


@server.tool()
@explained
def reading_list(rfc: str, depth: int = 1) -> list[dict]:
    """Normative references of an RFC up to `depth` hops (1-3); obsolete entries name their replacements."""
    return graph.reading(_conn(), rfc, depth)


@server.tool()
@explained
def dependents(rfc: str, depth: int = 1) -> list[dict]:
    """Documents still in force that normatively depend on an RFC, up to `depth` hops (1-3)."""
    return graph.impact(_conn(), rfc, depth)


@server.tool()
@explained
def search_rfcs(query: str, limit: int = 10) -> list[dict]:
    """Full-text search (BM25) over RFC titles and abstracts; obsolete hits are marked."""
    return graph.search(_conn(), query, limit)


@server.tool()
def get_schema() -> dict:
    """Labels, relationship types and properties of the graph, for writing read_cypher queries."""
    return {
        "nodes": {
            "RFC": "id 'RFC9110', number, title, date 'YYYY-MM', year, status, stream, area, wg, pages, abstract, "
                   "keywords, url, obsolete (bool), oldVersion (bool: obsolete only by newer protocol "
                   "versions), verifiedTechnicalErrata (int)",
            "Series": "id 'BCP14' | 'STD66', kind, number",
            "Erratum": "id, type (Technical/Editorial), status (Verified/Reported/...), section, date, url",
            "WorkingGroup": "acronym", "Area": "name",
            "Project": "name, repo, url, commit, scannedAt (open-source projects scanned by specrot)",
            "File": "path, project",
            "Section": "id 'RFC7231#6.5.1', rfc, number, title (only sections that carry over between editions)",
        },
        "relationships": [
            "(:RFC)-[:OBSOLETES {kind: edition|version|split|retired|redesign}]->(:RFC)", "(:RFC)-[:UPDATES]->(:RFC)",
            "(:RFC)-[:NORMATIVE_REF {via?}]->(:RFC|:Series)", "(:RFC)-[:INFORMATIVE_REF {via?}]->(:RFC|:Series)",
            "(:Series)-[:INCLUDES]->(:RFC)", "(:Erratum)-[:AMENDS]->(:RFC)",
            "(:RFC)-[:FROM_WG]->(:WorkingGroup)-[:IN_AREA]->(:Area)",
            "(:Project)-[:HAS_FILE]->(:File)-[:CITES {lines, readerLines, sections}]->(:RFC)",
            "(:RFC)-[:HAS_SECTION]->(:Section)-[:CONTINUES_AS {exact}]->(:Section)",
        ],
        "indexes": ["FULLTEXT rfc_text on RFC(title, abstract)"],
        "example": "MATCH (r:RFC {id:'RFC2616'})<-[:OBSOLETES]-+(n:RFC) WHERE NOT n.obsolete RETURN DISTINCT n.id",
    }


def _plain(v):
    """JSON-safe value: nodes and relationships become {labels or type, properties}."""
    if hasattr(v, "to_dict"):
        d = v.to_dict()
        return {k: d[k] for k in ("labels", "type", "properties") if k in d}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v if isinstance(v, (str, int, float, bool, dict, type(None))) else str(v)


@server.tool()
@explained
def read_cypher(statement: str, parameters: dict | None = None, limit: int = 200) -> dict:
    """Run a read-only Cypher 25 statement against the store (Relate dialect, no APOC). Returns {rows,
    truncated}: truncated is true when the query had more than `limit` rows (raise limit, or aggregate)."""
    if not 1 <= int(limit) <= 5000:
        raise graph.InputError(f"limit must be 1..5000, got {limit}")
    rows, truncated = [], False
    for i, r in enumerate(_conn().execute(statement, parameters or {})):
        if i >= limit:
            truncated = True
            break
        rows.append({k: _plain(v) for k, v in dict(r).items()})
    return {"rows": rows, "truncated": truncated}


def _brief(f: scan.Finding) -> dict:
    v = f.verdict
    return {"rfc": v.id, "title": v.title, "level": v.level, "replaced_by": v.current,
            "replacement_kinds": sorted({r["kind"] for r in v.replaced_by}),
            # newest edition on the old protocol version, when a later hop changes version (4492 -> 8422 -> TLS 1.3)
            "same_version_edition": sorted({r["same_version"] for r in v.replaced_by if r.get("same_version")}),
            "deprecated_by": [d["id"] for d in v.deprecations],
            "updated_by": [u["id"] for u in v.updated_by][:10], "verified_technical_errata": v.errata,
            "cited_at": [f"{c.path}:{c.line}" for c in f.citations][:20], "citations": len(f.citations),
            "sections_now": {c.section: [f"{h['rfc']} §{h['section']}" + ("" if h["exact"] else " (reworded)")
                                         for h in c.section_now] for c in f.citations if c.section and v.obsolete}}


def main():
    server.run("stdio")
