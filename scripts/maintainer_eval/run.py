"""Compare `specrot fix` with citation updates that project maintainers merged themselves.

    uv run python -m scripts.maintainer_eval.run     # writes scripts/maintainer_eval/results.json

For each merged PR that cohort.py selected (cohort.json: the search, every candidate, the rule), the changed files are fetched at the PR's base and merge commits from
GitHub, `specrot fix` runs on the base files, and every base line the maintainers changed that cites an
RFC is compared with fix's proposal: whether specrot calls the replaced RFC obsolete, whether `fix` proposes an edit, and whether
the RFC (and section) it proposes is one the maintainers wrote in the block that replaced the line;
fix edits on lines the maintainers left alone are listed too. Today's graph is
used, so a 2017 PR is judged against today's replacements.
"""
import difflib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

from specrot import fix, graph, scan

HERE = Path(__file__).resolve().parent
WORK = HERE.parent.parent / "data" / "maintainer_eval"
# the PRs cohort.py selected by its fixed search and rule
PRS = [(c["repo"], c["pr"]) for c in json.loads((HERE / "cohort.json").read_text())["candidates"] if c["included"]]


def get(url: str) -> bytes:
    h = {"User-Agent": "specrot-eval", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN") and "api.github.com" in url:  # optional: 60 unauthenticated calls an hour
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch(repo: str, n: int) -> dict:
    cache = WORK / f"{repo.replace('/', '__')}_{n}" / "pr.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pr = json.loads(get(f"https://api.github.com/repos/{repo}/pulls/{n}"))
    files = json.loads(get(f"https://api.github.com/repos/{repo}/pulls/{n}/files?per_page=100"))
    out = {"repo": repo, "pr": n, "title": pr["title"], "merged_at": pr["merged_at"], "merged_by": pr["merged_by"]["login"],
           "base": pr["base"]["sha"], "merge": pr["merge_commit_sha"], "files": []}
    for f in files:
        if f["status"] != "modified":
            continue
        for side, sha in (("base", out["base"]), ("merged", out["merge"])):
            p = WORK / f"{repo.replace('/', '__')}_{n}" / side / f["filename"]
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(get(f"https://raw.githubusercontent.com/{repo}/{sha}/{f['filename']}"))
        out["files"].append(f["filename"])
    cache.write_text(json.dumps(out))
    return out


def cites_of(lines: list[str]) -> set[tuple[str, str | None]]:
    return {(c.rfc, c.section) for line in lines for c in scan.find_in_text(line)}


def compare(conn, pr: dict) -> dict:
    """One row per (base line, RFC) whose RFC the maintainers replaced: the RFC is cited on a changed base
    line and absent from the merged block that replaced it."""
    root = WORK / f"{pr['repo'].replace('/', '__')}_{pr['pr']}"
    if not (root / "base" / ".git").exists():  # its own repo: data/ is ignored by the specrot checkout
        subprocess.run(["git", "init", "-q", str(root / "base")], check=True)
    edits, _ = fix.plan(conn, root / "base", include_history=True)
    by_line = {(e.path, e.line): e for e in edits}
    rows, untouched = [], []
    for path in pr["files"]:
        base = (root / "base" / path).read_text(errors="replace").splitlines()
        merged = (root / "merged" / path).read_text(errors="replace").splitlines()
        changed = set()
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, merged, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            # join the block's lines without comment markers, so "RFC" / "# 3986 Sections 2.2" reads as one citation
            block = cites_of([" ".join(re.sub(r"^\s*(#|//|/?\*+)?\s*", "", m) for m in merged[j1:j2])]) | cites_of(merged[j1:j2])
            block_rfcs = {r for r, _ in block}
            for i in range(i1, i2):
                changed.add(i + 1)
                for rfc in dict.fromkeys(c.rfc for c in scan.find_in_text(base[i])):
                    if rfc in block_rfcs:
                        continue  # kept by the maintainers: not an update
                    e = by_line.get((path, i + 1))
                    proposed = {x for x in cites_of([e.new]) if x[0] != rfc} - cites_of([e.old]) if e else set()
                    rows.append({"file": path, "line": i + 1, "rfc": rfc, "old": base[i].strip(),
                                 "maintainer": " / ".join(m.strip() for m in merged[j1:j2])[:300],
                                 "level": graph.check(conn, rfc).level, "fix": e.new.strip() if e else None,
                                 "same_rfc": bool(proposed) and {r for r, _ in proposed} <= block_rfcs,
                                 "same_section": bool(proposed) and all(s is None or (r, s) in block for r, s in proposed)
                                                 and any(s for _, s in proposed)})
        untouched += [{"file": e.path, "line": e.line, "old": e.old.strip(), "fix": e.new.strip()}
                      for e in edits if e.path == path and e.line not in changed]
    return {"rows": rows, "fix_on_untouched_lines": untouched}


def main():
    conn = graph.connect()
    results = []
    for repo, n in PRS:
        pr = fetch(repo, n)
        pr.update(compare(conn, pr))
        rows = pr["rows"]
        pr["summary"] = {"replaced_citations": len(rows), "obsolete": sum(r["level"] == "obsolete" for r in rows),
                         "fix_proposed": sum(r["fix"] is not None for r in rows),
                         "same_rfc": sum(r["same_rfc"] for r in rows), "same_section": sum(r["same_section"] for r in rows),
                         "fix_on_untouched_lines": len(pr["fix_on_untouched_lines"])}
        print(f"{repo}#{n}", pr["summary"])
        results.append(pr)
    total = {k: sum(p["summary"][k] for p in results) for k in results[0]["summary"]}
    print("TOTAL", total)
    (HERE / "results.json").write_text(json.dumps({"total": total, "prs": results}, indent=1) + "\n")


if __name__ == "__main__":
    main()
