"""Check the agent-eval answer key against the RFC Editor's own per-RFC metadata, not specrot's graph.

    uv run python scripts/agent_eval/check_key.py      # writes key_check.json

For each question: every RFC in the key must have an empty `obsoleted_by` at rfc-editor.org/rfc/rfcN.json,
and when the seed RFC differs from the key, the seed must list an `obsoleted_by`.
"""
import json
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def meta(rid: str) -> dict:
    with urllib.request.urlopen(f"https://www.rfc-editor.org/rfc/{rid.lower()}.json", timeout=60) as r:
        return json.load(r)


def main():
    rows = json.loads((HERE / "results.json").read_text())["rows"]
    keys = {r["seed"]: r["key"] for r in rows}
    cache, out = {}, []
    for seed, key in sorted(keys.items()):
        for rid in {seed, *key}:
            if rid not in cache:
                cache[rid] = meta(rid)
                time.sleep(0.5)
        key_current = all(not cache[k].get("obsoleted_by") for k in key)
        seed_ok = seed in key or bool(cache[seed].get("obsoleted_by"))
        out.append({"seed": seed, "key": key, "key_not_obsoleted": key_current, "seed_obsoleted": seed not in key,
                    "agrees": key_current and seed_ok, "seed_obsoleted_by": cache[seed].get("obsoleted_by", [])})
    summary = {"questions": len(out), "agree": sum(r["agrees"] for r in out),
               "source": "https://www.rfc-editor.org/rfc/rfcN.json (obsoleted_by)"}
    (HERE / "key_check.json").write_text(json.dumps({"summary": summary, "rows": out}, indent=1) + "\n")
    print(summary)


if __name__ == "__main__":
    main()
