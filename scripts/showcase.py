"""Scan well-known open-source projects and store each scan in the graph as a (:Project).

    uv run python scripts/showcase.py            # clone (shallow) at the pinned commits, scan, save
    uv run python scripts/showcase.py --latest   # use each default branch's HEAD and re-pin

Pins live in scripts/showcase.json, so the numbers in the README can be reproduced exactly.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from specrot import build, graph, scan

HERE = Path(__file__).resolve().parent
PINS = HERE / "showcase.json"
PROJECTS = [
    # (name, GitHub repo, sub-path to scan or "")
    ("curl", "curl/curl", ""),
    ("requests", "psf/requests", ""),
    ("urllib3", "urllib3/urllib3", ""),
    ("httpx", "encode/httpx", ""),
    ("aiohttp", "aio-libs/aiohttp", ""),
    ("werkzeug", "pallets/werkzeug", ""),
    ("django", "django/django", ""),
    ("cpython-Lib", "python/cpython", "Lib"),
    ("go-net", "golang/go", "src/net"),
    ("go-crypto-tls", "golang/go", "src/crypto"),
    ("undici", "nodejs/undici", ""),
    ("node-lib", "nodejs/node", "lib"),
    ("hyper", "hyperium/hyper", ""),
    ("reqwest", "seanmonstar/reqwest", ""),
    ("okhttp", "square/okhttp", ""),
    ("netty-codec-http", "netty/netty", "codec-http"),
    ("nginx", "nginx/nginx", ""),
    ("haproxy", "haproxy/haproxy", ""),
    ("openssl", "openssl/openssl", ""),
    ("nghttp2", "nghttp2/nghttp2", ""),
    ("pyjwt", "jpadilla/pyjwt", ""),
    ("jsonwebtoken", "auth0/node-jsonwebtoken", ""),
    ("oauthlib", "oauthlib/oauthlib", ""),
    ("authlib", "authlib/authlib", ""),
    ("miekg-dns", "miekg/dns", ""),
    ("dnspython", "rthalley/dnspython", ""),
]


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch(repo: str, commit: str | None, dest: Path) -> str:
    if not dest.exists():
        sh("git", "clone", "-q", "--depth", "1", f"https://github.com/{repo}", str(dest))
    if commit and sh("git", "rev-parse", "HEAD", cwd=dest) != commit:
        sh("git", "fetch", "-q", "--depth", "1", "origin", commit, cwd=dest)
        sh("git", "checkout", "-q", commit, cwd=dest)
    return sh("git", "rev-parse", "HEAD", cwd=dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="data/showcase")
    ap.add_argument("--latest", action="store_true")
    a = ap.parse_args()
    pins = {} if a.latest or not PINS.exists() else json.loads(PINS.read_text())
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    repos = sorted({r for _, r, _ in PROJECTS})
    with ThreadPoolExecutor(6) as ex:
        heads = dict(zip(repos, ex.map(lambda r: fetch(r, pins.get(r), work / r.replace("/", "__")), repos)))
    conn = graph.connect(read_only=False)
    summary = []
    for name, repo, sub in PROJECTS:
        root = work / repo.replace("/", "__") / sub
        cites = scan.find_citations(root)
        url = f"https://github.com/{repo}/tree/{heads[repo]}/{sub}".rstrip("/")
        scan.save(conn, name, root, cites, url)
        conn.execute("MATCH (p:Project {name: $n}) SET p.commit = $c, p.repo = $r", {"n": name, "c": heads[repo], "r": repo})
        act = [c for c in cites if c.actionable]
        findings = scan.judge(conn, act)
        obsolete = [f for f in findings if f.verdict.level == "obsolete"]
        n_obs = sum(len(f.citations) for f in obsolete)
        summary.append({"project": name, "repo": repo, "path": sub, "commit": heads[repo], "all_matches": len(cites),
                        "citations": len(act), "rfcs": len(findings), "obsolete_rfcs": len(obsolete),
                        "obsolete_citations": n_obs,
                        "top_obsolete": [(f.verdict.id, len(f.citations), f.verdict.current) for f in obsolete[:5]]})
        print(f"{name:18} {len(act):5} citations  {len(findings):4} RFCs  {len(obsolete):3} obsolete RFCs  {n_obs:4} obsolete citations")
    conn.close()
    build.compact(graph.DEFAULT_STORE)
    PINS.write_text(json.dumps(heads, indent=2) + "\n")
    (HERE / "showcase-results.json").write_text(json.dumps(summary, indent=1) + "\n")
    c, o = sum(x["citations"] for x in summary), sum(x["obsolete_citations"] for x in summary)
    print(f"TOTAL {c} citations (tests and identifiers excluded), {o} of them ({o / c:.0%}) to obsolete RFCs; "
          f"{sum(1 for x in summary if x['obsolete_citations'])}/{len(summary)} projects affected")


if __name__ == "__main__":
    main()
