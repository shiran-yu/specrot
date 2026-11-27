"""Label the audit sample with one model, from LABELING.md and sample.json only (no tools, no files).

    uv run python scripts/audit/label.py claude      # `claude -p`, model sonnet -> labels-claude.json
    uv run python scripts/audit/label.py gpt         # GitHub Copilot CLI, model auto (recorded) -> labels-gpt.json
    uv run python scripts/audit/label.py claude --dir scripts/fix_eval --save   # same, for the fix precision sample

The full prompt and the raw reply are kept in raw/<labeler>.json; score.py compares the two label files.
A rerun writes labels-<labeler>-<time>.json and raw/<labeler>-<time>.json beside the published ones
(compare with `score.py labels-claude.json labels-claude-<time>.json`); --save replaces the published files. The models behind the
aliases are recorded in raw/; `sonnet` and Copilot's `auto` may resolve to newer models later.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMANDS = {
    "claude": lambda p: ["claude", "-p", p, "--model", "sonnet", "--output-format", "json", "--tools", "",
                         "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"],
    # Copilot accepts only "auto" here; the model it picked is read back from its session log
    "gpt": lambda p: ["copilot", "-p", p, "--model", "auto", "--no-color", "--deny-tool", "shell", "--deny-tool", "write"],
}


def copilot_model(stdout: str) -> str:
    sid = re.search(r"--resume=([\w-]+)", stdout)
    log = Path.home() / ".copilot" / "session-state" / (sid.group(1) if sid else "?") / "events.jsonl"
    found = re.findall(r'"modelId":"([^"]+)"', log.read_text()) if log.exists() else []
    return found[-1] if found else "auto (unknown)"


def main():
    who, save = sys.argv[1], "--save" in sys.argv[2:]
    here = Path(sys.argv[sys.argv.index("--dir") + 1]).resolve() if "--dir" in sys.argv else HERE  # e.g. scripts/fix_eval
    stamp = "" if save else "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    sample = json.loads((here / "sample.json").read_text())
    prompt = ((here / "LABELING.md").read_text() + "\n\nsample.json:\n```json\n" + json.dumps(sample, indent=1)
              + "\n```\nReply with only the JSON list, in one fenced json block.")
    p = subprocess.run(COMMANDS[who](prompt), capture_output=True, text=True, timeout=1800, cwd="/")
    if p.returncode:
        raise SystemExit(f"{who} failed: {p.stderr.strip()[:500]}")
    reply, model = p.stdout, copilot_model(p.stdout + p.stderr) if who == "gpt" else ""
    if who == "claude":
        out = json.loads(p.stdout)
        reply, model = out["result"], ",".join(sorted(out.get("modelUsage", {})))
    block = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", reply, re.S)
    labels = json.loads(block.group(1) if block else reply)
    assert sorted(x["i"] for x in labels) == list(range(len(sample))), "one label per item"
    (here / "raw").mkdir(exist_ok=True)
    (here / "raw" / f"{who}{stamp}.json").write_text(json.dumps({
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model,
        "command": COMMANDS[who]("<prompt>"), "prompt": prompt, "reply": reply}, indent=1) + "\n")
    (here / f"labels-{who}{stamp}.json").write_text(json.dumps(sorted(labels, key=lambda x: x["i"]), indent=0) + "\n")
    print(who, model, len(labels), "labels")


if __name__ == "__main__":
    main()
