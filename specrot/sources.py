"""Download the open sources the graph is built from (metadata only, no RFC full texts).

- rfc-index.xml   RFC Editor index: every RFC, BCP and STD with obsoletes/updates links.
- errata.json     RFC Editor errata API (submitter names are dropped at build time).
- refs-*.jsonl    IETF Datatracker: normative / informative references made by RFCs.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

RFC_INDEX = "https://www.rfc-editor.org/rfc-index.xml"
ERRATA = "https://www.rfc-editor.org/api/v1/errata.json"
DATATRACKER = "https://datatracker.ietf.org"
REF_KINDS = ("refnorm", "refinfo")
UA = {"User-Agent": "specrot/0.1 (+https://github.com/shiran-yu/specrot)"}


def _get(url: str, retries: int = 4) -> bytes:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:  # network hiccup: back off and retry
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _refs(kind: str, out: Path) -> int:
    """Page through Datatracker relateddocument rows whose source is an RFC."""
    url = f"/api/v1/doc/relateddocument/?relationship__slug={kind}&source__type=rfc&order_by=id&limit=1000&format=json"
    n = 0
    with out.open("w") as f:
        while url:
            page = json.loads(_get(DATATRACKER + url))
            for o in page["objects"]:
                src = o["source"].rstrip("/").rsplit("/", 1)[-1]
                dst = o["target"].rstrip("/").rsplit("/", 1)[-1]
                f.write(json.dumps({"source": src, "target": dst}) + "\n")
                n += 1
            url = page["meta"]["next"]
    return n


def fetch(raw: Path, force: bool = False) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    for name, url in (("rfc-index.xml", RFC_INDEX), ("errata.json", ERRATA)):
        p = raw / name
        if force or not p.exists():
            print(f"fetch {url}")
            p.write_bytes(_get(url))
    for kind in REF_KINDS:
        p = raw / f"refs-{kind}.jsonl"
        if force or not p.exists():
            print(f"fetch Datatracker {kind} (paged, ~1 min)")
            print(f"  {_refs(kind, p)} rows")
