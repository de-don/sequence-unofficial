# Decisions log

The base design is `docs/opus_design_answer.md` (binding). This file records what was decided while implementing v0.1:
every consultation with Opus (questions and full answers were kept in the gitignored `.opus/`), and the smaller
choices that interpret or extend the design.

## Consultations with Opus

### 1. Public API shape and endpoints with unknown bodies

- **Question:** flat methods vs resource attributes; how to type `GET /activities` and `GET /exercise_library_items`
  (HTTP 200 seen, body truncated in the capture); whether the metrics endpoints get models.
- **Answer (summary):** resource attributes (`client.activities.get()`), no flat aliases. Unknown list bodies return
  `list[Activity]` / `list[ExerciseLibraryItem]` through one `_parse_list` helper: bare list, or a dict wrapping exactly
  one list under a small key allowlist (warning logged), else `UnexpectedResponse`; no invented query parameters
  (`--search`/`--custom` are client-side); `status="experimental"` plus a free-text `note` on `Endpoint`, no third status.
  Add a model only when a capture shows real fields; otherwise return plain JSON and mark the endpoint experimental.
- **Done:** `Endpoint.note`, `Endpoint.resource` (also an accepted wrapper key), `Sequence._parse_list`; the two list
  endpoints and `activity_all_time`/`activity_list`/`coaching_conversations` are experimental, the last three return raw
  JSON; `activity_magic_number` has a small `WeeklyMetric` model and is experimental (2-item sample).
  `tests/test_lists.py` exercises the rules with synthetic bodies (documented as such).

### 2. Session expiry, re-login, CSRF edge cases

- **Question:** what exactly counts as an expired session, whether to replay writes after re-login, eager vs lazy
  validation of a stored session, behaviour without credentials.
- **Answer (summary):** expired = 401, or 3xx to `/sign-in`, or 200 HTML ("ambiguous"); never for `/signin` itself,
  403, 422, 404, 5xx or other redirects; at most one re-login per call. A write is replayed once (with the new CSRF
  token) only if the signal was "rejected" (401/redirect: the server refused before handling it); an "ambiguous" answer
  to a write raises `SessionExpired` without replay; `replay_writes_after_reauth` switch. Stored session is checked
  lazily; it stores the lowercased e-mail and is ignored if another e-mail is configured; written atomically. The
  library never prompts: a `credential_provider` callable (the CLI adds a TTY prompt); with no credentials the dead
  session file is removed and `AuthenticationRequired` is raised. Re-login under a lock with a generation counter.
- **Done:** `client._expired`, `Sequence._send`, `auth.Auth` (lock + generation), `SessionStore` (atomic, 0600/0700),
  `replay_writes_after_reauth`. Names: I kept the design's `AuthError` base and added `InvalidCredentials`,
  `AuthenticationRequired`, `SessionExpired` as subclasses; I did *not* add Opus' `CsrfError`/`UnexpectedRedirect`
  (nothing can produce a CSRF error until a write is captured; redirects raise `UnexpectedResponse`).
  Tests: `tests/test_auth.py` (replay of GET and of writes with a test-only endpoint, no-credentials, e-mail mismatch).

### 3. Recognising "fake" UUIDs in the lint, and a leaked id

- **Question:** how should `lint_samples.py` define the fake-UUID allowlist? One UUID in the committed samples looked
  like a real v4 id (only inside `query` strings, which the sanitizer never cleaned): what to do?
- **Answer (summary):** use a committed allowlist `tools/fake_uuids.txt` written by the sanitizer (exact set
  difference; the alternatives either misclassify ~1/64 of fakes or force re-churning all samples). Fix the sanitizer
  to clean query strings and regenerate rather than hand-edit; scan raw text *and* a URL-decoded copy; cheap extra checks
  (non-example e-mails, JWT, long hex/base64, cookie headers, secret-looking keys); exceptions only through a committed
  file, never inline. Tell the user about git history.
