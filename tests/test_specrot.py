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


def test_ignore_file_accepts_legacy(tmp_path):
    (tmp_path / "a.py").write_text(FIXTURE)
    (tmp_path / ".specrot-ignore").write_text("RFC4627 a.py  # we still parse old JSON texts\n")
    cmd = [sys.executable, "-m", "specrot.cli", "scan", str(tmp_path), "--json"]
    out = json.loads(subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).stdout)
    assert out["accepted"] == 2 and out["counts"]["obsolete"] == 1


def test_replacement_kinds(conn):
    assert graph.check(conn, 5849).level == "old-version"      # OAuth 1.0 -> 2.0 is a new protocol version
    assert graph.check(conn, 5246).level == "old-version"      # TLS 1.2 -> 1.3
    v = graph.check(conn, 8446)                                # TLS 1.3 -> RFC 9846, same protocol
    assert v.level == "obsolete" and v.current == ["RFC9846"]
    r = graph.check(conn, 1788)                                # retired by a deprecation notice
    assert r.level == "obsolete" and r.current == [] and r.replaced_by[0]["kind"] == "retired"


def test_series_ids(conn):
    assert graph.check(conn, "BCP 14").members == ["RFC2119", "RFC8174"]
    assert graph.check(conn, "std66").members == ["RFC3986"]


@pytest.mark.parametrize("bad", ["abc", "", "RFC2616x", "-1"])
def test_bad_ids_raise_input_error(bad):
    with pytest.raises(graph.InputError):
        graph.rfc_id(bad)


def test_depth_is_capped(conn):
    with pytest.raises(graph.InputError):
        graph.reading(conn, 9110, 0)
    assert max(r["depth"] for r in graph.impact(conn, 9110, 9)) <= graph.MAX_DEPTH


def test_scan_untracked_and_utf16(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "new.c").write_text("/* RFC 2616 */\n")                       # untracked, not ignored
    (tmp_path / "w.txt").write_bytes("see RFC 7540\n".encode("utf-16"))     # UTF-16 with BOM
    assert {c.rfc for c in scan.find_citations(tmp_path)} == {"RFC2616", "RFC7540"}


def test_cli_errors_exit_2(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-m", "specrot.cli", *a], capture_output=True, text=True, cwd=ROOT)
    assert run("check", "abc").returncode == 2
    assert run("scan", str(tmp_path / "missing"), "--fail-on", "obsolete").returncode == 2
    assert run("scan", str(tmp_path), "--fail-on", "obsolte").returncode == 2
    r = run("cypher", "MATCH (n) DETACH DELETE n")
    assert r.returncode == 2 and "read-only" in r.stdout


# MCP tools, called as plain functions (the server decorator returns them unchanged)
def test_mcp_check_rfcs_per_item_errors():
    from specrot import mcp_server as m
    out = m.check_rfcs(["abc", "2616", "BCP 14"])
    assert "error" in out[0] and out[1]["level"] == "obsolete" and out[2]["members"] == ["RFC2119", "RFC8174"]


def test_mcp_errors_are_tool_errors_with_hints():
    from mcp.server.mcpserver.exceptions import ToolError
    from specrot import mcp_server as m
    for call in (lambda: m.dependents("2119", depth=0), lambda: m.search_rfcs("!!!"),
                 lambda: m.read_cypher("MATCH (n) DETACH DELETE n"), lambda: m.read_cypher("RETURN 1", limit=-1),
                 lambda: m.scan_path("/no/such/path")):
        with pytest.raises(ToolError):
            call()


def test_mcp_read_cypher_returns_node_properties():
    from specrot import mcp_server as m
    out = m.read_cypher("MATCH (r:RFC {id: 'RFC2616'}) RETURN r")
    [row] = out["rows"]
    assert out["truncated"] is False and m.read_cypher("MATCH (r:RFC) RETURN r.id", limit=5)["truncated"] is True
    assert row["r"]["labels"] == ["RFC"] and row["r"]["properties"]["id"] == "RFC2616"


def test_mcp_read_cypher_stops_a_runaway_query(monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError
    from specrot import mcp_server as m
    monkeypatch.setattr(m, "CYPHER_SECONDS", 3)
    with pytest.raises(ToolError, match="stopped after 3 s"):
        m.read_cypher("MATCH (a:RFC)-[:NORMATIVE_REF]->+(b:RFC) RETURN count(*)")
    assert m.read_cypher("RETURN 1 AS x")["rows"] == [{"x": 1}]  # the server still answers


def test_search_operator_words():
    from specrot import mcp_server as m
    assert m.search_rfcs("MUST NOT") is not None  # NOT is a query operator unless lower-cased


def test_mcp_stdio_round_trip():
    """Start `specrot mcp` as a real stdio server and call a tool through the MCP client."""
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "specrot.cli", "mcp"], cwd=str(ROOT))
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            res = await s.call_tool("check_rfcs", {"rfcs": ["8446"]})
            return names, res
    names, res = anyio.run(go)
    assert {"check_rfcs", "scan_path", "read_cypher"} <= names
    assert "RFC9846" in json.dumps([c.model_dump() for c in res.content])


