"""Do coding agents name an obsolete RFC as "the current spec"? Model alone vs. model + specrot MCP.

    uv run python scripts/agent_eval/run.py --models haiku sonnet

Each question asks for the current RFC for a topic. The answer key is computed from the graph: the
documents still in force at the end of the OBSOLETES chain that starts at the topic's classic RFC.
An answer is correct when it names at least one of them and no obsolete RFC. Needs the `claude` CLI.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from specrot import graph

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PROMPT = ("Which RFC is the current IETF specification for {topic}? If several RFCs together form the current "
          "specification, list them. Reply with only the RFC number(s), for example 'RFC 1234' or 'RFC 1234, RFC 5678'.")


def answer_key(conn, seed: str) -> list[str]:
    v = graph.check(conn, seed)
    return v.current if v.obsolete else [v.id]


def ask(model: str, topic: str, with_tool: bool, mcp_config: Path, empty_config: Path, cwd: str) -> dict:
    cmd = ["claude", "-p", PROMPT.format(topic=topic), "--model", model, "--output-format", "json",
           "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
    if with_tool:
        cmd += ["--mcp-config", str(mcp_config), "--allowedTools", "mcp__specrot__check_rfcs",
                "mcp__specrot__search_rfcs", "mcp__specrot__read_cypher", "mcp__specrot__get_schema"]
    else:
        cmd += ["--mcp-config", str(empty_config)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=cwd)
    try:
        out = json.loads(p.stdout)
        text, turns, model_id = out.get("result", ""), out.get("num_turns"), sorted(out.get("modelUsage", {}))
    except json.JSONDecodeError:
        text, turns, model_id = (p.stdout + p.stderr)[-500:], None, []
    return {"text": text, "turns": turns, "model_id": model_id}


def score(conn, text: str, key: list[str]) -> dict:
    """Only the answer line counts; a later explanatory note may mention the RFC it replaced."""
    answer = next((ln for ln in (text or "").splitlines() if ln.strip()), "")
    named = sorted({f"RFC{int(n)}" for n in re.findall(r"(?i)rfc\s*-?\s*(\d{1,5})", answer)})
    obsolete = [x for x in named if graph.check(conn, x).obsolete]
    return {"named": named, "obsolete_named": obsolete,
            "correct": bool(set(named) & set(key)) and not obsolete}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["haiku", "sonnet"])
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    conn = graph.connect()
    qs = json.loads((HERE / "questions.json").read_text())
    for q in qs:
        q["key"] = answer_key(conn, q["seed"])
    tmp = Path(tempfile.mkdtemp())
    mcp = tmp / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"specrot": {
        "command": "uv", "args": ["run", "--directory", str(ROOT), "specrot", "mcp"]}}}))
    empty = tmp / "empty.json"
    empty.write_text(json.dumps({"mcpServers": {}}))
    jobs = [(m, q, t) for m in a.models for t in (False, True) for q in qs]
    with ThreadPoolExecutor(a.workers) as ex:
        answers = list(ex.map(lambda j: ask(j[0], j[1]["topic"], j[2], mcp, empty, str(tmp)), jobs))
    rows = []
    for (m, q, t), ans in zip(jobs, answers):
        rows.append({"model": m, "with_specrot": t, "topic": q["topic"], "seed": q["seed"], "key": q["key"],
                     **ans, **score(conn, ans["text"], q["key"])})
    summary = {}
    for m in a.models:
        for t in (False, True):
            rs = [r for r in rows if r["model"] == m and r["with_specrot"] == t]
            changed = [r for r in rs if r["seed"] not in r["key"]]
            summary[f"{m}{' + specrot' if t else ''}"] = {
                "correct": sum(r["correct"] for r in rs), "of": len(rs),
                "named_an_obsolete_rfc": sum(bool(r["obsolete_named"]) for r in rs),
                "correct_where_spec_was_replaced": f"{sum(r['correct'] for r in changed)}/{len(changed)}"}
    out = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "prompt": PROMPT,
           "summary": summary, "rows": rows}
    (HERE / "results.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
