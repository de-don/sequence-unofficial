# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/),
versioning: [SemVer](https://semver.org/) (0.x: the API may change between minors).

## [0.1.0a2] - 2026-11-25

### Fixed
- `workouts list`: `skip_widgets=1` returns `{}` (not lists) for `widgets`/`measures`; now normalised to `None`.
- **Breaking:** `dashboard` `snapshot.sessions_completed` is now `int` (was `str`), `session_breakdown` is an object with per-category entries (was `str`).

### Changed
- Endpoints confirmed against a live account on 2026-11-25 are now `verified` (activities, exercises, magic number); coaching conversations and two metrics endpoints stay `experimental` because their live bodies were empty.
- Sanitized samples now cover both `activities` variants; `tools/split_samples.py` keeps query variants apart.

## [0.1.0a1] - 2026-11-25

### Added
- Login with session + CSRF persistence (0600) and automatic re-login on expiry.
- Typed, read-only access to every endpoint observed so far (see `docs/api.md`).
- Registry-driven transport: throttle, GET-only retries, honest User-Agent, secret redaction in logs.
- Write safety machinery (`allow_writes`, `dry_run`, `confirm=`); no write endpoints yet.
- CLI: `login`, `logout`, `whoami`, `workouts`, `exercises`, `planner`, `tests`, `dashboard`, `export`, `raw GET`.
- Tools: `sanitize_captures.py`, `lint_samples.py`, `gen_docs.py`.


### Fixed (from the v0.1 review)
- Secrets: any header/key that looks like a secret is redacted (so a custom CSRF header name is covered); pydantic
  errors no longer echo the payload; a bad sign-in response no longer chains the validation error.
- Files: `export` refuses a non-empty directory (`--force` overwrites its own files), never follows symlinks, and only
  restricts permissions on directories it created; the session store only replaces/deletes its own files.
- Path parameters `""`, `.`, `..` are rejected; destructive endpoints must name a path placeholder as `confirm_param`
  and are refused until backup-before-delete exists; a write is never sent without a CSRF token.
- New `OutcomeUnknown` (write timeouts, 502/504 on writes; CLI exit code 3) and `InvalidArgument`.
- The custom `http_client` parameter was removed. Cookie `secure`/`expires` are kept; rotated cookies are saved as soon as a response changes them (and on close; a save failure is only logged);
  `Retry-After` HTTP dates; sign-in redirects such as `/users/sign_in`; login 429/5xx map to `RateLimited`/`ServerError`.
- CLI closes its clients; `login` consults the keyring; `export --all/--force`; `python -m sequence_unofficial`.
- Session file: carries `"kind": "sequence-unofficial-session"`; only such files (or older version-1 files whose keys
  match exactly) are ever replaced or deleted, and a newer `version` is never downgraded.
- Redaction: the configured CSRF header name is always redacted; `session` as a plain JSON key or query parameter is no
  longer redacted (only `session_id`, `_session`, `session_token`, ...).
- Export: a file that cannot be written is recorded in `errors` instead of aborting; duplicate ids are skipped and
  ids differing only by case get distinct file names; race-safe directory creation; symlinked subdirectories are
  refused. `--all` counts only successfully empty months and the manifest has `planner_complete` and
  `planner_stop_reason`; the CLI warns when the walk was incomplete.
- `OutcomeUnknown` from a 502/504 carries the real path. `NotImplementedError` (destructive call refused) is documented
  as intentionally not a `SequenceError`.
