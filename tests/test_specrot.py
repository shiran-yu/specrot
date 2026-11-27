"""Tests run against the committed store (store/rfc.rl), read-only."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from specrot import graph, scan

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def conn():
    c = graph.connect()
    yield c
    c.close()


def test_rfc_id_forms():
    assert graph.rfc_id("2616") == "RFC2616"
    assert graph.rfc_id("RFC 7231") == "RFC7231"
    assert graph.rfc_id("rfc-0822") == "RFC822"
    assert graph.rfc_id(9110) == "RFC9110"


def test_http_lineage(conn):
    v = graph.check(conn, 2616)
    assert v.level == "obsolete"
    assert v.current == ["RFC9110", "RFC9111", "RFC9112"]
    assert all(r["chain"][0] == "RFC2616" for r in v.replaced_by)


def test_live_document_is_not_obsolete(conn):
    v = graph.check(conn, 9110)
    assert not v.obsolete and v.level in {"ok", "amended"}
    assert "STD97" in v.series


def test_oauth_updates_include_security_bcp(conn):
    ids = [u["id"] for u in graph.check(conn, 6749).updated_by]
    assert "RFC9700" in ids


def test_unknown_rfc(conn):
    assert graph.check(conn, 99999).level == "unknown"


def test_reading_list_resolves_series_and_flags_obsolete(conn):
    rows = {r["id"]: r for r in graph.reading(conn, 9110, 1)}
    assert "RFC3986" in rows  # cited as STD 66
    assert "RFC2119" in rows  # cited as BCP 14


def test_impact(conn):
    ids = {r["id"] for r in graph.impact(conn, 9110, 1)}
    assert len(ids) > 10


def test_search(conn):
    assert graph.search(conn, "HTTP caching", 3)[0]["id"] == "RFC9111"


FIXTURE = """\
# Parses Date headers as in RFC 2616, section 3.3.1
# JSON per rfc4627 (see https://tools.ietf.org/html/rfc4627)
# URIs: RFC-3986
DATE_FMT = time.RFC1123Z
"""


def test_find_citations(tmp_path):
    (tmp_path / "a.py").write_text(FIXTURE)
    (tmp_path / "CHANGELOG.md").write_text("0.1: follow RFC 2068\n")
    cites = scan.find_citations(tmp_path)
    assert [(c.rfc, c.section) for c in cites] == [
        ("RFC2616", "3.3.1"), ("RFC4627", None), ("RFC4627", None), ("RFC3986", None), ("RFC1123", None)]
    assert any(c.rfc == "RFC2068" for c in scan.find_citations(tmp_path, include_history=True))


def test_judge_orders_obsolete_first(conn, tmp_path):
    (tmp_path / "a.py").write_text(FIXTURE)
    findings = scan.judge(conn, scan.find_citations(tmp_path))
    assert findings[0].verdict.level == "obsolete"
    assert {f.verdict.id for f in findings if f.verdict.level == "obsolete"} == {"RFC2616", "RFC4627"}


def test_cli_scan_json_and_fail_on(tmp_path):
    (tmp_path / "a.py").write_text(FIXTURE)
    cmd = [sys.executable, "-m", "specrot.cli", "scan", str(tmp_path), "--json", "--fail-on", "obsolete"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["counts"]["obsolete"] == 2
