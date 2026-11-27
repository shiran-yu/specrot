"""The README's headline numbers must match facts.json (regenerate with scripts/facts.py)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_readme_matches_facts():
    f = json.loads((ROOT / "facts.json").read_text())
    readme = (ROOT / "README.md").read_text()
    s = f["showcase"]
    for needle in [f"**{s['citations']:,}**", f"**{s['obsolete']:,} ({s['obsolete_pct']}%)**",
                   f"**{s['affected']} of {s['projects']}**", f"{s['old_version']:,} more",
                   f"{f['nodes']['RFC']:,} `RFC`s", f"{f['nodes']['Erratum']:,} `Erratum`",
                   f"{f['relationships']['NORMATIVE_REF']:,} `NORMATIVE_REF`",
                   f"{f['relationships']['INFORMATIVE_REF']:,} `INFORMATIVE_REF`",
                   f"{f['nodes']['File']:,} `File`s"]:
        assert needle in readme, needle
    t = f["top_obsolete"]
    assert f"RFC 2616 ({t[0]['projects']} projects)" in readme and t[0]["rfc"] == "RFC2616"
