"""Read-side queries over the Relate store. Every function is one or two Cypher statements."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import relate

DEFAULT_STORE = Path(os.environ.get("SPECROT_STORE", Path(__file__).resolve().parent.parent / "store" / "rfc.rl"))
# An update whose title says this is a deprecation, not a mere extension.
DEPRECATING = re.compile(r"deprecat|prohibit|obsolet|historic|retir|removing|sunset", re.I)


def connect(store: Path | str = DEFAULT_STORE, read_only: bool = True):
    store = Path(store)
    if not store.exists():
        raise SystemExit(f"store not found: {store} (run `specrot build` or set SPECROT_STORE)")
    return relate.connect(str(store), read_only=read_only)


def rfc_id(x: str | int) -> str:
    m = re.fullmatch(r"(?i)\s*(rfc|bcp|std|fyi)?[\s_-]*0*(\d+)\s*", str(x))
    if not m:
        raise ValueError(f"not an RFC id: {x!r}")
    return f"{(m.group(1) or 'RFC').upper()}{int(m.group(2))}"


# Current replacements: follow OBSOLETES backwards to documents nobody obsoletes.
REPLACEMENTS = """
MATCH (r:RFC {id: $id})
MATCH p = (r)<-[:OBSOLETES]-+(n:RFC) WHERE NOT n.obsolete
RETURN [x IN nodes(p) | x.id] AS chain, n.id AS current, n.title AS title, n.date AS date
ORDER BY current
"""

# Live amendments: updates from documents that are themselves still in force.
UPDATES = """
MATCH (r:RFC {id: $id})<-[:UPDATES]-(u:RFC) WHERE NOT u.obsolete
RETURN u.id AS id, u.title AS title, u.date AS date, u.status AS status
ORDER BY u.date DESC
"""

SERIES = "MATCH (s:Series)-[:INCLUDES]->(r:RFC {id: $id}) RETURN s.id AS id ORDER BY id"

INFO = """
MATCH (r:RFC {id: $id})
RETURN r.id AS id, r.title AS title, r.date AS date, r.status AS status, r.obsolete AS obsolete,
       r.verifiedTechnicalErrata AS errata, r.wg AS wg, r.url AS url, r.abstract AS abstract
"""


@dataclass
class Verdict:
    id: str
    title: str | None = None
    date: str | None = None
    status: str | None = None
    url: str | None = None
    known: bool = True
    obsolete: bool = False
    replaced_by: list[dict] = field(default_factory=list)   # [{chain, current, title, date}]
    updated_by: list[dict] = field(default_factory=list)    # live updates, newest first
    deprecations: list[dict] = field(default_factory=list)  # subset of updated_by
    errata: int = 0
    series: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        """obsolete > historic > amended > ok (> unknown). Deprecations count as amendments."""
        if not self.known:
            return "unknown"
        if self.obsolete:
            return "obsolete"
        if self.status == "HISTORIC":
            return "historic"
        if self.updated_by or self.errata:
            return "amended"
        return "ok"

    @property
    def current(self) -> list[str]:
        return sorted({r["current"] for r in self.replaced_by})

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["level"], d["current"] = self.level, self.current
        return d


def check(conn, x: str | int) -> Verdict:
    rid = rfc_id(x)
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
                shortest[r["current"]] = dict(r)
        v.replaced_by = list(shortest.values())
    v.updated_by = [dict(r) for r in conn.execute(UPDATES, {"id": rid})]
    v.deprecations = [u for u in v.updated_by if DEPRECATING.search(u["title"] or "")]
    v.series = [r["id"] for r in conn.execute(SERIES, {"id": rid})]
    return v


# Everything you must read to implement an RFC: normative closure, with obsolete targets
# swapped for their current replacements, then their normative references in turn.
READING = """
MATCH (root:RFC {id: $id})
MATCH p = (root)-[:NORMATIVE_REF]->{1,%d}(d:RFC)
WITH d, min(length(p)) AS depth
OPTIONAL MATCH (d)<-[:OBSOLETES]-+(n:RFC) WHERE NOT n.obsolete
RETURN d.id AS id, d.title AS title, depth, d.obsolete AS obsolete, collect(DISTINCT n.id) AS current
ORDER BY depth, id
"""


def reading(conn, x: str | int, depth: int = 2) -> list[dict]:
    return [dict(r) for r in conn.execute(READING % int(depth), {"id": rfc_id(x)})]


# Who normatively depends on this RFC (directly or through n hops), still-current documents only.
IMPACT = """
MATCH (root:RFC {id: $id})
MATCH p = (root)<-[:NORMATIVE_REF]-{1,%d}(d:RFC) WHERE NOT d.obsolete
WITH d, min(length(p)) AS depth
RETURN d.id AS id, d.title AS title, d.date AS date, d.status AS status, depth
ORDER BY depth, date DESC
"""


def impact(conn, x: str | int, depth: int = 1) -> list[dict]:
    return [dict(r) for r in conn.execute(IMPACT % int(depth), {"id": rfc_id(x)})]


SEARCH = """
MATCH (r:RFC)
SEARCH r IN (FULLTEXT INDEX rfc_text FOR $q LIMIT $k) SCORE AS score
RETURN r.id AS id, r.title AS title, r.date AS date, r.status AS status, r.obsolete AS obsolete, score
ORDER BY score DESC
"""


def search(conn, q: str, k: int = 10) -> list[dict]:
    return [dict(r) for r in conn.execute(SEARCH, {"q": q, "k": int(k)})]