def test_retired_protocol_versions_are_historic_and_document_revisions_are_editions(conn, tmp_path):
    levels = {x: graph.check(conn, x).level for x in ("2246", "4346", "5246", "5849", "3447", "2898")}
    assert levels == {"2246": "historic", "4346": "historic", "5246": "old-version", "5849": "old-version",
                      "3447": "obsolete", "2898": "obsolete"}
    (tmp_path / "tls.c").write_text("/* TLS 1.0 record layer, RFC 2246 section 6.2 */\n")
    p = subprocess.run([sys.executable, "-m", "specrot.cli", "scan", str(tmp_path), "--fail-on", "historic"],
                       cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 1


def test_section_parse_and_match():
    from specrot import sections as S
    old = S.parse("Table of Contents\n   6.5.1.  400 Bad Request ....... 58\n\n6.  Response Status Codes\n"
                  "6.5.  Client Error 4xx\n6.5.1.  400 Bad Request\n7.  Response Header Fields\n"
                  "RFC 7231            HTTP/1.1 Semantics and Content           June 2014\n")
    assert old == [("6", "Response Status Codes"), ("6.5", "Client Error 4xx"), ("6.5.1", "400 Bad Request"),
                   ("7", "Response Header Fields")]
    new = {9110: [("15", "Status Codes"), ("15.5", "Client Error 4xx"), ("15.5.1", "400 Bad Request")]}
    m = S.match(old, new)
    assert m["6.5.1"] == {"rfc": 9110, "section": "15.5.1", "title": "400 Bad Request", "exact": True}
    assert m["6"]["exact"] is False  # "Response Status Codes" ~ "Status Codes"


def test_section_now_follows_continues_as(conn):
    v = graph.check(conn, "RFC 7231 §6.5.1")
    assert v.section == "6.5.1" and [(h["rfc"], h["section"]) for h in v.section_now] == [("RFC9110", "15.5.1")]
    assert graph.check(conn, "2616#14.20").section_now[0]["rfc"] == "RFC9110"  # two hops: 2616 -> 7231 -> 9110


def test_fix_rewrites_only_unambiguous_citations(conn, tmp_path):
    from specrot import fix
    (tmp_path / "a.c").write_text("// RFC 7231, section 6.5.1\n// see RFC 2616\n// RFC 8941 Section 4.2\n")
    edits, skipped = fix.plan(conn, tmp_path)
    assert [e.new.strip() for e in edits] == ["// RFC 9110, section 15.5.1", "// RFC 9651 Section 4.2"]
    assert [(c.rfc, why) for c, why in skipped] == [("RFC2616", "no single replacement")]


def test_fix_targets_the_right_citation_on_a_line(conn, tmp_path):
    from specrot import fix
    (tmp_path / "a.md").write_text('as per [RFC 7230](https://tools.ietf.org/html/rfc7230#section-3.2.2)\n"rfc2109": 1\n')
    edits, _ = fix.plan(conn, tmp_path)
    assert edits == []  # the label (RFC 7230, split) cannot follow its link, so the line stays whole
    (tmp_path / "b.md").write_text("see https://tools.ietf.org/html/rfc7230#section-3.2.2\n")
    edits, _ = fix.plan(conn, tmp_path)
    assert [e.new for e in edits] == ["see https://tools.ietf.org/html/rfc9110#section-5.3\n"]


def test_fix_leaves_code_names_alone(conn, tmp_path):
    from specrot import fix
    (tmp_path / "t.c").write_text("enum { rfc822, rfc850 };\n/* RFC 822 dates */\n")
    edits, _ = fix.plan(conn, tmp_path)
    assert [e.line for e in edits] == [2]


def test_fix_skips_history_and_quoted_examples(conn, tmp_path):
    from specrot import fix
    (tmp_path / "n.py").write_text('# RFC 8446 for TLS 1.3 was obsoleted by RFC 9846\n'
                                   '# examples: "Section 4.2.8.1 of RFC 8446"\n# obsoletes RFC 2109\n# see RFC 8941\n')
    edits, skipped = fix.plan(conn, tmp_path)
    assert [e.line for e in edits] == [4] and len(skipped) == 3


def test_fix_keeps_code_names_protocol_strings_and_bytes(conn, tmp_path):
    from specrot import fix
    (tmp_path / "u.py").write_bytes(b"RESERVED_NCS, RFC_4122 = 0, 1\r\nfetch('RFC822.TEXT')\r\n"
                                    b"# -dateopt rfc_822\r\n# see RFC 8941\r\n")
    (tmp_path / "l.txt").write_bytes(b"caf\xe9 RFC 8941\n")  # Latin-1: not UTF-8, left alone
    edits, _ = fix.plan(conn, tmp_path)
    assert [(e.path, e.line) for e in edits] == [("u.py", 4)]
    fix.apply(tmp_path, edits)
    assert (tmp_path / "u.py").read_bytes().endswith(b"# see RFC 9651\r\n")
    assert (tmp_path / "u.py").read_bytes().count(b"\r\n") == 4


@pytest.mark.parametrize("old,new,kind", [
    ("Type of Service in the Internet Protocol Suite", "Definition of the DS Field in the IPv4 and IPv6 Headers", "edition"),
    ("HTTP Authentication: Basic and Digest Access Authentication", "Hypertext Transfer Protocol (HTTP/1.1): Authentication", "edition"),
    ("POP3 Support for UTF-8", "Post Office Protocol Version 3 (POP3) Support for UTF-8", "edition"),
    ("PKCS #1: RSA Cryptography Specifications Version 2.1", "PKCS #1: RSA Cryptography Specifications Version 2.2", "edition"),
    ("Lightweight Directory Access Protocol", "Lightweight Directory Access Protocol version 2 (LDAPv2) to Historic Status", "retired"),
    ("Real Time Streaming Protocol (RTSP)", "Real-Time Streaming Protocol Version 2.0", "version"),
    ("The Internet Key Exchange (IKE)", "Internet Key Exchange (IKEv2) Protocol", "version"),
    ("INTERNET MESSAGE ACCESS PROTOCOL - VERSION 4rev1", "Internet Message Access Protocol (IMAP) - Version 4rev2", "version"),
    ("The TLS Protocol Version 1.2", "The Transport Layer Security (TLS) Protocol Version 1.3", "version"),
    # a TLS 1.2 extension folded into TLS 1.3 is a version change; consolidations and glossaries are not
    ("Transport Layer Security (TLS) Session Hash and Extended Master Secret Extension",
     "The Transport Layer Security (TLS) Protocol Version 1.3", "version"),
    ("Internet Printing Protocol (IPP): Job Progress Attributes",
     "Internet Printing Protocol/1.1: Model and Semantics", "edition"),
    ("Internet Security Glossary", "Internet Security Glossary, Version 2", "edition"),
])
def test_obsoletes_kind(old, new, kind):
    from specrot.build import obsoletes_kind
    assert obsoletes_kind(old, new, 1) == kind


def test_section_match_prefers_the_same_number():
    from specrot import sections as S
    m = S.match([("4", "Handshake Protocol")], {9846: [("4", "Handshake Protocol"), ("B.3", "Handshake Protocol")]})
    assert m["4"]["section"] == "4"


def test_scan_reports_skipped_large_files(tmp_path):
    (tmp_path / "big.txt").write_text("RFC 2616\n" * 300)
    p = subprocess.run([sys.executable, "-m", "specrot.cli", "scan", str(tmp_path), "--json", "--max-bytes", "100"],
                       cwd=ROOT, capture_output=True, text=True)
    assert json.loads(p.stdout)["skipped_large_files"] == ["big.txt"]


def test_fix_judge_examples_from_cpython(conn, tmp_path):
    from specrot import fix
    lines = ["typ, dat = self.fetch(num, '(FLAGS INTERNALDATE RFC822)')",   # protocol string, single quotes
             "# UUIDs as specified in RFC 4122/9562",                          # replacement already named
             "# RFC 2822, which is the followon to RFC 822",                   # history / duplicate target
             "# RFC 7231: 6.3.6.",                                              # uncaptured section
             "#   RFC 2732: Format for Literal IPv6 Addresses in URL's",       # reference list entry
             "# Modified 04-Oct-1995 by Jack Jansen; RFC 3548 support",        # dated attribution
             "# see RFC 8941"]
    (tmp_path / "x.py").write_text("\n".join(lines) + "\n")
    edits, _ = fix.plan(conn, tmp_path)
    assert [e.line for e in edits] == [7]


def test_edition_then_version_chain_is_obsolete(conn):
    v = graph.check(conn, 4492)
    assert v.level == "obsolete" and v.replaced_by[0]["same_version"] == "RFC8422"
    assert graph.check(conn, 5246).level == "old-version"


def test_sphinx_rfc_roles_are_found_and_fixed(conn, tmp_path):
    from specrot import fix
    found = scan.find_in_text("because :rfc:`RFC 7232 <7232#section-4.1>` and :rfc:`2822`")
    assert [(c.rfc, c.section) for c in found] == [("RFC7232", "4.1"), ("RFC2822", None)]
    (tmp_path / "x.rst").write_text("a valid :rfc:`2822` style header\nper :rfc:`7232#section-3.1`\n")
    edits, _ = fix.plan(conn, tmp_path)
    assert [e.new.strip() for e in edits] == ["a valid :rfc:`5322` style header", "per :rfc:`9110#section-13.1.1`"]


def test_fix_leaves_quotations_spanning_lines(conn, tmp_path):
    from specrot import fix
    (tmp_path / "x.py").write_text('# From RFC 3986:\n#\n# "A host identified by an IP literal, version 6\n'
                                   '# [RFC3513] or later, is distinguished by enclosing it"\n# see RFC 3513\n')
    edits, _ = fix.plan(conn, tmp_path)
    assert [e.line for e in edits] == [5]


def test_scan_walks_a_folder_the_enclosing_repo_ignores(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("vendored/\n")
    (tmp_path / "vendored").mkdir()
    (tmp_path / "vendored" / "h11.py").write_text("# per RFC 7230\n")
    assert [c.rfc for c in scan.find_citations(tmp_path / "vendored")] == ["RFC7230"]


def test_ignore_star_accepts_any_rfc_under_a_path(tmp_path):
    (tmp_path / ".specrot-ignore").write_text("* data/*  # evaluation data\n")
    rules = scan.load_ignore(tmp_path)
    c = scan.Citation("data/x.json", 1, "RFC2616", None, "")
    assert scan.accepted(c, rules) and not scan.accepted(scan.Citation("src/a.py", 1, "RFC2616", None, ""), rules)


def test_rfc850_date_is_a_format_name():
    kinds = lambda t: [c.kind for c in scan.find_in_text(t)]
    assert kinds("# accept RFC 850 dates too") == ["identifier"]
    assert kinds("RFC 850-date and asctime") == ["identifier"]
    assert kinds("see RFC 850 for USENET") == ["prose"]


def test_import_rule_matches_only_import_lines():
    kinds = lambda t: [c.kind for c in scan.find_in_text(t)]
    assert kinds("from RFC 7231, this document takes the status codes") == ["prose"]
    assert kinds("import rfc822") == ["identifier"]
    assert kinds("from rfc822 import parsedate  # old module") == ["identifier"]


def test_fix_skips_version_changes_and_reference_link_labels(conn, tmp_path):
    from specrot import fix
    lines = ["/* ECC ciphersuites from RFC4492 */",                   # 4492 -> 8422 -> TLS 1.3: a decision
             "clients, as defined in RFC 6962.",                      # CT -> CT Version 2.0
             "per [RFC 7230, section 6.3.2][]. Only enable",          # Markdown reference link label
             "(see Appendix E.6 of RFC8446). Note",                   # uncaptured appendix
             "// supported_versions instead. See RFC 8446, sections 4.1.3 and 4.2.1.",  # plural sections
             "// field, according to RFC 8446, Section",              # section wrapped onto the next line
             "Violate RFC 7231/6.4.4 and do not convert POST",        # slash section
             "[RFC 8446]:",                                           # link definition, URL on the next line
             "see RFC 8446 D.4 for middlebox",                        # bare appendix (E.4 in RFC 9846)
             "urllib3 is RFC 3986 and RFC 6874 compliant",            # 6874 -> 9844 is a different design
             "# Accept-Language. From RFC 2616, section 14.4 and 3.9",  # second section (Django, PR 16257)
             "# sections 2.2 and 2.3 of RFC 2396:",                   # plural sections before the citation
             "# see RFC 8941",
             "as defined in section 3.1 of RFC 7232."]                # singular: mapped (RFC 9110 §13.1.1)
    (tmp_path / "x.md").write_text("\n".join(lines) + "\n")
    edits, _ = fix.plan(conn, tmp_path)
    assert [e.line for e in edits] == [13, 14]
    assert "section 13.1.1 of RFC 9110" in edits[1].new
