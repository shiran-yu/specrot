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

HISTORY = re.compile(r"(?i)\b(obsolet\w*|supersed\w*|replac\w*|deprecat\w*|formerly|previously|historic\w*|legacy|"
                     r"older|earlier|original\w*|was updated|updated by|backward\w*|compatib\w*|released|introduced|"
                     r"(?:in|since|from) (?:19|20)\d\d)\b")
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
        if head.count('"') % 2 or head.count("`") % 2:
            return None  # inside a quoted example or quotation
        if HISTORY.search(line) or re.search(rf"(?i)rfc[ \t_#-]{{0,2}}0*{n_new}(?!\d)", line):
            return None  # the line already talks about the replacement or the history: rewording needs a person
        if not head.endswith("/") and re.fullmatch(r"rfc\d+", line[m.start():m.end(1)]):
            return None  # lower-case and unspaced outside a link: a code name (enum rfc822, fmt == rfc850)
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


def _read(p: Path) -> list[str] | None:
    """Lines with their own line endings; None for a file that is not UTF-8 (left untouched)."""
    try:
        return p.read_bytes().decode("utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None


def plan(conn, root: Path, include_history: bool = False) -> tuple[list[Edit], list[tuple[scan.Citation, str]]]:
    cites = [c for c in scan.find_citations(root, include_history) if c.actionable]
    rules = scan.load_ignore(root)
    cites = [c for c in cites if not scan.accepted(c, rules)]
    edits, skipped = [], []
    base = root if root.is_dir() else root.parent
    lines_of: dict[str, list[str] | None] = {}
    by_line: dict[tuple, list] = {}
    for f in scan.judge(conn, cites):
        for c in f.citations:
            if f.verdict.obsolete:
                by_line.setdefault((c.path, c.line), []).append((c, f.verdict))
    for (path_, line_no), pairs in sorted(by_line.items()):
        # all or nothing per line, right to left so a rewrite never shifts the next offset
        pairs.sort(key=lambda p: -p[0].col)
        path = path_ if root.is_dir() else root.name
        lines = lines_of.setdefault(path, _read(base / path))
        old = new = lines[line_no - 1] if lines and line_no <= len(lines) else None
        why, notes = None, []
        for c, v in pairs:
            t = _target(c, v)
            if isinstance(t, str):
                why = why or t
                continue
            r = _rewrite(new, c.col, t[0], t[1]) if new is not None else None
            if r is None:
                why = why or ("file is not UTF-8" if lines is None else "citation form not safe to rewrite")
                continue
            new = r
            notes.append(f"{c.rfc}{'§' + c.section if c.section else ''} → {t[0]}{'§' + t[1] if t[1] else ''}")
        if why or new == old:
            skipped += [(c, why or "unchanged") for c, _ in pairs]
            continue
        lines[line_no - 1] = new
        edits.append(Edit(path, line_no, old, new, "; ".join(notes)))
    return edits, skipped


def _changed(root: Path, edits: list[Edit]):
    base = root if root.is_dir() else root.parent
    for path in dict.fromkeys(e.path for e in edits):
        old = _read(base / path)
        new = list(old)
        for e in edits:
            if e.path == path:
                new[e.line - 1] = e.new
        yield base / path, path, old, new


def diff(root: Path, edits: list[Edit]) -> str:
    return "".join(x for _, path, old, new in _changed(root, edits)
                   for x in difflib.unified_diff(old, new, f"a/{path}", f"b/{path}"))


def apply(root: Path, edits: list[Edit]) -> None:
    """Write exactly the reviewed lines; every other byte of the file is kept."""
    for p, _, _, new in list(_changed(root, edits)):
        p.write_bytes("".join(new).encode("utf-8"))
