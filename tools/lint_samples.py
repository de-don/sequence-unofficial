"""Reject sample/fixture files that look like they contain real data.

usage: python tools/lint_samples.py [PATH ...]      (default: docs/samples tests/fixtures)

Checks (on the raw text and on a URL-decoded copy, so query strings are covered too):
  * UUIDs that are not in tools/fake_uuids.txt (written by sanitize_captures.py)
  * e-mail addresses other than @example.(com|org|net)
  * JWT-like strings, long hex strings, long base64-ish runs
  * Cookie / Set-Cookie / Authorization headers
  * JSON keys that look secret (password, csrf, token, ...) with a real-looking string value
Exceptions go into tools/lint_allow.txt (one exact matched string per line). No inline disables.
Exit code 1 when anything is found.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
JWT = re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]*")
LONG_HEX = re.compile(r"(?<![0-9a-f-])[0-9a-f]{32,}(?![0-9a-f-])", re.I)
# needs a digit or capital so snake_case key names do not match
LONG_B64 = re.compile(r"(?=[A-Za-z0-9+/_-]*[A-Z0-9])[A-Za-z0-9+/_-]{40,}={0,2}")
AUTH_HEADER = re.compile(r"(?i)\b(set-cookie|cookie|authorization)\b")
SECRET_KEY = re.compile(r"(?i)password|passwd|csrf|xsrf|token|secret|session|api[_-]?key|(^|_)(otp|pin)($|_)")
PLACEHOLDERS = {"", "text", "[REDACTED]"}


def _secret_values(obj: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():  # pyright: ignore[reportUnknownVariableType]
            key = str(k)  # pyright: ignore[reportUnknownArgumentType]
            if SECRET_KEY.search(key) and isinstance(v, str) and v not in PLACEHOLDERS:
                found.append(f"key {path}{key!r} has a non-placeholder value")
            found += _secret_values(v, f"{path}{key}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            found += _secret_values(v, f"{path}{i}.")
    return found


def lint_text(raw: str, fake_uuids: set[str], allow: set[str]) -> list[str]:
    problems: list[str] = []
    text = raw + "\n" + unquote(raw)
    for u in sorted({m.lower() for m in UUID.findall(text)} - fake_uuids):
        if u not in allow:
            problems.append(f"UUID not in fake_uuids.txt: {u}")
    for m in EMAIL.finditer(text):
        if m.group(1).lower() not in SAFE_EMAIL_DOMAINS and m.group(0) not in allow:
            problems.append(f"e-mail address: {m.group(0)}")
    uuid_free = UUID.sub("", text)
    for rx, what in ((JWT, "JWT-like string"), (LONG_HEX, "long hex string"), (LONG_B64, "long base64 run")):
        for m in rx.finditer(uuid_free):
            if m.group(0) not in allow:
                problems.append(f"{what}: {m.group(0)[:20]}...")
    for m in AUTH_HEADER.finditer(text):
        if m.group(0) not in allow:
            problems.append(f"header name in sample: {m.group(0)}")
    with contextlib.suppress(ValueError):  # not JSON: the regex checks above still ran
        problems += _secret_values(json.loads(raw))
    return list(dict.fromkeys(problems))


def _read_lines(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or [ROOT / "docs" / "samples", ROOT / "tests" / "fixtures"]
    files: list[Path] = []
    for t in targets:
        files += sorted(t.rglob("*.json")) if t.is_dir() else [t] if t.exists() else []
    fake = {u.lower() for u in _read_lines(HERE / "fake_uuids.txt")}
    allow = _read_lines(HERE / "lint_allow.txt")
    bad = 0
    for f in files:
        for p in lint_text(f.read_text(encoding="utf-8"), fake, allow):
            print(f"{f}: {p}")
            bad += 1
    print(f"lint_samples: {len(files)} files, {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
