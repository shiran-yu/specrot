"""Choose the maintainer PRs for run.py by a fixed search and a fixed rule; writes cohort.json.

    GITHUB_TOKEN=... uv run python -m scripts.maintainer_eval.cohort

Search: `repo:<r> is:pr is:merged RFC in:title` for each of the 26 scanned projects (GitHub issue search,
all pages; Go and others that merge outside GitHub PRs yield few or none). Rule, independent of specrot's
graph: a PR is included when, in some modified file, a removed line cites RFC N and the added lines of
that file cite another RFC and not N (a citation was replaced), and the title does not start with "[" (a backport
of another PR to a release branch). Every candidate is kept with its reason.
"""
import json
import time
import urllib.error
import urllib.parse

from scripts.maintainer_eval.run import HERE, get
from scripts.showcase import PROJECTS
from specrot import scan

QUERY = "repo:{repo} is:pr is:merged RFC in:title"


def rfcs(lines: list[str]) -> set[str]:
    return {c.rfc for line in lines for c in scan.find_in_text(line)}


def replaces(patch: str) -> list[str]:
    """RFCs cited on removed lines and replaced by another RFC on added lines of the same file."""
    lines = patch.splitlines()
    gone = rfcs([x[1:] for x in lines if x.startswith("-")])
    came = rfcs([x[1:] for x in lines if x.startswith("+")])
    return sorted(gone - came) if came - gone else []


def main():
    out = []
    for repo in sorted({r for _, r, _ in PROJECTS}):
        page = 1
        while True:
            q = urllib.parse.quote(QUERY.format(repo=repo))
            try:
                res = json.loads(get(f"https://api.github.com/search/issues?q={q}&per_page=100&page={page}"))
            except urllib.error.HTTPError as e:  # 422: GitHub will not search this repository
                print(repo, f"search failed: HTTP {e.code}")
                out.append({"repo": repo, "pr": None, "title": None, "closed_at": None, "included": False,
                            "replaced": {}, "error": f"search failed: HTTP {e.code}"})
                break
            for it in res["items"]:
                try:
                    files = json.loads(get(f"https://api.github.com/repos/{repo}/pulls/{it['number']}/files?per_page=100"))
                except urllib.error.HTTPError as e:  # e.g. 422 for a diff GitHub will not list
                    files, it["error"] = [], f"files not available: HTTP {e.code}"
                hit = {f["filename"]: r for f in files if f["status"] == "modified" and (r := replaces(f.get("patch") or ""))}
                backport = it["title"].startswith("[")  # "[3.14] gh-...": the same change on another branch
                out.append({"repo": repo, "pr": it["number"], "title": it["title"], "closed_at": it["closed_at"],
                            "included": bool(hit) and not backport, "replaced": hit,
                            **({"excluded": "backport of another PR"} if hit and backport else {}),
                            **({"error": it["error"]} if "error" in it else {})})
            time.sleep(2.5)  # search API: 30 requests a minute
            if len(res["items"]) < 100:
                break
            page += 1
        print(repo, sum(1 for x in out if x["repo"] == repo), "candidates",
              sum(1 for x in out if x["repo"] == repo and x["included"]), "included")
    (HERE / "cohort.json").write_text(json.dumps({"query": QUERY, "candidates": out}, indent=1) + "\n")
    print("total", len(out), "candidates,", sum(x["included"] for x in out), "included")


if __name__ == "__main__":
    main()
