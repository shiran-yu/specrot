"""Export the store to docs/data/graph.json for the in-browser explorer (Relate WASM cannot open a .rl
file, so the page rebuilds the same graph in memory from this file with Cypher UNWIND batches)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from specrot import graph

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "graph.json"


def main():
    c = graph.connect()
    q = lambda s: [dict(r) for r in c.execute(s)]
    rfcs = [[r["n"], r["t"], r["d"], r["s"], int(bool(r["o"])), r["e"] or 0, r["w"], int(bool(r["v"]))] for r in q(
        "MATCH (r:RFC) RETURN r.number AS n, r.title AS t, r.date AS d, r.status AS s, r.obsolete AS o, "
        "r.verifiedTechnicalErrata AS e, r.wg AS w, r.oldVersion AS v ORDER BY n")]
    edges = {}
    for t in ("OBSOLETES", "UPDATES", "NORMATIVE_REF"):
        edges[t] = [[r["a"], r["b"]] + ([r["k"]] if t == "OBSOLETES" else []) for r in q(
            f"MATCH (a:RFC)-[e:{t}]->(b:RFC) RETURN a.number AS a, b.number AS b, e.kind AS k ORDER BY a, b")]
    series = [[r["s"], r["m"]] for r in q(
        "MATCH (s:Series)-[:INCLUDES]->(r:RFC) RETURN s.id AS s, collect(r.number) AS m ORDER BY s")]
    projects = []
    for p in q("MATCH (p:Project) RETURN p.name AS name, p.repo AS repo, p.commit AS commit, p.url AS url ORDER BY name"):
        files = q(f"""MATCH (:Project {{name: '{p['name']}'}})-[:HAS_FILE]->(f:File)-[c:CITES]->(r:RFC)
                     WHERE size(c.readerLines) > 0
                     RETURN f.path AS path, collect([r.number, c.readerLines]) AS cites ORDER BY path""")
        p["files"] = [[f["path"], f["cites"]] for f in files]
        projects.append(p)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fetched = date.fromtimestamp((ROOT / "data" / "raw" / "rfc-index.xml").stat().st_mtime).isoformat() \
        if (ROOT / "data" / "raw" / "rfc-index.xml").exists() else date.today().isoformat()
    data = {"built": fetched, "rfcs": rfcs, "edges": edges, "series": series, "projects": projects}
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(OUT, f"{OUT.stat().st_size / 1e6:.1f} MB", {k: len(v) for k, v in edges.items()}, len(projects))
    # sections load on demand (first section lookup): [rfc number, section, title] and edges by index
    secs = q("MATCH (s:Section) RETURN s.id AS id, s.rfc AS r, s.number AS n, s.title AS t ORDER BY id")
    at = {s["id"]: i for i, s in enumerate(secs)}
    cont = [[at[r["a"]], at[r["b"]], int(bool(r["x"]))] for r in q(
        "MATCH (a:Section)-[e:CONTINUES_AS]->(b:Section) RETURN a.id AS a, b.id AS b, e.exact AS x")]
    sec_out = OUT.with_name("sections.json")
    sec_out.write_text(json.dumps({"s": [[int(s["r"][3:]), s["n"], s["t"]] for s in secs], "e": cont},
                                  separators=(",", ":")))
    print(sec_out, f"{sec_out.stat().st_size / 1e6:.1f} MB", len(secs), len(cont))


if __name__ == "__main__":
    main()
