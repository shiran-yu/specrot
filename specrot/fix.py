"""Rewrite stale RFC citations to the current document and section, as a unified diff a person reviews.

Only unambiguous cases are rewritten:
  - level `obsolete` (not old-version or historic: those need a decision, not a rename);
  - with a section: exactly one current section whose heading matches the old one exactly;
  - without a section: exactly one current replacement (a split such as RFC 2616 is left alone);
  - links only on RFC hosts, with no anchor or a #section-/#appendix- anchor.
Everything else is listed with the reason it was skipped.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from . import graph, scan

RFC_HOSTS = re.compile(r"(?i)(rfc-editor\.org/rfc/|tools\.ietf\.org/html/|datatracker\.ietf\.org/doc/html/|ietf\.org/rfc/)$")


@dataclass
class Edit:
    path: str
    line: int
    old: str
    new: str
    note: str


def _target(c: scan.Citation, v: graph.Verdict) -> tuple[str, str | None] | str:
    """(new rfc id, new section) or the reason to skip."""
    if v.level != "obsolete":
        return f"level {v.level}"
    if c.section:
        exact = [h for h in c.section_now if h["exact"]]
        if len(exact) != 1:
            return f"§{c.section}: " + ("no matching heading" if not c.section_now else "reworded or several homes")
        return exact[0]["rfc"], exact[0]["section"]
    if len(v.current) != 1:
        return "no single replacement" if v.current else "retired"
    return v.current[0], None


def _rewrite(line: str, col: int, new_rfc: str, new_section: str | None) -> str | None:
    """Rewrite the citation that starts at `col`; None when its form is unsafe to touch."""
    n_new = new_rfc[3:]
    before_sections = {m.start(2): m for m in scan.SECTION_OF.finditer(line)}
    for m in scan.CITATION.finditer(line):
        if m.start() != col:
            continue
        head = line[:m.start()]
        tail = line[m.end():]
        if head.endswith(("'", '"')) and tail.startswith(("'", '"')):
            return None  # a string literal in code ("rfc2109": ...), not prose
        if head.endswith("/"):
            if not RFC_HOSTS.search(head) or re.match(r"[#.][\w]", tail):
                return None  # e.g. httpwg.org/specs/rfc7231.html#status.codes: anchors differ
        text = line[m.start():m.end()]
        i1 = m.start(1) - m.start()
        text = text[:i1] + n_new + text[i1 + len(m.group(1)):]
        if m.group(2) and new_section:
            i2 = m.start(2) - m.start() + len(n_new) - len(m.group(1))
            text = text[:i2] + new_section + text[i2 + len(m.group(2)):]
        out = line[:m.start()] + text + tail
        pm = before_sections.get(m.start())
        if pm and not m.group(2) and new_section:
            out = out[:pm.start(1)] + new_section + out[pm.end(1):]
        return out
    return None


def plan(conn, root: Path, include_history: bool = False) -> tuple[list[Edit], list[tuple[scan.Citation, str]]]:
    cites = [c for c in scan.find_citations(root, include_history) if c.actionable]
    rules = scan.load_ignore(root)
    cites = [c for c in cites if not scan.accepted(c, rules)]
    edits, skipped = [], []
    base = root if root.is_dir() else root.parent
    lines_of: dict[str, list[str]] = {}
    # right to left within a line, so a rewrite never shifts the offset of the next one
    pairs = sorted(((c, f.verdict) for f in scan.judge(conn, cites) for c in f.citations),
                   key=lambda p: (p[0].path, p[0].line, -p[0].col))
    for c, v in pairs:
        t = _target(c, v)
        if isinstance(t, str):
            if v.obsolete:
                skipped.append((c, t))
            continue
        path = c.path if root.is_dir() else root.name
        lines = lines_of.setdefault(path, (base / path).read_text(errors="replace").splitlines(keepends=True))
        old = lines[c.line - 1]
        new = _rewrite(old, c.col, t[0], t[1])
        if new is None or new == old:
            skipped.append((c, "citation form not safe to rewrite"))
            continue
        lines[c.line - 1] = new  # later edits on the same line build on this one; the last holds them all
        edits.append(Edit(path, c.line, old, new, f"{c.rfc}{'§' + c.section if c.section else ''} → "
                                                   f"{t[0]}{'§' + t[1] if t[1] else ''}"))
    return edits, skipped


def diff(root: Path, edits: list[Edit]) -> str:
    base = root if root.is_dir() else root.parent
    out = []
    for path in dict.fromkeys(e.path for e in edits):
        old = (base / path).read_text(errors="replace").splitlines(keepends=True)
        new = list(old)
        for e in edits:
            if e.path == path:
                new[e.line - 1] = e.new
        out += difflib.unified_diff(old, new, f"a/{path}", f"b/{path}")
    return "".join(out)


def apply(root: Path, edits: list[Edit]) -> None:
    base = root if root.is_dir() else root.parent
    for path in dict.fromkeys(e.path for e in edits):
        p = base / path
        lines = p.read_text(errors="replace").splitlines(keepends=True)
        for e in edits:
            if e.path == path:
                lines[e.line - 1] = e.new
        p.write_text("".join(lines))
