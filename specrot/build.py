"""Build the Relate store (store/rfc.rl) from the raw sources fetched by sources.py.

Graph model:
  (:RFC)-[:OBSOLETES]->(:RFC)        newer document replaces the older one
  (:RFC)-[:UPDATES]->(:RFC)          newer document amends the older one
  (:RFC)-[:NORMATIVE_REF]->(:RFC)    must be read to implement
  (:RFC)-[:INFORMATIVE_REF]->(:RFC)  background reading
  (:RFC)-[:NORMATIVE_REF]->(:Series) references to a BCP/STD as a whole (e.g. BCP 14)
  (:Series)-[:INCLUDES]->(:RFC)      BCP/STD/FYI subseries members
  (:Erratum)-[:AMENDS]->(:RFC)       RFC Editor errata (no submitter names)
  (:RFC)-[:FROM_WG]->(:WorkingGroup)-[:IN_AREA]->(:Area)
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import relate

NS = {"r": "https://www.rfc-editor.org/rfc-index"}
MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October November December".split(), 1)}
BATCH = 5000


def _text(el, path):
    x = el.find(path, NS)
    return x.text.strip() if x is not None and x.text else None


def _ids(el, path):
    return [d.text for d in el.findall(f"{path}/r:doc-id", NS)]


def parse_index(path: Path):
    root = ET.parse(path).getroot()
    rfcs, series, rels = [], [], []
    for e in root.findall("r:rfc-entry", NS):
        rid = _text(e, "r:doc-id")
        month = MONTHS.get(_text(e, "r:date/r:month") or "", 1)
        year = int(_text(e, "r:date/r:year") or 0)
        abstract = " ".join(p.text.strip() for p in e.findall("r:abstract/r:p", NS) if p.text)
        rfcs.append({
            "id": rid,
            "number": int(rid[3:]),
            "title": _text(e, "r:title"),
            "year": year,
            "date": f"{year:04d}-{month:02d}",
            "status": _text(e, "r:current-status"),
            "publishedAs": _text(e, "r:publication-status"),
            "stream": _text(e, "r:stream"),
            "area": _text(e, "r:area"),
            "wg": _text(e, "r:wg_acronym"),
            "pages": int(_text(e, "r:page-count") or 0),
            "abstract": abstract,
            "keywords": [k.text for k in e.findall("r:keywords/r:kw", NS) if k.text],
            "url": f"https://www.rfc-editor.org/rfc/{rid.lower()}",
        })
        for old in _ids(e, "r:obsoletes"):
            rels.append(("OBSOLETES", rid, old))
        for old in _ids(e, "r:updates"):
            rels.append(("UPDATES", rid, old))
    for kind in ("bcp", "std", "fyi"):
        for e in root.findall(f"r:{kind}-entry", NS):
            sid = _text(e, "r:doc-id")
            members = _ids(e, "r:is-also")
            series.append({"id": sid, "kind": kind.upper(), "number": int(sid[3:]), "members": members})
    return rfcs, series, rels


def parse_refs(raw: Path, known: set[str]):
    """Datatracker names are lower-case: rfc2119, bcp14, draft-...; keep RFC and series targets."""
    rels = []
    for kind, rel in (("refnorm", "NORMATIVE_REF"), ("refinfo", "INFORMATIVE_REF")):
        p = raw / f"refs-{kind}.jsonl"
        if not p.exists():
            continue
        for line in p.open():
            o = json.loads(line)
            src, dst = o["source"].upper(), o["target"].upper()
            if src in known and dst in known and src != dst:
                rels.append((rel, src, dst))
    return sorted(set(rels))


def parse_errata(path: Path, known: set[str]):
    out = []
    for o in json.load(path.open()):
        rid = (o.get("doc-id") or "").upper()
        if rid not in known:
            continue
        out.append({
            "id": f"EID{o['errata_id']}",
            "rfc": rid,
            "type": o.get("errata_type_code"),
            "status": o.get("errata_status_code"),
            "section": (o.get("section") or "")[:80],
            "date": (o.get("submit_date") or "")[:10],
            "url": f"https://www.rfc-editor.org/errata/eid{o['errata_id']}",
        })
    return out


def _batches(rows):
    for i in range(0, len(rows), BATCH):
        yield rows[i:i + BATCH]


def load(conn, rfcs, series, rels, errata):
    run = conn.execute
    run("CREATE CONSTRAINT rfc_id IF NOT EXISTS FOR (r:RFC) REQUIRE r.id IS UNIQUE")
    run("CREATE CONSTRAINT series_id IF NOT EXISTS FOR (s:Series) REQUIRE s.id IS UNIQUE")
    run("CREATE CONSTRAINT erratum_id IF NOT EXISTS FOR (e:Erratum) REQUIRE e.id IS UNIQUE")
    run("CREATE INDEX rfc_number IF NOT EXISTS FOR (r:RFC) ON (r.number)")
    for b in _batches(rfcs):
        run("UNWIND $rows AS row CREATE (r:RFC) SET r = row", {"rows": b})
    for b in _batches(series):
        run("""UNWIND $rows AS row
               CREATE (s:Series {id: row.id, kind: row.kind, number: row.number})
               WITH s, row UNWIND row.members AS m
               MATCH (r:RFC {id: m}) CREATE (s)-[:INCLUDES]->(r)""", {"rows": b})
    by_type: dict[str, list] = {}
    for t, a, b in rels:
        by_type.setdefault(t, []).append({"a": a, "b": b})
    for t, rows in by_type.items():
        for b in _batches(rows):
            run(f"""UNWIND $rows AS row
                    MATCH (a:RFC {{id: row.a}})
                    MATCH (b {{id: row.b}}) WHERE b:RFC OR b:Series
                    CREATE (a)-[:{t}]->(b)""", {"rows": b})
    # A reference to a series (BCP 14, STD 66) is a reference to each of its member RFCs.
    for t in ("NORMATIVE_REF", "INFORMATIVE_REF"):
        run(f"""MATCH (a:RFC)-[:{t}]->(s:Series)-[:INCLUDES]->(m:RFC)
                WHERE a <> m AND NOT EXISTS {{ (a)-[:{t}]->(m) }}
                CREATE (a)-[:{t} {{via: s.id}}]->(m)""")
    for b in _batches(errata):
        run("""UNWIND $rows AS row MATCH (r:RFC {id: row.rfc})
               CREATE (e:Erratum {id: row.id, type: row.type, status: row.status,
                                  section: row.section, date: row.date, url: row.url})-[:AMENDS]->(r)""",
            {"rows": b})
    run("""MATCH (r:RFC) WHERE r.wg IS NOT NULL AND r.wg <> 'NON WORKING GROUP'
           MERGE (w:WorkingGroup {acronym: r.wg}) CREATE (r)-[:FROM_WG]->(w)""")
    run("""MATCH (r:RFC)-[:FROM_WG]->(w:WorkingGroup) WHERE r.area IS NOT NULL
           WITH w, collect(DISTINCT r.area)[0] AS area
           MERGE (a:Area {name: area}) CREATE (w)-[:IN_AREA]->(a)""")
    # derived flags used by every query
    run("MATCH (r:RFC) SET r.obsolete = EXISTS { (r)<-[:OBSOLETES]-(:RFC) }")
    run("""MATCH (r:RFC) SET r.verifiedTechnicalErrata =
           COUNT { (r)<-[:AMENDS]-(e:Erratum) WHERE e.status = 'Verified' AND e.type = 'Technical' }""")
    run("CREATE FULLTEXT INDEX rfc_text IF NOT EXISTS FOR (r:RFC) ON EACH [r.title, r.abstract]")
    classify_obsoletes(conn)


VERSION = re.compile(r"(?i)(?:version\s*|/)(\d+(?:\.\d+)?)|\b(\d+\.\d+)\b")
WORD = re.compile(r"[a-z0-9]+")


def _versions(title: str) -> set[str]:
    return {re.sub(r"\.0$", "", next(g for g in m.groups() if g)) for m in VERSION.finditer(title or "")}


def obsoletes_kind(old_title: str, new_title: str, n_successors: int) -> str:
    """Why an RFC was obsoleted, from the two titles: 'retired' (a deprecation notice, no replacement),
    'version' (a different protocol version: TLS 1.2 -> 1.3, OAuth 1.0 -> 2.0), 'split' (content moved
    into several documents), else 'edition' (a revised edition of the same specification)."""
    if DEPRECATING_TITLE.search(new_title or ""):
        return "retired"
    vo, vn = _versions(old_title), _versions(new_title)
    if vo and vn and vo != vn and not (vo & vn):
        return "version"
    if n_successors > 1:
        return "split"
    return "edition"


DEPRECATING_TITLE = re.compile(r"(?i)\b(formally )?deprecat|\bmoving .* to historic|\bobsoleting\b|\bretir")


def classify_obsoletes(conn) -> None:
    rows = [dict(r) for r in conn.execute("""
        MATCH (n:RFC)-[:OBSOLETES]->(o:RFC)
        RETURN o.id AS old, o.title AS ot, n.id AS new, n.title AS nt, COUNT { (o)<-[:OBSOLETES]-() } AS k""")]
    edits = [{"old": r["old"], "new": r["new"], "kind": obsoletes_kind(r["ot"], r["nt"], r["k"])} for r in rows]
    conn.execute("""UNWIND $rows AS x MATCH (:RFC {id: x.new})-[e:OBSOLETES]->(:RFC {id: x.old})
                    SET e.kind = x.kind""", {"rows": edits})
    # oldVersion: obsolete only because a newer protocol version exists (TLS 1.2, OAuth 1.0)
    from . import graph
    old = [r["id"] for r in conn.execute("MATCH (r:RFC) WHERE r.obsolete RETURN r.id AS id")]
    flags = [{"id": i, "v": graph.check(conn, i).level == "old-version"} for i in old]
    conn.execute("MATCH (r:RFC) SET r.oldVersion = false")
    conn.execute("UNWIND $rows AS x MATCH (r:RFC {id: x.id}) SET r.oldVersion = x.v", {"rows": flags})


def build(raw: Path, store: Path) -> dict:
    rfcs, series, rels = parse_index(raw / "rfc-index.xml")
    # NOT ISSUED entries carry no title: keep them (they hold a number) but mark them
    known = {r["id"] for r in rfcs} | {s["id"] for s in series}
    rels = sorted(set(rels)) + parse_refs(raw, known)
    errata = parse_errata(raw / "errata.json", {r["id"] for r in rfcs})
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp()) / store.name
    conn = relate.connect(str(tmp))
    load(conn, rfcs, series, rels, errata)
    conn.close()
    if store.exists():
        store.unlink()
    shutil.move(str(tmp), store)
    compact(store)
    counts = {"rfcs": len(rfcs), "series": len(series), "errata": len(errata)}
    for t in {t for t, _, _ in rels}:
        counts[t] = sum(1 for x in rels if x[0] == t)
    return counts


def compact(store: Path) -> bool:
    """Rewrite the .rl bundle without its write-ahead log (41 MB -> ~5 MB) using the relate CLI if present."""
    exe = shutil.which("relate")
    if not exe:
        return False
    import subprocess
    tmp = store.with_suffix(".compact.rl")
    if tmp.exists():
        tmp.unlink()
    subprocess.run([exe, "clone", str(store), str(tmp)], check=True, capture_output=True)
    tmp.replace(store)
    return True
