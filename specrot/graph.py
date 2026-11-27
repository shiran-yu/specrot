"""Read-side queries over the Relate store. Each function is a few Cypher statements."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import relate

DEFAULT_STORE = Path(os.environ.get("SPECROT_STORE", Path(__file__).resolve().parent.parent / "store" / "rfc.rl"))
# An update whose title says this is a deprecation, not a mere extension.
DEPRECATING = re.compile(r"deprecat|prohibit|obsolet|historic|retir|removing|sunset", re.I)
MAX_DEPTH = 3  # traversal depth cap for read/impact: depth 3 already reaches thousands of documents
LEVELS = ["obsolete", "historic", "old-version", "amended", "ok", "unknown"]


class InputError(ValueError):
    """A bad argument from a user or an agent; the message says how to fix it."""


def connect(store: Path | str = DEFAULT_STORE, read_only: bool = True):
    store = Path(store)
    if not store.exists():
        raise SystemExit(f"store not found: {store} (run `specrot build` or set SPECROT_STORE)")
    return relate.connect(str(store), read_only=read_only)


def rfc_id(x: str | int) -> str:
    """'2616', 'RFC 2616', 'rfc-2616', 'bcp14', 'STD 66' -> canonical id."""
    m = re.fullmatch(r"(?i)\s*(rfc|bcp|std|fyi)?[\s_-]*0*(\d{1,5})\s*", str(x))
    if not m or str(x).strip().startswith("-"):
        raise InputError(f"not an RFC id: {x!r} (use a number such as 2616, or RFC 2616, BCP 14, STD 66)")
    return f"{(m.group(1) or 'RFC').upper()}{int(m.group(2))}"


REF = re.compile(r"(?i)^(.*?\d)\s*(?:#\s*(?:section-|appendix-)?|§\s*|,?\s+sec(?:tion)?\.?\s*)"
                 r"((?-i:[A-Z])(?:\.\d+)*|\d+(?:\.\d+)*)\.?\s*$")


def split_ref(x: str | int) -> tuple[str | int, str | None]:
    """'7231#6.5.1', 'RFC 7231 §6.5.1', 'RFC 7231 section 6.5.1' -> ('7231...', '6.5.1'); else (x, None)."""
    m = REF.match(str(x))
    return (m.group(1), m.group(2)) if m else (x, None)


def clamp_depth(depth: int) -> int:
    if int(depth) < 1:
        raise InputError(f"depth must be 1..{MAX_DEPTH}, got {depth}")
    return min(int(depth), MAX_DEPTH)


# Current replacements: follow OBSOLETES backwards to documents nobody obsoletes. Each edge carries the
# kind of replacement computed at build time (build.py: edition, version, split, retired).
REPLACEMENTS = """
MATCH (r:RFC {id: $id})
MATCH p = (r)<-[:OBSOLETES]-+(n:RFC) WHERE NOT n.obsolete
RETURN [x IN nodes(p) | x.id] AS chain, [e IN relationships(p) | e.kind] AS kinds,
       n.id AS current, n.title AS title, n.date AS date
ORDER BY current
"""

# Live amendments: updates from documents that are themselves still in force.
UPDATES = """
MATCH (r:RFC {id: $id})<-[:UPDATES]-(u:RFC) WHERE NOT u.obsolete
RETURN u.id AS id, u.title AS title, u.date AS date, u.status AS status
ORDER BY u.date DESC
"""

SERIES = "MATCH (s:Series)-[:INCLUDES]->(r:RFC {id: $id}) RETURN s.id AS id ORDER BY id"
MEMBERS = "MATCH (s:Series {id: $id})-[:INCLUDES]->(r:RFC) RETURN r.id AS id ORDER BY r.number"

INFO = """
MATCH (r:RFC {id: $id})
RETURN r.id AS id, r.title AS title, r.date AS date, r.status AS status, r.obsolete AS obsolete,
       r.verifiedTechnicalErrata AS errata, r.wg AS wg, r.url AS url, r.abstract AS abstract
"""

# Where a section of an obsolete RFC lives now: CONTINUES_AS hops (matched headings, build.py) to a
# section of a document still in force. exact is false when any hop matched a reworded heading.
SECTION_NOW = """
MATCH (s:Section {id: $id})
MATCH p = (s)-[:CONTINUES_AS]->+(t:Section)
MATCH (r:RFC {id: t.rfc}) WHERE NOT r.obsolete
RETURN r.id AS rfc, t.number AS section, t.title AS title, s.title AS was,
       all(e IN relationships(p) WHERE e.exact) AS exact, size(relationships(p)) AS hops
