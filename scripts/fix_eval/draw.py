"""Sample `specrot fix` edits for a precision check: every edit fix proposes on the 26 showcase checkouts,
the first 100 by sha256("2026|project|file|line"), each with ±3 lines of context.

    uv run python -m scripts.fix_eval.draw        # writes scripts/fix_eval/sample.json (needs data/showcase/)
"""
import hashlib
import json
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
    key = lambda x: hashlib.sha256(f"2026|{x[0]}|{x[2].path}|{x[2].line}".encode()).hexdigest()
    out = []
    for i, (name, root, e) in enumerate(sorted(edits, key=key)[:100]):
        lines = (root / e.path).read_text(errors="replace").splitlines()
        out.append({"i": i, "project": name, "file": e.path, "line": e.line, "change": e.note,
                    "old": e.old.rstrip("\r\n"), "new": e.new.rstrip("\r\n"),
                    "context": "\n".join(lines[max(0, e.line - 4):e.line + 3])})
    (HERE / "sample.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"edits {len(edits)}, sample {len(out)}")


if __name__ == "__main__":
    main()
