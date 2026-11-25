"""Turn the raw capture (contains personal data) into sanitized API samples that are safe to publish.

usage: python sanitize_captures.py capture.jsonl out_dir
Every fake UUID minted is merged into tools/fake_uuids.txt, which tools/lint_samples.py uses as its allowlist.
Rules: UUIDs -> stable fake UUIDs, e-mails -> user@example.com, free text -> 'text', lists cut to 2 items,
secrets dropped. Only structure, types, enum-like values, numbers and dates survive.
"""
import json, re, sys, uuid, hashlib, os
from urllib.parse import parse_qsl, urlencode

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
EMAIL = re.compile(r"[^@\s\"']+@[^@\s\"']+\.[a-z]{2,}", re.I)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
ENUM = re.compile(r"^[a-z0-9_\-:.]{1,40}$")
SECRET = re.compile(r"(^pass(word)?$|token|secret|authorization|cookie|jwt|csrf|api[_-]?key)", re.I)
_fake = {}


def fake_uuid(u):
    u = u.lower()
    if u not in _fake:
        _fake[u] = str(uuid.UUID(hashlib.sha256(("seq-sample-" + u).encode()).hexdigest()[:32]))
    return _fake[u]


def clean_str(s, key=""):
    s2 = UUID.sub(lambda m: fake_uuid(m.group(0)), s)
    if EMAIL.search(s2):
        return "user@example.com"
    if ISO.match(s2) or UUID.fullmatch(s2) or ENUM.match(s2):
        return s2
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27}", s2):
        return s2
    return "text"


def clean(o, key=""):
    if isinstance(o, dict):
        return {k: ("[REDACTED]" if SECRET.search(k) and isinstance(v, str) else clean(v, k)) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v, key) for v in o[:2]]
    if isinstance(o, str):
        return clean_str(o, key)
    return o


def clean_query(url):
    """Query strings can carry ids too (e.g. activity_id=...): same rules as bodies."""
    if "?" not in url:
        return ""
    pairs = parse_qsl(url.split("?", 1)[1], keep_blank_values=True)
    return urlencode([(k, "[REDACTED]" if SECRET.search(k) else clean_str(v, k)) for k, v in pairs])[:200]


def tmpl(url):
    path = re.sub(r"^https?://[^/]+", "", url).split("?")[0]
    return UUID.sub("{id}", path)


def main(src, out, allow=None):
    os.makedirs(out, exist_ok=True)
    seen = {}
    for line in open(src):
        r = json.loads(line)
        if "dashboard.sequence-app.com" not in r["url"] or r.get("status", 0) == 0:
            continue
        key = (r["method"], tmpl(r["url"]))
        if key in seen:
            continue
        def parse(s):
            try:
                return json.loads(s) if s else None
            except Exception:
                return None
        seen[key] = {
            "method": r["method"], "path": key[1], "status": r["status"],
            "query": clean_query(r["url"]),
            "request": clean(parse(r.get("reqBody"))) if r.get("reqBody") else None,
            "response": clean(parse(r.get("resBody"))) if r.get("resBody") else None,
            "note": r.get("note", ""),
        }
    with open(os.path.join(out, "samples.json"), "w") as f:
        json.dump(sorted(seen.values(), key=lambda x: (x["path"], x["method"])), f, ensure_ascii=False, indent=1)
    allow = allow or os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_uuids.txt")
    known = set(open(allow).read().split()) if os.path.exists(allow) else set()
    with open(allow, "w") as f:
        f.write("\n".join(sorted(known | set(_fake.values()))) + "\n")
    print(len(seen), "sanitized samples ->", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