- **Done:** sanitizer now cleans query strings and merges fakes into `fake_uuids.txt`; `lint_samples.py` as described.
  I did not have the raw capture, so I applied the sanitizer's own deterministic mapping to the three `query` fields of
  `docs/samples/samples.json` (it mapped to the same fake as the workout-detail sample, so references are consistent).
  **Not done on purpose:** I did not rewrite git history. The original id is still in the first commit (`fc37cb9`) and
  in the diff of my fix commit (`d1019da`); both are local and were never pushed. Before publishing, publish a squashed
  history (e.g. a fresh `git init` + one commit from the current tree, or `git rebase -i --root` squashing everything),
  then check with `git log --all -p -S<the id>` and, if you rewrote this repo in place,
  `git reflog expire --expire=now --all && git gc --prune=now`. The id also appears in this session's gitignored
  `.opus/` files (it was quoted in the question to Opus), which are not part of the repo.

### 4. Review of v0.1: OutcomeUnknown, custom `http_client`, destructive endpoints without a backup

Opus reviewed v0.1 (`.opus/review1.md`); I fixed all blockers/majors and the cheap minors. Three points were real design
choices, so I asked (`.opus/q4.md` / `a4.md`):

- **OutcomeUnknown.** Answer: subclass `SequenceError` only (a subclass of `ServerError` would be caught by
  `except ServerError: retry`); GET keeps `ServerError` (+ retries); `ConnectError`/`ConnectTimeout`/`PoolTimeout` on a
  write stay `ServerError` because the request provably never left, everything else on a non-GET (`ReadTimeout`,
  `WriteTimeout`, protocol errors) and a 502/504 *response* to a write is `OutcomeUnknown` (carries method and path);
  CLI gets its own exit code with "check the state before retrying". **Done** exactly so (exit code 3). A login that times
  out is reported as `ServerError`, since logging in again is harmless.
- **Custom `http_client`.** Answer: remove it from `Sequence` and `Transport`; if an injection point is ever needed take
  an `httpx.BaseTransport` and wrap it in our own client. **Done:** removed (respx patches httpx globally, so tests are unaffected).
- **Destructive endpoints before the backup exists.** Answer: fail closed (`NotImplementedError`), not a `skip_backup=`
  parameter (it would become the habit). The test bypass is a private module flag `client._ALLOW_UNBACKED_DESTRUCTIVE`,
  flipped only by the `allow_unbacked_destructive` fixture via `monkeypatch`: not a kwarg, not an `Endpoint` field, not in
  `__all__`. `Endpoint.__post_init__` rejects destructive GETs and a `confirm_param` that is not a parsed path placeholder.
  **Done**, with a test that the guard raises when the fixture is not used.

## Smaller decisions (no consultation needed)

- **Dry run works even with writes disabled.** It sends nothing and is the way to preview; the guard only applies to
  sending. Destructive endpoints skip the `confirm` check in dry-run.
- **`confirm=` semantics:** must equal the value of the endpoint's `confirm_param` path parameter. Backup-before-delete from
  the design is **not implemented**: there are no destructive endpoints yet, so there is nothing to back up.
