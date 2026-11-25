# sequence-unofficial

Unofficial Python client and command-line tool for the [Sequence](https://www.sequence-app.com) climbing-training app.

> **Unofficial. Not affiliated with, endorsed by, or supported by Sequence.**
> It talks to the same JSON backend the Sequence web dashboard uses, which is undocumented and can change
> or break at any time. Status: **v0.1, read-only, alpha.**

## What works (v0.1)

- Login with session persistence (cookie + CSRF token, stored with mode 0600, never the password) and automatic re-login
  when the session expires.
- Typed, read-only access to everything observed so far: account/preferences, workouts (with exercises and sets),
  categories, exercise library, planner months, custom tests and their progress, dashboard, a few metrics.
  See [docs/api.md](docs/api.md) for every endpoint, whether it is *verified* or *experimental*, and a sample.
- A CLI (`sequence-unofficial`, short alias `squ`) with `--json` on the data commands (not `login`, `logout`, `raw`; `raw` always prints JSON), and a best-effort JSON export (`export`).
- Write safety is in place (`allow_writes`, `dry_run`, `confirm=`), but **no write endpoints exist yet** — they have
  not been captured. The CLI is read-only.

## Install

Not on PyPI yet. From a checkout:

```bash
pip install -e .            # Python >= 3.10
pip install -e ".[keyring]" # optional: read the password from the OS keyring (on macOS the `security` tool is tried first, no extra package needed)
```

## CLI

```bash
squ login                       # prompts; or set SEQUENCE_EMAIL / SEQUENCE_PASSWORD
squ whoami
squ workouts list               # verified live on 2026-11-25
squ workouts show <id> --json
squ exercises list --custom --search hang
squ planner month 2026-11
squ tests list ; squ tests show <template-id>
squ dashboard
squ export ./backup             # everything readable, as JSON (private: personal data). Needs a new/empty dir;
                                # --force overwrites its own files, --all walks the planner back as far as it has content
                                # (manifest.json: errors, planner_complete, planner_stop_reason)
squ raw GET /api/v1/dashboard   # GET only, host is fixed
squ logout                      # removes the local session
```

Exit codes: `0` ok, `1` error, `2` authentication problem / bad usage, `3` a write may or may not have been applied
(`OutcomeUnknown`; no write exists yet). `-v` / `-vv` show warnings / debug logs. Secrets (password, cookies, CSRF
token) are redacted from this library's own log lines. If *your* application turns on DEBUG for the root logger,
`httpx`/`httpcore` log their own lines (including response headers such as `Set-Cookie`) and this library cannot
redact those: keep the `httpx` and `httpcore` loggers at WARNING or above.

## Library

```python
from sequence_unofficial import Sequence

with Sequence() as sq:                       # credentials: args -> env -> keyring -> provider
    print(sq.account.status().subscribed)
    workout = sq.activities.get("<workout-id>")
    print(workout.duration_timedelta, workout.raw["duration"])   # .raw = original payload
    for day in sq.schedules.month(2026, 11):
        print(day.date, len(day.content or []))
```

Models are tolerant: unknown fields are kept (`model_extra`), enum-like values are plain strings, numbers sent as
strings become `Decimal`, and every field except `id` is optional. Personal fields (e-mail, name) are hidden from `repr`.

### Safety model for writes (future)

`Sequence(allow_writes=False)` is the default: any non-GET endpoint raises `WritesDisabled` before anything is sent.
`client.request(endpoint, ..., dry_run=True)` returns the prepared request (secrets redacted) without sending it.
Destructive endpoints additionally need `confirm=<the object id>`, and are **refused outright for now**
(`NotImplementedError`, which is deliberately *not* a `SequenceError`) until backup-before-delete exists. Writes are never retried automatically; if a write times out
or the gateway answers 502/504 you get `OutcomeUnknown` (it may have been applied: check before trying again).
`Sequence` always builds its own HTTP client: no custom `httpx.Client` can be injected, so nothing can swap out the
base URL or the no-redirect rule. (`user_agent=` and `timeout=` are ordinary constructor parameters; the default
User-Agent identifies this tool as unofficial.)

### Session, retries, throttling

- Session file: `$SEQUENCE_SESSION_FILE` or the platform state dir (`…/sequence-unofficial/session.json`, mode 0600). The file carries a `kind` marker; the
  tool never overwrites or deletes a file that does not, whatever `SEQUENCE_SESSION_FILE` points at.
- Expiry (401, redirect to `/sign-in`, or an HTML answer) → log in once and replay. A write is replayed only if the
  server provably refused it before handling it (401 / redirect), never after an ambiguous answer.
- Only GETs are retried (429, 502/503/504, connection errors; at most 3, exponential backoff with jitter, `Retry-After`
  honoured). At most 2 requests/second by default. The User-Agent says what this is.
- **Unverified:** the header carrying the CSRF token on writes. The default `X-CSRF-Token` is a guess based on the
  backend looking like Rails; it is configurable (`Sequence(csrf_header=...)`) and must be confirmed by the first write capture.
- One client per thread is simplest; re-login is serialised by a lock if you share one.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest                    # offline: respx + sanitized fixtures; nothing talks to the real service
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pyright                   # strict
python tools/lint_samples.py        # leak check for samples/fixtures
python tools/gen_docs.py --check    # docs/api.md is generated; omit --check to regenerate
```

See [tools/README.md](tools/README.md) for the capture → sanitize → fixtures → docs workflow and
[docs/decisions.md](docs/decisions.md) for the design decisions.

## Legal, ethics and privacy

- **Unofficial.** Not affiliated with or endorsed by Sequence. "Sequence" is their name; no logos or branding are used here.
- This library uses **your own account** through the same endpoints the web app uses. It is not a public, supported API:
  it may break at any time, and Sequence may change or restrict access.
- **No warranty** (see the MIT [LICENSE](LICENSE)). Writes — once they exist — can damage your training plan:
  keep `allow_writes` off unless you need it, preview with `dry_run`, and keep your own backups (`squ export` is best effort, not a guaranteed full backup).
- **Use it gently.** The client throttles itself; please do not remove that or run it in tight loops or in bulk.
- **Read Sequence's Terms of Service yourself** and decide whether this use is acceptable for you.
- If you only need read access to your data, **prefer the official read-only MCP server** that Sequence provides.
- Your credentials and session stay on your machine; the password is never written to disk by this tool.

What this repository deliberately does **not** contain: HAR files, cookies, tokens, real ids/names/e-mails, the
dashboard's JavaScript bundle, logos, the built-in exercise library text or thumbnails, or paid plan/template content.
The samples in `docs/samples/` are sanitized (structure and types only) and checked by `tools/lint_samples.py`.

## Roadmap

Writes will be added one at a time as they are captured, lowest risk first: add a test result, create a note, schedule a
single workout, create/edit a workout, move a scheduled item, create a test template, single deletes, bulk schedule and
clear. Each needs a capture, a fixture and a round-trip check on a throwaway object.

## License

MIT
