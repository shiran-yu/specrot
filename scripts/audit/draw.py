"""Draw the audit sample: 100 citations, seed 2026, from the population the headline counts
(reader-facing citations of RFCs a newer edition has replaced, in the 26 showcase projects).

    uv run python scripts/audit/draw.py      # writes scripts/audit/sample.json (needs data/showcase/)
"""
import json
import random
from pathlib import Path

from specrot import graph, scan
from scripts.showcase import PROJECTS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main():
    conn = graph.connect()
    population = []
    for name, repo, sub in PROJECTS:
        root = ROOT / "data" / "showcase" / repo.replace("/", "__") / sub
        cites = [c for c in scan.find_citations(root) if c.actionable]
        for f in scan.judge(conn, cites):
            if f.verdict.level == "obsolete":
                population += [(name, root, c, f.verdict) for c in f.citations]
    random.seed(2026)
    sample = random.sample(population, 100)
    out = []
    for i, (name, root, c, v) in enumerate(sample):
        lines = (root / c.path).read_text(errors="replace").splitlines()
        out.append({"i": i, "project": name, "file": c.path, "line": c.line, "rfc": c.rfc, "rfc_title": v.title,
                    "replaced_by": v.current, "replacement_kinds": sorted({r["kind"] for r in v.replaced_by}),
                    "context": "\n".join(lines[max(0, c.line - 4):c.line + 3])})
    (HERE / "sample.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"population {len(population)}, sample {len(out)}")


if __name__ == "__main__":
    main()
