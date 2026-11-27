"""Find RFC citations in a source tree and judge each one against the graph."""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import graph

# "RFC 2616", "rfc2616", "RFC-7231", "RFC#6749", ".../html/rfc2616", "time.RFC1123Z"; optional section.
CITATION = re.compile(
    r"(?i)(?<![a-z0-9])rfc[ \t_#-]{0,2}(\d{1,5})(?!\d)"
    r"(?:[ \t]*,?[ \t]*(?:section|sec\.?|§)[ \t]*(\d+(?:\.\d+)*))?"
)
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv", "venv", "__pycache__",
             "target", ".tox", ".mypy_cache"}
# Changelogs cite the RFCs a project used to follow; that history is not rot.
HISTORY_FILES = re.compile(r"(?i)^(changelog|changes|history|news|releases?)([._-].*)?$")
# Media types and module names that contain "rfc822" but cite nothing.
NOT_A_CITATION = re.compile(r"(?i)(message|text|x-)/$")
IMPORT = re.compile(r"(import|from)\s+$")
TEST_PATH = re.compile(r"(?i)(^|/)(tests?|testdata|testing|__tests__|spec|fixtures?)(/|$)|(^|/)test_[^/]*$|_test\.[a-z]+$|\.test\.[a-z]+$")
MAX_BYTES = 2_000_000
LEVELS = ["obsolete", "historic", "amended", "ok", "unknown"]


@dataclass
class Citation:
    path: str
    line: int
    rfc: str
    section: str | None
    text: str
    kind: str = "prose"      # prose | link | identifier (time.RFC1123, rfc2822_date)
    in_tests: bool = False

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


def _files(root: Path, include_history: bool = False) -> list[Path]:
    """Tracked files when root is a git checkout (respects .gitignore), else a filtered walk."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
        files = [root / p for p in out.stdout.decode(errors="replace").split("\0") if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = [p for p in root.rglob("*") if p.is_file()]
    return [p for p in files
            if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & SKIP_DIRS)
            and (include_history or not HISTORY_FILES.match(p.name))
            and p.stat().st_size <= MAX_BYTES]


def find_citations(root: Path, include_history: bool = False) -> list[Citation]:
    root = root.resolve()
    targets = [root] if root.is_file() else _files(root, include_history)
    base = root.parent if root.is_file() else root
    out = []
    for p in targets:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:  # binary
            continue
        text = data.decode("utf-8", errors="replace")
        if "rfc" not in text.lower():
            continue
        out += find_in_text(text, str(p.relative_to(base)))
    return out


def _in_line(path: str, i: int, line: str) -> list[Citation]:
    out = []
    for m in CITATION.finditer(line):
        n = int(m.group(1))
        before, after = line[:m.start()], line[m.end(1):m.end(1) + 1]
        if n == 0 or NOT_A_CITATION.search(before):
            continue
        if before.endswith("/"):
            kind = "link"
        elif (before and before[-1] in "._") or after.isalpha() or after == "_" or IMPORT.search(before):
            kind = "identifier"
        else:
            kind = "prose"
        out.append(Citation(path, i, f"RFC{n}", m.group(2), line.strip()[:200], kind, bool(TEST_PATH.search(path))))
    return out


def find_in_text(text: str, name: str = "<pasted>") -> list[Citation]:
    return [c for i, line in enumerate(text.splitlines(), 1) for c in _in_line(name, i, line)]


def judge(conn, citations: list[Citation]) -> list[Finding]:
    by_rfc: dict[str, list[Citation]] = defaultdict(list)
    for c in citations:
        by_rfc[c.rfc].append(c)
    findings = [Finding(graph.check(conn, rid), cs) for rid, cs in by_rfc.items()]
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
CREATE (file)-[:CITES {lines: c.lines, sections: c.sections, actionable: c.actionable}]->(r)
"""


def save(conn, name: str, root: Path, citations: list[Citation], url: str | None = None) -> None:
    """Write the scan into the graph: (:Project)-[:HAS_FILE]->(:File)-[:CITES]->(:RFC)."""
    files: dict[str, dict[str, dict]] = defaultdict(dict)
    for c in citations:
        e = files[c.path].setdefault(c.rfc, {"rfc": c.rfc, "lines": [], "sections": [], "actionable": 0})
        e["lines"].append(c.line)
        e["actionable"] += int(c.actionable)
        if c.section and c.section not in e["sections"]:
            e["sections"].append(c.section)
    rows = [{"path": p, "inTests": bool(TEST_PATH.search(p)), "cites": list(cs.values())} for p, cs in sorted(files.items())]
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(SAVE, {"name": name, "url": url, "commit": _git_commit(root), "at": at})
    for i in range(0, len(rows), 2000):
        conn.execute(SAVE_FILES, {"name": name, "files": rows[i:i + 2000]})
