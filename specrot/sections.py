"""Section headings of RFCs and how sections carry over from an obsoleted RFC to its replacements.

A section of the old RFC continues as the section of a replacement with the same heading (after
normalising case, punctuation and filler words); among several candidates the one under the section
its parent continues as wins (so "Introduction" of 7231 section 6 lands under 9110 section 15).
Fuzzy matches (word overlap >= 0.6) count only when there is no exact one, and are marked.
"""
from __future__ import annotations

import re
import time
import urllib.request
from pathlib import Path

HEADING = re.compile(r"^((?:\d+|[A-Z])(?:\.\d+)*)\.?\s{1,6}(\S.{1,90}?)\s*$")
APPENDIX = re.compile(r"^Appendix\s+([A-Z](?:\.\d+)*)\.?\s+(\S.{1,90}?)\s*$")
PAGE_LINE = re.compile(r"^(RFC \d+|.*\[Page \d+\])")
FILLER = {"the", "a", "an", "of", "and", "for", "to", "in", "on"}


def fetch(numbers, txt_dir: Path) -> None:
    """Download rfcNNNN.txt from the RFC Editor (cached; one request per second)."""
    txt_dir.mkdir(parents=True, exist_ok=True)
    for n in sorted(numbers):
        p = txt_dir / f"rfc{n}.txt"
        if p.exists():
            continue
        try:
            with urllib.request.urlopen(f"https://www.rfc-editor.org/rfc/rfc{n}.txt", timeout=60) as r:
                p.write_bytes(r.read())
        except OSError:
            p.write_text("")  # missing or unreachable: no sections
        time.sleep(1)


def parse(text: str) -> list[tuple[str, str]]:
    """[(number, title)] in document order: headings start in column 0; the indented TOC is skipped."""
    out, seen = [], set()
    for line in text.splitlines():
        if not line or line[0] == " " or PAGE_LINE.match(line) or "...." in line:
            continue
        m = HEADING.match(line) or APPENDIX.match(line)
        if not m:
            continue
        num, title = m.group(1), m.group(2).strip()
        if num in seen or not re.search(r"[A-Za-z]", title) or title.endswith((",", ";")):
            continue
        if num.isalpha() and not APPENDIX.match(line) and not re.match(r"^[A-Z]\.\s", line):
            continue  # a lone capital starting a sentence, not an appendix
        seen.add(num)
        out.append((num, title))
    return out


def norm(title: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", title.lower().replace("-", " "))
    return tuple(w for w in words if w not in FILLER)


def _parent(num: str) -> str | None:
    return num.rsplit(".", 1)[0] if "." in num else None


def match(old: list[tuple[str, str]], new: dict[str, list[tuple[str, str]]]) -> dict[str, dict]:
    """old section number -> {rfc, section, title, exact} for each old section that carries over."""
    cands: dict[tuple, list[tuple[str, str, str]]] = {}
    pool = []
    for rfc, secs in new.items():
        for num, title in secs:
            cands.setdefault(norm(title), []).append((rfc, num, title))
            pool.append((rfc, num, title, set(norm(title))))
    out: dict[str, dict] = {}
    for num, title in old:
        key = norm(title)
        if not key:
            continue
        hits, exact = cands.get(key, []), True
        if not hits:
            words = set(key)
            scored = [(len(words & w) / len(words | w), (r, n, t)) for r, n, t, w in pool if w]
            best = max((s for s, _ in scored), default=0)
            hits = [h for s, h in scored if s == best and best >= 0.6]
            exact = False
        p = out.get(_parent(num) or "")
        if len(hits) > 1 and p:
            under = [h for h in hits if h[0] == p["rfc"] and (h[1] + ".").startswith(p["section"] + ".")]
            hits = under or [h for h in hits if h[0] == p["rfc"]] or hits
        if len(hits) == 1:
            rfc, n, t = hits[0]
            out[num] = {"rfc": rfc, "section": n, "title": t, "exact": exact}
    return out
