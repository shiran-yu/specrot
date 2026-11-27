"""Export the store to docs/data/graph.json for the in-browser explorer (Relate WASM cannot open a .rl
file, so the page rebuilds the same graph in memory from this file with Cypher UNWIND batches)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from specrot import graph

OUT = Path(__file__).resolve().parent.parent / "docs" / "data" / "graph.json"


def main():
    c = graph.connect()
    q = lambda s: [dict(r) for r in c.execute(s)]
    rfcs = [[r["n"], r["t"], r["d"], r["s"], int(bool(r["o"])), r["e"] or 0, r["w"]] for r in q(
        "MATCH (r:RFC) RETURN r.number AS n, r.title AS t, r.date AS d, r.status AS s, r.obsolete AS o, "
        "r.verifiedTechnicalErrata AS e, r.wg AS w ORDER BY n")]
    edges = {}
    for t in ("OBSOLETES", "UPDATES", "NORMATIVE_REF"):
        edges[t] = [[r["a"], r["b"]] for r in q(
            f"MATCH (a:RFC)-[:{t}]->(b:RFC) RETURN a.number AS a, b.number AS b ORDER BY a, b")]
    series = [[r["s"], r["m"]] for r in q(
        "MATCH (s:Series)-[:INCLUDES]->(r:RFC) RETURN s.id AS s, collect(r.number) AS m ORDER BY s")]
    projects = []
    for p in q("MATCH (p:Project) RETURN p.name AS name, p.repo AS repo, p.commit AS commit, p.url AS url ORDER BY name"):
        files = q(f"""MATCH (:Project {{name: '{p['name']}'}})-[:HAS_FILE]->(f:File)-[c:CITES]->(r:RFC)
                     WHERE c.actionable > 0 AND NOT f.inTests
                     RETURN f.path AS path, collect([r.number, c.lines]) AS cites ORDER BY path""")
        p["files"] = [[f["path"], f["cites"]] for f in files]
        projects.append(p)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {"built": date.today().isoformat(), "rfcs": rfcs, "edges": edges, "series": series, "projects": projects}
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(OUT, f"{OUT.stat().st_size / 1e6:.1f} MB", {k: len(v) for k, v in edges.items()}, len(projects))


if __name__ == "__main__":
    main()
