"""Summarise the audit: label counts per labeler, agreement and Cohen's kappa, and the share labelled
`update` by each labeler and by both.

    uv run python scripts/audit/score.py
"""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = ["update", "legacy", "identifier", "test", "not-a-citation"]


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in LABELS) / n ** 2
    return (po - pe) / (1 - pe)


def main():
    files = sorted(HERE.glob("labels-*.json"))
    labs = {f.stem.removeprefix("labels-"): {x["i"]: x["label"] for x in json.loads(f.read_text())} for f in files}
    ids = sorted(set.intersection(*(set(v) for v in labs.values())))
    out = {"n": len(ids), "labelers": {}}
    for k, v in labs.items():
        c = Counter(v[i] for i in ids)
        out["labelers"][k] = {lab: c[lab] for lab in LABELS}
    if len(labs) == 2:
        (ka, a), (kb, b) = labs.items()
        la, lb = [a[i] for i in ids], [b[i] for i in ids]
        out["agreement"] = round(sum(x == y for x, y in zip(la, lb)) / len(ids), 3)
        out["cohen_kappa"] = round(kappa(la, lb), 3)
        out["update_by_both"] = sum(x == y == "update" for x, y in zip(la, lb))
        out["update_by_either"] = sum("update" in (x, y) for x, y in zip(la, lb))
    (HERE / "summary.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