- **`ConfirmationRequired`** exception added (not in the design's list) so a missing confirm is distinguishable.
- **`POST /signin` is in the registry** with `auth=True`, so it is not counted as a write and needs no `allow_writes`.
- **`password_set_from_plan_purchase`** is typed `bool | str | None`: the sample has a string (probably a sanitizer
  artefact; real type unknown). `time_zone`, `date_value` etc. follow the samples.
- **Sanitized "text" in date-like fields** (`week_start_date`, `latest_date`, …) means those are typed `str`, not `date`;
  only fields whose samples hold real ISO dates (`ScheduleDay.date`, `scheduled_at`) are `date`.
- **No `planner range`:** the grid length (5 or 6 weeks) is unknown, so a range helper would be invented behaviour.
  `schedules.month(y, m)` starts the grid on the Monday on or before the 1st (inferred from one sample: 2026-09 → 2026-08-31).
- **User-Agent** is `sequence-unofficial/<version> (unofficial client)`; the design suggests adding the repo URL, which
  does not exist yet. Add it when the repository is public (`Sequence(user_agent=...)` already allows it).
- **CLI is read-only** (it never sets `allow_writes`). `raw` accepts only GET and only paths starting with a single `/`.
- **CLI log level:** warnings (e.g. "endpoint is experimental") are hidden by default and shown with `-v`.
- **`SEQUENCE_SESSION_FILE`** overrides the session path (used by tests so they never touch the real state dir).
- **Export** creates the directory 0700 and files 0600 (they contain personal data), records failing endpoints in
  `manifest.json` instead of aborting, but stops on authentication errors.
- **Tooling:** `ruff format` also reformats Python code blocks in Markdown, so `docs/` is excluded in the ruff config
  (the design docs must not be edited). `tools/sanitize_captures.py` is excluded from ruff/pyright: it is a standalone
  script supplied with the brief.
- **`keyring`** is an optional extra, looked up with `importlib` so it is never a hard dependency.

## Write roadmap

Unchanged from the design: add a test result → create a note → schedule a single workout → create/edit a workout →
move/update a scheduled item → create a test template → single deletes → bulk schedule and clear. Each step needs a
capture, a sanitized fixture, a registry line + wrapper, and a live round trip on a throwaway object.

### Review fixes: what I did differently or deliberately left out

- **`export --all`** has no date to start from (activities carry no date), so it walks the planner back from this month
  until it has been empty (no day with a workout, note or test) for 6 months in a row, capped at 240 months. The export is
  documented as best effort, not a full backup; the manifest lists the planner months it covered.
- **Corrupt/foreign session file:** `SessionStore.save` logs a warning and does **not** persist (login still works in
  memory) rather than overwrite a file it cannot recognise; the user must remove it by hand.
- **httpx/httpcore logging (review major 7):** I narrowed the README claim instead of installing a filter on libraries'
  loggers; the library cannot own what other loggers print.
- **`[project.urls]` and the repo URL in the User-Agent** are not added: there is no public repository URL yet and I will
  not invent one. Add both when the repository exists.
- **Not done on purpose:** `skip_widgets=1` vs `true` and the Monday week start need the capture / a live check (already
  marked unverified in the registry notes); the live smoke test and the fresh-history step of the publishing checklist
  are for the owner.

### Re-review fixes (second round; no new Opus consultation, the choices were dictated by the review)

- **Session file ownership** is an exact marker: `"kind": "sequence-unofficial-session"` plus an integer `version`.
  Older version-1 files without `kind` are still read and replaced, but only if their key set is exactly
  `{version, email, csrf, cookies, saved_at}`. A higher version is never overwritten (no downgrade); `logout` may still
  delete it because it is provably ours.
- **Cookie persistence:** rotated cookies are saved after every response that changed them, not only in `close()`.
  `save_if_changed` logs and swallows `OSError` (it is best effort), so a read-only state directory can neither break a
  read nor replace `OutcomeUnknown` raised inside a `with` block. After a failed save the in-memory snapshot is still
  updated, so it warns once instead of on every request.
- **Redaction:** the configured CSRF header name is passed to the transport and always redacted. In JSON keys and query
  strings `session` alone is no longer secret (a "session" is a workout); `session_id`, `_session`, `session_token`,
  `session_key` are. Header names keep the broad `session` match because headers carry no training data.
- **Export:** every step (fetch *and* write) records `OSError` in `errors`; duplicate ids are fetched once; file names
  are made unique case-insensitively (hash suffix); `out` is created without a check-then-create race; symlinked
  subdirectories are refused. `--all` counts only successfully empty months, stops after 3 failed months in a row, and the
  manifest records `planner_complete` (true only when six empty months ended the walk with no failed month) and
  `planner_stop_reason` (`window`, `empty_months`, `max_months`, `errors`). The CLI maps stray `OSError` to exit code 1.
- **`NotImplementedError`** for refused destructive calls stays outside `SequenceError`; documented in the `request`
  docstring and README, and pinned by a test.
- **Left alone:** the pydantic `JSONDecodeError` stays in `__context__` of some errors (review: low risk).
