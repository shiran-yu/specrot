"""Find RFC citations in a source tree and judge each one against the graph."""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import graph

# "RFC 2616", "rfc2616", "RFC-7231", "RFC#6749", ".../html/rfc2616", "time.RFC1123Z"; optional section:
# "RFC 2616, section 4.4", "RFC7540#4.1", "rfc7230#section-5.3.3", "#appendix-A", "par. 2.7", "RFC 7231 6.3.6".
CITATION = re.compile(
    r"(?i)(?<![a-z0-9])rfc[ \t_#-]{0,2}(\d{1,5})(?!\d)"
    r"(?:(?:\.html|\.txt)?(?:[ \t]*,?[ \t]*(?:section|sec\.?|§|par\.)[ \t]*|[ \t]*#[ \t]*(?:section-|appendix-|sec)?"
    r"|[ \t]+(?=\d+\.\d))((?-i:[A-Z])(?:\.\d+)*(?![\w-])|\d+(?:\.\d+)*))?"
)
# Sphinx/reST role: :rfc:`2822`, :rfc:`7232#section-4.1`, :rfc:`RFC 7232 <7232#section-4.1>`
ROLE = re.compile(r":rfc:`(?:[^`<]*<)?0*(\d{1,5})(?:#(?:section|appendix)-([A-Z]?[\d.]*\d|[A-Z]))?>?`")
# "Section 4.2.8.1 of RFC 8446", "section 6 of RFC 7159"
SECTION_OF = re.compile(r"(?i)(?:section|§)[ \t]*(\d+(?:\.\d+)*),?[ \t]+of[ \t]+\[?(rfc)[ \t_-]{0,2}\d")
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv", "venv", "__pycache__",
             "target", ".tox", ".mypy_cache"}
# Changelogs cite the RFCs a project used to follow; that history is not rot.
HISTORY_FILES = re.compile(r"(?i)^(changelog|changes|history|news|releases?)([._-].*)?$")
# Media types and module names that contain "rfc822" but cite nothing.
NOT_A_CITATION = re.compile(r"(?i)(message|text|x-)/$")
# a module name in an import statement (import rfc822 / from email import rfc822), not "quote from RFC 7231"
IMPORT = re.compile(r"^\s*(import\s+[\w., ]+|from\s+[\w.]+\s+import\s+[\w., ()*]+)\s*(#.*)?$")  # whole line
TEST_PATH = re.compile(r"(?i:(^|/)(tests?|testdata|testing|__tests__|spec|fixtures?)(/|$)|(^|/)test_[^/]*$|_test\.[a-z]+$|\.test\.[a-z]+$)"
                       r"|(^|/)[a-z]+Tests?(/|$)|Tests?\.(kt|java|scala|cs|swift)$")
MAX_BYTES = 2_000_000
LEVELS = graph.LEVELS


@dataclass
class Citation:
    path: str
    line: int
    rfc: str
    section: str | None
    text: str
    kind: str = "prose"      # prose | link | identifier (time.RFC1123, rfc2822_date)
    in_tests: bool = False
    section_now: list = field(default_factory=list)  # where the cited section lives now (obsolete RFCs)
    col: int = -1                                    # offset of the match in the raw line (for fix)

    @property
    def actionable(self) -> bool:
        """A reader-facing citation outside tests: the ones worth updating."""
        return self.kind != "identifier" and not self.in_tests


@dataclass
class Finding:
    verdict: graph.Verdict
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.verdict.to_dict()
        d["citations"] = [c.__dict__ for c in self.citations]
        return d


def _files(root: Path, include_history: bool = False, skipped: list | None = None,
           max_bytes: int = MAX_BYTES) -> list[Path]:
    """Tracked files when root is a git checkout (respects .gitignore), else a filtered walk."""
    try:
        # tracked and untracked-but-not-ignored files, so code an agent just wrote is scanned too
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True)
        files = [root / p for p in out.stdout.decode(errors="replace").split("\0") if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = None
    if not files:  # not a checkout, or a folder the enclosing repo ignores (.venv/..., data/): walk it
        files = [p for p in root.rglob("*") if p.is_file()]
    keep = [p for p in files
            if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & SKIP_DIRS)
            and (include_history or not HISTORY_FILES.match(p.name)) and p.name != ".specrot-ignore"]
    big = [p for p in keep if p.stat().st_size > max_bytes]
    if skipped is not None:
        skipped += [str(p.relative_to(root)) for p in big]  # reported, so a scan never looks complete when it is not
    return [p for p in keep if p not in big]


def find_citations(root: Path, include_history: bool = False, skipped: list | None = None,
                   max_bytes: int = MAX_BYTES) -> list[Citation]:
    if not root.exists():
        raise graph.InputError(f"no such file or directory: {root}")
    root = root.resolve()
    targets = [root] if root.is_file() else _files(root, include_history, skipped, max_bytes)
    base = root.parent if root.is_file() else root
    out = []
    for p in targets:
        try:
            data = p.read_bytes()
        except OSError:
            if skipped is not None:
                skipped.append(str(p.relative_to(base)))  # unreadable: reported like an oversized file
            continue
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16 with a byte-order mark
            text = data.decode("utf-16", errors="replace")
        elif b"\0" in data[:4096]:  # binary
            continue
        else:
            text = data.decode("utf-8", errors="replace")
        if "rfc" not in text.lower():
            continue
        out += find_in_text(text, str(p.relative_to(base)))
    return out


