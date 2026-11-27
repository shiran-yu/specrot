"""specrot command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

import relate

from . import graph, scan

console = Console(highlight=False)
STYLE = {"obsolete": "bold red", "old-version": "magenta", "historic": "red", "amended": "yellow", "ok": "green",
         "unknown": "dim"}
ICON = {"obsolete": "✗", "old-version": "↑", "historic": "✗", "amended": "!", "ok": "✓", "unknown": "?"}


def _label(v: graph.Verdict) -> str:
    return f"[{STYLE[v.level]}]{ICON[v.level]} {v.level.upper()}[/]"


def _moved(section: str, homes: list[dict]) -> str:
    """'§6.5.1 → RFC9110 §15.5.1'; '~' marks a reworded heading; '?' when no heading matched."""
    if not homes:
        return f"§{section} → ?"
    return f"§{section} → " + ", ".join(f"{h['rfc']} §{h['section']}{'' if h['exact'] else ' ~'}" for h in homes)


def _verdict_tree(v: graph.Verdict) -> Tree:
    head = f"{_label(v)}  [bold]{v.id}[/]"
    if v.members:
        head += f"  {v.title}"
    elif v.known:
        head += f"  {v.title}  [dim]({v.date}, {v.status.title() if v.status else '?'})[/]"
    else:
        head += "  [dim]no such RFC in the index[/]"
    t = Tree(head)
    for m in v.members:
        t.add(f"{m}")
    if v.replaced_by:
        retired = all(p["kind"] == "retired" for p in v.replaced_by)
        r = t.add(f"[bold]{'retired by' if retired else 'replaced by'}[/] (OBSOLETES chains to documents still in force)")
        for p in v.replaced_by:
            colour = "dim" if p["kind"] == "retired" else "bold green"
            r.add(" → ".join(p["chain"][:-1] + [f"[{colour}]{p['current']}[/]"]) + f"  {p['title']}"
                  + f"  [dim]({graph.KIND_TEXT[p['kind']]})[/]"
                  + (f"\n  [dim]staying on the older protocol version? {p['same_version']} is its newest edition[/]"
                     if p.get("same_version") else ""))
    if v.section and v.obsolete:
        s = t.add(f"[bold]section {v.section}[/] {v.section_now[0]['was'] if v.section_now else ''} (CONTINUES_AS, by heading)")
        for h in v.section_now:
            s.add(f"[bold green]{h['rfc']} §{h['section']}[/]  {h['title']}" + ("" if h["exact"] else "  [dim](reworded heading)[/]"))
        if not v.section_now:
            s.add(f"[dim]no section of the replacement has this heading, or {v.id} has no section {v.section}; see the change log[/]")
    elif v.section:
        t.add(f"[dim]section {v.section}: {v.id} is not obsolete, so the citation stays as it is[/]")
    if v.deprecations:
        d = t.add("[bold]partly deprecated by[/]")
        for u in v.deprecations:
            d.add(f"[yellow]{u['id']}[/] {u['title']} [dim]({u['date']})[/]")
    others = [u for u in v.updated_by if u not in v.deprecations]
    if others:
        u = t.add(f"[bold]updated by[/] {len(others)} document(s) still in force")
        for x in others[:8]:
            u.add(f"{x['id']} {x['title']} [dim]({x['date']})[/]")
        if len(others) > 8:
            u.add(f"[dim]… {len(others) - 8} more[/]")
    if v.errata:
        t.add(f"[bold]{v.errata}[/] verified technical errata  [dim]https://www.rfc-editor.org/errata/{v.id.lower()}[/]")
    if v.series:
        t.add("part of " + ", ".join(v.series))
    return t


def cmd_check(a, conn):
    verdicts = [graph.check(conn, x) for x in a.rfc]
    if a.json:
        print(json.dumps([v.to_dict() for v in verdicts], indent=2))
        return
    for v in verdicts:
        console.print(_verdict_tree(v))


def _markdown(findings, root) -> str:
    lines = [f"## specrot report for `{root}`", "", "| RFC | Status | Replaced by / amended by | Cited at |", "|---|---|---|---|"]
    for f in findings:
        v = f.verdict
        if v.level == "ok":
            continue
        fix = ", ".join(v.current) if v.current else ", ".join(u["id"] for u in v.updated_by[:4])
        moved = list(dict.fromkeys(_moved(c.section, c.section_now) for c in f.citations if c.section and v.obsolete))
        fix += "".join(f"<br>{m}" for m in moved[:4]) + (" …" if len(moved) > 4 else "")
        where = ", ".join(f"`{c.path}:{c.line}`" for c in f.citations[:3]) + (" …" if len(f.citations) > 3 else "")
        lines.append(f"| [{v.id}]({v.url or ''}) {v.title or ''} | {v.level} | {fix} | {where} |")
    return "\n".join(lines)


def cmd_scan(a, conn):
    root = Path(a.path)
    fail = {x.strip() for x in (a.fail_on or "").split(",") if x.strip()}
    if fail - set(graph.LEVELS):
        raise graph.InputError(f"--fail-on takes {', '.join(graph.LEVELS)}; got {', '.join(sorted(fail - set(graph.LEVELS)))}")
    too_big: list[str] = []
    found = scan.find_citations(root, a.include_history, too_big, a.max_bytes)
    citations = found if a.all_kinds else [c for c in found if c.actionable]
    rules = scan.load_ignore(root)
    n_accepted = sum(1 for c in citations if scan.accepted(c, rules))
    citations = [c for c in citations if not scan.accepted(c, rules)]
    findings = scan.judge(conn, citations)
    counts = {lvl: sum(1 for f in findings if f.verdict.level == lvl) for lvl in graph.LEVELS}
    if a.baseline:  # accept today's findings so a CI gate fails only on new ones
        levels = fail or {"obsolete"}
        keep = sorted({(f.verdict.id, c.path) for f in findings if f.verdict.level in levels for c in f.citations})
        base = root if root.is_dir() else root.parent
        with open(base / scan.IGNORE_FILE, "a") as fh:
            fh.writelines(f"{rid} {path}  # baseline\n" for rid, path in keep)
        console.print(f"added {len(keep)} (RFC, file) pair(s) to {base / scan.IGNORE_FILE}; review them, then commit")
        return 0
    if a.save:
        conn.close()
        wconn = graph.connect(a.store, read_only=False)
        scan.save(wconn, a.save, root.resolve(), citations, a.url)
        wconn.close()
    if a.json:
        print(json.dumps({"root": str(root), "citations": len(citations), "accepted": n_accepted, "counts": counts,
                          "skipped_large_files": too_big,
                          "findings": [f.to_dict() for f in findings]}, indent=2))
    elif a.markdown:
        print(_markdown(findings, root))
    else:
        console.print(f"[bold]{len(citations)}[/] RFC citations of [bold]{len(findings)}[/] distinct RFCs in {root}"
                      + ("" if a.all_kinds else f"  [dim](skipped {len(found) - len(citations) - n_accepted} in tests or identifiers like time.RFC1123; --all-kinds to include)[/]"))
        console.print("  ".join(f"[{STYLE[k]}]{ICON[k]} {k} {n}[/]" for k, n in counts.items() if n)
                      + (f"  [dim]{n_accepted} accepted by {scan.IGNORE_FILE}[/]" if n_accepted else ""))
        tab = Table(show_lines=False, header_style="bold")
        for col in ("status", "RFC", "title", "replaced by / amended by", "cited at"):
            tab.add_column(col, overflow="fold")
        for f in findings:
            v = f.verdict
            if v.level == "ok" and not a.all:
                continue
            fix = ", ".join(v.current) if v.current else (
                "⚠ " + ", ".join(u["id"] for u in v.deprecations) if v.deprecations else
                ", ".join(u["id"] for u in v.updated_by[:3]) + (" …" if len(v.updated_by) > 3 else ""))
            if v.errata and v.level == "amended":
                fix += f" (+{v.errata} errata)" if fix else f"{v.errata} errata"
            moved = list(dict.fromkeys(_moved(c.section, c.section_now) for c in f.citations if c.section and v.obsolete))
            fix += "".join(f"\n[dim]{m}[/]" for m in moved[:3]) + (f"\n[dim]… {len(moved) - 3} more sections[/]" if len(moved) > 3 else "")
            where = f"{f.citations[0].path}:{f.citations[0].line}" + (f" +{len(f.citations) - 1}" if len(f.citations) > 1 else "")
            tab.add_row(_label(v), v.id, (v.title or "")[:60], fix, where)
        console.print(tab)
        if too_big:
            console.print(f"[yellow]skipped {len(too_big)} file(s) over {a.max_bytes:,} bytes or unreadable[/] (--max-bytes to include): "
                          + ", ".join(too_big[:5]) + (" …" if len(too_big) > 5 else ""))
        if a.save:
            console.print(f"saved as (:Project {{name: '{a.save}'}}) in {a.store}")
    if fail and any(counts.get(k) for k in fail):
        sys.exit(1)


def cmd_read(a, conn):
    rows = graph.reading(conn, a.rfc, a.depth)
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    tab = Table(title=f"Normative reading list for {graph.rfc_id(a.rfc)} (depth ≤ {graph.clamp_depth(a.depth)})", header_style="bold")
    for col in ("hop", "RFC", "title", "note"):
        tab.add_column(col, overflow="fold")
    for r in rows:
        note = f"[red]obsolete → {', '.join(r['current']) or 'retired'}[/]" if r["obsolete"] else ""
        tab.add_row(str(r["depth"]), r["id"], r["title"] or "", note)
    console.print(tab)
    stale = sum(1 for r in rows if r["obsolete"])
    console.print(f"{len(rows)} documents, [red]{stale}[/] of them obsolete (their replacements are named).")


def cmd_impact(a, conn):
    rows = graph.impact(conn, a.rfc, a.depth)
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    tab = Table(title=f"Documents still in force that normatively depend on {graph.rfc_id(a.rfc)} "
                      f"(depth ≤ {graph.clamp_depth(a.depth)})", header_style="bold")
    for col in ("hop", "RFC", "title", "date", "status"):
        tab.add_column(col, overflow="fold")
    for r in rows[: a.limit]:
        tab.add_row(str(r["depth"]), r["id"], r["title"] or "", r["date"], (r["status"] or "").title())
    console.print(tab)
    console.print(f"{len(rows)} dependents" + (f" (showing {a.limit})" if len(rows) > a.limit else ""))


def cmd_search(a, conn):
    rows = graph.search(conn, a.query, a.limit)
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    tab = Table(header_style="bold")
    for col in ("RFC", "title", "date", "status"):
        tab.add_column(col, overflow="fold")
    for r in rows:
        st = "[red]obsolete[/]" if r["obsolete"] else (r["status"] or "").title()
        tab.add_row(r["id"], r["title"] or "", r["date"], st)
    console.print(tab)


def cmd_cypher(a, conn):
    params = json.loads(a.params) if a.params else {}
    if a.write:
        conn.close()
        conn = graph.connect(a.store, read_only=False)
    rows = [dict(r) for r in conn.execute(a.statement, params)]
    print(json.dumps(rows, indent=2, default=str))


def cmd_fix(a, conn):
    from . import fix
    root = Path(a.path)
    edits, skipped = fix.plan(conn, root, a.include_history)
    if a.write:
        fix.apply(root, edits)
    else:
        sys.stdout.write(fix.diff(root, edits))
    err = Console(stderr=True)
    err.print(f"[bold]{len(edits)}[/] citation(s) {'rewritten' if a.write else 'to rewrite (review the diff; --write applies it)'}"
              f", [bold]{len(skipped)}[/] obsolete citation(s) left for a person:")
    for c, why in skipped[: a.limit]:
        err.print(f"  [dim]{c.path}:{c.line}[/] {c.rfc}{' §' + c.section if c.section else ''}: {why}")
    if len(skipped) > a.limit:
        err.print(f"  [dim]… {len(skipped) - a.limit} more (--limit)[/]")


def cmd_build(a, _conn):
    from . import build, sources
    raw = Path(a.raw)
    sources.fetch(raw, force=a.refresh)
    console.print(build.build(raw, Path(a.store)))


def cmd_mcp(a, _conn):
    import os
    os.environ.setdefault("SPECROT_STORE", a.store)
    from . import mcp_server
    mcp_server.main()


def main(argv=None):
    p = argparse.ArgumentParser(prog="specrot", description="Find the dead RFCs your code still cites (a Relate graph).")
    p.add_argument("--store", default=str(graph.DEFAULT_STORE), help="Relate store (default: the committed store/rfc.rl)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check", help="status of one or more RFCs: obsolete, amended, replacements")
    s.add_argument("rfc", nargs="+")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("scan", help="find RFC citations in a file or directory and judge them")
    s.add_argument("path")
    s.add_argument("--all", action="store_true", help="also list citations that are current")
    s.add_argument("--include-history", action="store_true", help="also scan CHANGELOG/HISTORY/NEWS files")
    s.add_argument("--all-kinds", action="store_true", help="also count citations in tests and identifiers (time.RFC1123)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--markdown", action="store_true")
    s.add_argument("--fail-on", default="", help="comma list of levels that exit 1, e.g. obsolete,historic")
    s.add_argument("--save", metavar="NAME", help="write the scan into the graph as (:Project {name: NAME})")
    s.add_argument("--url", help="project URL stored with --save")
    s.add_argument("--max-bytes", type=int, default=scan.MAX_BYTES, help="skip (and report) larger files")
    s.add_argument("--baseline", action="store_true",
                   help="append today's findings (levels from --fail-on, default obsolete) to .specrot-ignore, so CI fails only on new ones")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("fix", help="rewrite unambiguous obsolete citations (RFC and section) as a diff to review")
    s.add_argument("path")
    s.add_argument("--write", action="store_true", help="apply the edits instead of printing the diff")
    s.add_argument("--include-history", action="store_true")
    s.add_argument("--limit", type=int, default=20, help="skipped citations to list")
    s.set_defaults(fn=cmd_fix)

    s = sub.add_parser("read", help="normative reading list (what you must read to implement an RFC)")
    s.add_argument("rfc")
    s.add_argument("--depth", type=int, default=1)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("impact", help="documents still in force that normatively depend on an RFC")
    s.add_argument("rfc")
    s.add_argument("--depth", type=int, default=1)
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_impact)

    s = sub.add_parser("search", help="full-text search over RFC titles and abstracts")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("cypher", help="run any Cypher statement against the store (read-only unless --write)")
    s.add_argument("statement")
    s.add_argument("--params", help="JSON object of parameters")
    s.add_argument("--write", action="store_true")
    s.set_defaults(fn=cmd_cypher)

    s = sub.add_parser("build", help="download the sources and rebuild the store")
    s.add_argument("--raw", default="data/raw")
    s.add_argument("--refresh", action="store_true", help="download again even if cached")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("mcp", help="run the MCP server on stdio (for Claude Code, Cursor, ...)")
    s.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    conn = None
    try:
        conn = None if a.cmd in ("build", "mcp") else graph.connect(a.store)
        a.fn(a, conn)
    except graph.InputError as e:
        console.print(f"[red]error:[/] {e}")
        sys.exit(2)
    except json.JSONDecodeError as e:
        console.print(f"[red]error:[/] --params is not valid JSON: {e}")
        sys.exit(2)
    except relate.Error as e:
        hint = " (another process has the store open for writing; close it or use --store)" if "lock" in str(e).lower() else ""
        console.print(f"[red]Relate error:[/] {e}{hint}")
        sys.exit(2)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
