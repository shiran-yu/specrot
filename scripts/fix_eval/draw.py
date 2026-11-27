"""Sample `specrot fix` edits for a precision check: every edit fix proposes on the 26 showcase checkouts,
the first 100 by sha256("2026|project|file|line"), each with ±3 lines of context.

    uv run python -m scripts.fix_eval.draw        # writes scripts/fix_eval/sample.json (needs data/showcase/)
    uv run python -m scripts.fix_eval.draw --holdout   # new salt, no edit seen in earlier rounds -> holdout/
"""
import hashlib
import json
import sys
from pathlib import Path

from specrot import fix, graph
from scripts.showcase import PROJECTS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main():
    conn = graph.connect()
    edits = []
    for name, repo, sub in PROJECTS:
        root = ROOT / "data" / "showcase" / repo.replace("/", "__") / sub
        es, _ = fix.plan(conn, root)
        edits += [(name, root, e) for e in es]
    salt, out_dir = ("holdout", HERE / "holdout") if "--holdout" in sys.argv else ("2026", HERE)
    if salt == "holdout":  # drop every line labelled in rounds 1 and 2
        seen = {(r["project"], r["file"], r["line"]) for f in ("sample.json", "round1/sample.json")
                for r in json.loads((HERE / f).read_text())}
        edits = [x for x in edits if (x[0], x[2].path, x[2].line) not in seen]
    key = lambda x: hashlib.sha256(f"{salt}|{x[0]}|{x[2].path}|{x[2].line}".encode()).hexdigest()
    out = []
    for i, (name, root, e) in enumerate(sorted(edits, key=key)[:100]):
        lines = (root / e.path).read_text(errors="replace").splitlines()
        out.append({"i": i, "project": name, "file": e.path, "line": e.line, "change": e.note,
                    "old": e.old.rstrip("\r\n"), "new": e.new.rstrip("\r\n"),
                    "context": "\n".join(lines[max(0, e.line - 4):e.line + 3])})
    out_dir.mkdir(exist_ok=True)
    (out_dir / "sample.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"edits {len(edits)}, sample {len(out)}")


if __name__ == "__main__":
    main()