def _in_line(path: str, i: int, line: str) -> list[Citation]:
    out = []
    section_before = {m.start(2): m.group(1) for m in SECTION_OF.finditer(line)}
    for m in CITATION.finditer(line):
        n = int(m.group(1))
        before, after = line[:m.start()], line[m.end(1):m.end(1) + 1]
        if n == 0 or NOT_A_CITATION.search(before):
            continue
        if before.endswith("/"):
            kind = "link"
        elif n == 850 and re.match(r"(?i)[\s-]*(date|format|style|time)", line[m.end(1):]):
            kind = "identifier"  # "RFC 850 date": the obsolete HTTP-date format RFC 9110 still makes parsers accept
        elif ((before and before[-1] in "._") or after.isalpha() or after == "_" or IMPORT.match(line)
              or "_" in line[m.start() + 3:m.start(1)] or re.match(r"\.[A-Za-z]", line[m.end(1):])):
            # also RFC_4122 / rfc_822 (names) and RFC822.TEXT (an IMAP protocol item)
            kind = "identifier"
        else:
            kind = "prose"
        section = m.group(2) or section_before.get(m.start())
        out.append(Citation(path, i, f"RFC{n}", section, line.strip()[:200], kind, bool(TEST_PATH.search(path)),
                            col=m.start()))
    for m in ROLE.finditer(line):
        inside = [c for c in out if m.start() <= c.col < m.end()]  # :rfc:`RFC 7232 <...>` already found as prose
        if inside:
            inside[0].section = inside[0].section or m.group(2)
        elif int(m.group(1)):
            out.append(Citation(path, i, f"RFC{int(m.group(1))}", m.group(2), line.strip()[:200], "prose",
                                bool(TEST_PATH.search(path)), col=m.start()))
    return out


def find_in_text(text: str, name: str = "<pasted>") -> list[Citation]:
    return [c for i, line in enumerate(text.splitlines(), 1) for c in _in_line(name, i, line)]


def judge(conn, citations: list[Citation]) -> list[Finding]:
    by_rfc: dict[str, list[Citation]] = defaultdict(list)
    for c in citations:
        by_rfc[c.rfc].append(c)
    findings = [Finding(graph.check(conn, rid), cs) for rid, cs in by_rfc.items()]
    homes: dict[tuple, list] = {}
    for f in findings:
        if f.verdict.obsolete:
            for c in f.citations:
                if c.section:
                    key = (c.rfc, c.section)
                    if key not in homes:
                        homes[key] = graph.section_now(conn, c.rfc, c.section)
                    c.section_now = homes[key]
    findings.sort(key=lambda f: (LEVELS.index(f.verdict.level), not f.verdict.deprecations, -len(f.citations), f.verdict.id))
    return findings


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                              check=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


SAVE = """
MERGE (p:Project {name: $name})
SET p.url = $url, p.commit = $commit, p.scannedAt = $at
WITH p
OPTIONAL MATCH (p)-[:HAS_FILE]->(old:File)
DETACH DELETE old
"""

SAVE_FILES = """
MATCH (p:Project {name: $name})
UNWIND $files AS f
CREATE (p)-[:HAS_FILE]->(file:File {key: $name + ':' + f.path, path: f.path, project: $name, inTests: f.inTests})
WITH file, f
UNWIND f.cites AS c
MATCH (r:RFC {id: c.rfc})
CREATE (file)-[:CITES {lines: c.lines, readerLines: c.readerLines, sections: c.sections}]->(r)
"""


def save(conn, name: str, root: Path, citations: list[Citation], url: str | None = None) -> None:
    """Write the scan into the graph: (:Project)-[:HAS_FILE]->(:File)-[:CITES]->(:RFC)."""
    files: dict[str, dict[str, dict]] = defaultdict(dict)
    for c in citations:
        e = files[c.path].setdefault(c.rfc, {"rfc": c.rfc, "lines": [], "readerLines": [], "sections": []})
        e["lines"].append(c.line)
        if c.actionable:
            e["readerLines"].append(c.line)
        if c.section and c.section not in e["sections"]:
            e["sections"].append(c.section)
    rows = [{"path": p, "inTests": bool(TEST_PATH.search(p)), "cites": list(cs.values())} for p, cs in sorted(files.items())]
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(SAVE, {"name": name, "url": url, "commit": _git_commit(root), "at": at})
    for i in range(0, len(rows), 2000):
        conn.execute(SAVE_FILES, {"name": name, "files": rows[i:i + 2000]})


IGNORE_FILE = ".specrot-ignore"


def load_ignore(root: Path) -> list[tuple[str, str | None, str]]:
    """Rules from <root>/.specrot-ignore: `RFC5849 [path-glob] [# reason]`, one per line; `*` for any RFC."""
    p = (root if root.is_dir() else root.parent) / IGNORE_FILE
    rules = []
    if p.exists():
        for n, raw in enumerate(p.read_text().splitlines(), 1):
            line, _, reason = raw.partition("#")
            parts = line.split()
            if parts and parts[0] == "*":  # every RFC under a path: data files, docs about RFCs themselves
                rules.append((None, parts[1] if len(parts) > 1 else None, reason.strip()))
            elif parts:
                try:
                    rid = graph.rfc_id(parts[0])
                except graph.InputError as e:
                    raise graph.InputError(f"{p}:{n}: {e}") from e
                rules.append((rid, parts[1] if len(parts) > 1 else None, reason.strip()))
    return rules


def accepted(c: Citation, rules) -> bool:
    from fnmatch import fnmatch
    return any(rid in (None, c.rfc) and (glob is None or fnmatch(c.path, glob)) for rid, glob, _ in rules)