ORDER BY hops
"""

KIND_TEXT = {
    "edition": "new edition of the same specification",
    "version": "newer protocol version: the old RFC still defines the old version",
    "split": "content split across several documents",
    "retired": "retired without a replacement",
    "redesign": "replaced by a different design: check before switching the citation",
    "partial": "only one part of it moved here: check the updates for the rest",
}


def path_kind(kinds: list[str]) -> str:
    """Summarise a chain by its first hop: TLS 1.2 -> 1.3 -> 1.3bis is a version change, but RFC 4492 -> 8422
    (new edition) -> 9846 (TLS 1.3) is a replaced edition. A retiring last hop wins."""
    if kinds and kinds[-1] == "retired":
        return "retired"
    if kinds and kinds[0] == "version":
        return "version"
    if "redesign" in kinds:
        return "redesign"
    if "partial" in kinds:
        return "partial"
    if "split" in kinds:
        return "split"
    return "edition"


def same_version(r: dict) -> str | None:
    """The newest edition before a later version hop (4492 -> 8422 -> 9846 gives 8422), for code that stays on the old version."""
    j = next((i for i, k in enumerate(r["kinds"]) if k == "version"), None)
    return r["chain"][j] if j else None


@dataclass
class Verdict:
    id: str
    title: str | None = None
    date: str | None = None
    status: str | None = None
    url: str | None = None
    known: bool = True
    obsolete: bool = False
    replaced_by: list[dict] = field(default_factory=list)   # [{chain, kinds, kind, current, title, date}]
    updated_by: list[dict] = field(default_factory=list)    # live updates, newest first
    deprecations: list[dict] = field(default_factory=list)  # subset of updated_by
    errata: int = 0
    series: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)        # for a BCP/STD/FYI id
    section: str | None = None                               # the section asked about, if any
    section_now: list[dict] = field(default_factory=list)   # [{rfc, section, title, was, exact}]

    @property
    def level(self) -> str:
        """obsolete > historic > old-version > amended > ok (> unknown). Deprecations count as amendments.
        A retired protocol version (TLS 1.0, status HISTORIC) is historic, not old-version."""
        if not self.known:
            return "unknown"
        if self.obsolete and not self.version_only:
            return "obsolete"
        if self.status == "HISTORIC":
            return "historic"
        if self.obsolete:
            return "old-version"
        if self.updated_by or self.errata:
            return "amended"
        return "ok"

    @property
    def version_only(self) -> bool:
        """Obsolete only because newer protocol versions exist (stored as RFC.oldVersion)."""
        return bool(self.replaced_by) and all(r["kind"] == "version" for r in self.replaced_by)

    @property
    def current(self) -> list[str]:
        """Documents to read instead (retiring documents are not replacements)."""
        return sorted({r["current"] for r in self.replaced_by if r["kind"] != "retired"})

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["level"], d["current"] = self.level, self.current
        return d


def section_now(conn, rid: str, section: str) -> list[dict]:
    """Current homes of a section of an obsolete RFC, one per current document, fewest hops first."""
    out: dict[tuple, dict] = {}
    for r in conn.execute(SECTION_NOW, {"id": f"{rid}#{section}"}):
        out.setdefault((r["rfc"], r["section"]), {k: r[k] for k in ("rfc", "section", "title", "was", "exact")})
    return list(out.values())


def check(conn, x: str | int, section: str | None = None) -> Verdict:
    x, sec = split_ref(x)
    section = section or sec
    v = _check(conn, x)
    if section and v.known:
        v.section = section
        if v.obsolete:
            v.section_now = section_now(conn, v.id, section)
    return v


def _check(conn, x: str | int) -> Verdict:
    rid = rfc_id(x)
    if not rid.startswith("RFC"):
        members = [r["id"] for r in conn.execute(MEMBERS, {"id": rid})]
        if not members:
            return Verdict(id=rid, known=False)
        return Verdict(id=rid, title=f"{rid[:3]} {rid[3:]}: a series of {len(members)} RFC(s)", status="SERIES",
                       members=members)
    info = list(conn.execute(INFO, {"id": rid}))
    if not info:
        return Verdict(id=rid, known=False)
    i = info[0]
    v = Verdict(id=rid, title=i["title"], date=i["date"], status=i["status"], url=i["url"],
                obsolete=bool(i["obsolete"]), errata=int(i["errata"] or 0))
    if v.obsolete:
        shortest: dict[str, dict] = {}  # one shortest chain per current replacement
        for r in conn.execute(REPLACEMENTS, {"id": rid}):
            if r["current"] not in shortest or len(r["chain"]) < len(shortest[r["current"]]["chain"]):
                shortest[r["current"]] = {**dict(r), "kind": path_kind(r["kinds"]), "same_version": same_version(r)}
        v.replaced_by = list(shortest.values())
    v.updated_by = [dict(r) for r in conn.execute(UPDATES, {"id": rid})]
    v.deprecations = [u for u in v.updated_by if DEPRECATING.search(u["title"] or "")]
    v.series = [r["id"] for r in conn.execute(SERIES, {"id": rid})]
    return v


# Traversals go hop by hop over sets of ids (a breadth-first search in Cypher), which keeps
# depth 3 fast where one variable-length pattern would enumerate every path.
HOP_OUT = """UNWIND $ids AS id MATCH (:RFC {id: id})-[:NORMATIVE_REF]->(d:RFC) RETURN DISTINCT d.id AS id"""
HOP_IN = """UNWIND $ids AS id MATCH (:RFC {id: id})<-[:NORMATIVE_REF]-(d:RFC) RETURN DISTINCT d.id AS id"""
DESCRIBE = """
UNWIND $ids AS id MATCH (d:RFC {id: id})
OPTIONAL MATCH (d)<-[:OBSOLETES]-+(n:RFC) WHERE NOT n.obsolete
RETURN d.id AS id, d.title AS title, d.date AS date, d.status AS status, d.obsolete AS obsolete,
       collect(DISTINCT n.id) AS current
