"""Split docs/samples/samples.json into tests/fixtures/<method>_<path>.json (one file per sample).

usage: python tools/split_samples.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fixture_name(method: str, path: str, query: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    if query:
        slug += "__" + re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")
    return f"{method.lower()}_{slug}.json"


def main() -> None:
    samples = json.loads((ROOT / "docs" / "samples" / "samples.json").read_text(encoding="utf-8"))
    out = ROOT / "tests" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    # The query is part of the file name only for variants of one endpoint (e.g. skip_widgets=1).
    counts: dict[tuple[str, str], int] = {}
    for s in samples:
        key = (s["method"], s["path"])
        counts[key] = counts.get(key, 0) + 1
    for s in samples:
        query = s.get("query", "") if counts[(s["method"], s["path"])] > 1 and s.get("query") else ""
        (out / fixture_name(s["method"], s["path"], query)).write_text(
            json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(f"{len(samples)} fixtures -> {out}")


if __name__ == "__main__":
    main()
