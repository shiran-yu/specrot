"""Compute every headline number from the store into facts.json; tests/test_facts.py checks the README against it."""
from __future__ import annotations

import json
from pathlib import Path

from specrot import graph

OUT = Path(__file__).resolve().parent.parent / "facts.json"


def main():
    c = graph.connect()
    one = lambda q: dict(next(iter(c.execute(q))))
    labels = {r["l"]: r["c"] for r in c.execute("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c")}
    rels = {r["t"]: r["c"] for r in c.execute("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")}
    show = one("""MATCH (p:Project)-[:HAS_FILE]->(:File)-[c:CITES]->(r:RFC)
                  WITH p, sum(size(c.readerLines)) AS cites,
                       sum(CASE WHEN r.obsolete AND NOT r.oldVersion THEN size(c.readerLines) ELSE 0 END) AS stale,
                       sum(CASE WHEN r.oldVersion THEN size(c.readerLines) ELSE 0 END) AS older
                  RETURN sum(cites) AS citations, sum(stale) AS obsolete, sum(older) AS old_version, count(p) AS projects,
                         sum(CASE WHEN stale > 0 THEN 1 ELSE 0 END) AS affected""")
    show["obsolete_pct"] = round(100 * show["obsolete"] / show["citations"])
    top = [dict(r) for r in c.execute("""
        MATCH (p:Project)-[:HAS_FILE]->(:File)-[c:CITES]->(r:RFC) WHERE r.obsolete AND NOT r.oldVersion AND size(c.readerLines) > 0
        RETURN r.id AS rfc, count(DISTINCT p) AS projects ORDER BY projects DESC, rfc LIMIT 4""")]
    tls = one("""MATCH (p:Project)-[:HAS_FILE]->(:File)-[c:CITES]->(:RFC {id: 'RFC8446'}) WHERE size(c.readerLines) > 0
                 RETURN count(DISTINCT p) AS projects, sum(size(c.readerLines)) AS citations""")
    cited = [dict(r) for r in c.execute("""MATCH (:File)-[c:CITES]->(r:RFC) WHERE r.obsolete AND NOT r.oldVersion
        AND size(c.readerLines) > 0 UNWIND c.sections AS s RETURN DISTINCT r.id AS rfc, s""")]
    homes = [graph.section_now(c, x["rfc"], x["s"]) for x in cited]
    sections = {"cited": len(cited), "mapped": sum(bool(h) for h in homes),
                "exact": sum(any(y["exact"] for y in h) for h in homes)}
    # blast radius of a new RFC: everything it replaces, any number of hops back, still cited in the projects.
    # WITH DISTINCT old: an RFC reached by several OBSOLETES paths must count its citations once.
    blast = {rid: one(f"""MATCH (:RFC {{id: '{rid}'}})-[:OBSOLETES]->+(old:RFC) WITH DISTINCT old
                           MATCH (old)<-[c:CITES]-(:File)<-[:HAS_FILE]-(p:Project) WHERE size(c.readerLines) > 0
                           RETURN count(DISTINCT old) AS replaced, count(DISTINCT p) AS projects,
                                  sum(size(c.readerLines)) AS citations""") for rid in ("RFC9110", "RFC9846")}
    facts = {"blast_radius": blast, "sections": sections, "nodes": labels, "relationships": rels, "showcase": show, "top_obsolete": top, "rfc8446_cited": tls,
             "store_bytes": graph.DEFAULT_STORE.stat().st_size}
    OUT.write_text(json.dumps(facts, indent=2) + "\n")
    print(json.dumps(facts, indent=2))


if __name__ == "__main__":
    main()