"""


def _bfs(conn, root: str, hop: str, depth: int) -> dict[str, int]:
    seen, frontier = {root: 0}, [root]
    for d in range(1, clamp_depth(depth) + 1):
        nxt = [r["id"] for r in conn.execute(hop, {"ids": frontier}) if r["id"] not in seen]
        for i in nxt:
            seen[i] = d
        frontier = nxt
        if not frontier:
            break
    seen.pop(root)
    return seen


def _describe(conn, depths: dict[str, int]) -> list[dict]:
    rows = [dict(r) | {"depth": depths[r["id"]]} for r in conn.execute(DESCRIBE, {"ids": list(depths)})]
    return rows


def reading(conn, x: str | int, depth: int = 1) -> list[dict]:
    """Normative references up to `depth` hops; obsolete entries name their current replacements."""
    rows = _describe(conn, _bfs(conn, rfc_id(x), HOP_OUT, depth))
    return sorted(rows, key=lambda r: (r["depth"], int(r["id"][3:])))


def impact(conn, x: str | int, depth: int = 1) -> list[dict]:
    """Documents still in force that normatively depend on an RFC, directly or through `depth` hops."""
    rows = [r for r in _describe(conn, _bfs(conn, rfc_id(x), HOP_IN, depth)) if not r["obsolete"]]
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return sorted(rows, key=lambda r: r["depth"])  # stable: newest first within each hop


SEARCH = """
MATCH (r:RFC)
SEARCH r IN (FULLTEXT INDEX rfc_text FOR $q LIMIT $k) SCORE AS score
RETURN r.id AS id, r.title AS title, r.date AS date, r.status AS status, r.obsolete AS obsolete, score
ORDER BY score DESC
"""


def search(conn, q: str, k: int = 10) -> list[dict]:
    """Full-text search; query words are reduced to letters and digits so any input is safe."""
    words = [w.lower() for w in re.findall(r"[\w.]+", q or "")]  # lower case: AND/OR/NOT are query operators
    if not words:
        raise InputError("search needs at least one word, e.g. specrot search \"http caching\"")
    if not 1 <= int(k) <= 200:
        raise InputError(f"limit must be 1..200, got {k}")
    return [dict(r) for r in conn.execute(SEARCH, {"q": " ".join(words), "k": int(k)})]
