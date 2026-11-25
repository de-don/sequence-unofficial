# Design decisions for the unofficial Sequence client

1. **Names and license.** Use `sequence-unofficial` as the PyPI name, `sequence_unofficial` as the import name and `sequence-unofficial` as the CLI command (with `squ` as a short alias). Use the MIT license.
   - **Why:** The name says "unofficial" everywhere a user will see it, and it matches the repo name.
   - **Risk:** I haven't checked PyPI. Run `pip index versions sequence-unofficial` before publishing. If the name is taken, use `sequence-app-unofficial`.

2. **Layout, sync/async and HTTP library.** Use a `src/` layout, sync only, on `httpx`.
   - **Why sync:** The traffic is low and the main users are a CLI and scripts. The future MCP wrapper can call it through `anyio.to_thread`. `httpx` lets you add an `AsyncClient` later without changing the API shape.
   - **Modules:** `_transport.py` (HTTP, retries, throttling), `auth.py`, `session_store.py`, `errors.py`, `endpoints.py` (registry), `models/` (one file per area), `resources/` (activities, exercises, schedules, tests, account, dashboard), `client.py`, `cli/`, plus a `py.typed` marker.

3. **Models.** Use pydantic v2 with `extra="allow"`. Make every field optional except `id`.
   - **Enums:** Store values like `category`, `kind` and `effort_scale` as `str`, with the known values kept as constants. A new value from the server then won't break parsing.
   - **Numbers:** Turn numeric strings (`duration: "6300000.0"` in ms, `weight: "5.0"`) into `Decimal` with validators. Also add a `duration_timedelta` property.
   - **Raw data:** Keep the original dict on each model as `.raw` (a `PrivateAttr`). Unknown fields go to `model_extra`.
   - **Risk:** Optional fields everywhere weaken typing. Fix that with drift tests (see 7), not stricter models.

4. **Auth and session.**
   - **Credentials, in this order:** explicit arguments → `SEQUENCE_EMAIL`/`SEQUENCE_PASSWORD` → `keyring` (optional extra) → an interactive prompt (CLI only).
   - **Session storage:** Save cookies and the CSRF token as JSON at `platformdirs.user_state_dir("sequence-unofficial")/session.json`, with file mode 0600 and the folder at 0700. Never store the password there.
   - **CSRF:** Send the token on every non-GET request. The backend looks like Rails, so `X-CSRF-Token` is the likely header, but confirm it in the first write capture.
   - **Expiry:** Set `follow_redirects=False`. Treat 401, 302→`/sign-in`, or an HTML response as an expired session. Log in again once and replay the request; repeat a write only when the server never handled it.
   - **2FA:** None is supported. If `/signin` returns anything without `user` and `csrf`, raise `AuthError`.

5. **Errors and retries.**
   - **Error types:** `SequenceError` as the base, then `AuthError`, `NotFound`, `ValidationError` (422, with the body), `RateLimited`, `ServerError`, `UnexpectedResponse` (wrong shape or HTML), `WritesDisabled`.
   - **Retries:** Only GETs retry, on 429, 502/503/504 or connection errors. Use at most 3 retries with exponential backoff, jitter, and `Retry-After` honored. Writes never retry automatically.
   - **Throttling:** At most 2 requests per second (configurable), and an honest User-Agent like `sequence-unofficial/<ver> (+repo URL)`.
   - **Logging:** Remove cookies, CSRF tokens and passwords from all logs.

6. **Adding endpoints and keeping writes safe.** Use one declarative registry, plus a generic `client.request()` and thin typed wrappers:
   ```python
   ACTIVITY_GET = Endpoint("GET", "/api/v1/activities/{id}", model=Activity,
                           status="verified", verified_on="2026-11-25")
   SCHEDULE_CLEAR = Endpoint("POST", "...", status="experimental", destructive=True)
   ```
   - Adding a captured endpoint then takes one registry line, one wrapper method and one fixture.
   - `experimental` endpoints log a warning when called.
   - **Writes are off by default.** `Sequence(allow_writes=False)` raises `WritesDisabled`.
   - Every write takes `dry_run=True` to return the prepared request without sending it.
   - **Destructive calls** also need `confirm=<id or date range>`. Before any delete or clear, the client saves the affected objects as JSON in `~/.local/state/.../backups/` automatically.
   - The CLI asks for `--yes` and shows what will change.

7. **Testing.**
   - **Mocking:** Use pytest with `respx`, which is built for httpx.
   - **Fixtures:** Split `docs/samples/` into `tests/fixtures/<method>_<path>.json`.
   - **Contract tests:** Every fixture must parse into its model. `model_extra` must be empty; unknown fields count as warnings in CI.
   - **Other tests:** Auth flows (expiry → re-login → replay), the "no write without opt-in" guard, dry-run output.
   - **Live tests:** Mark them `@pytest.mark.live`. They run only with `SEQUENCE_LIVE=1`, read-only, never in CI.
   - **CI (GitHub Actions):** Python 3.10–3.13, ruff, pyright strict, pytest with coverage, `gitleaks`, and a fixture-sanitization lint (see 9).

8. **CLI.** Use Typer with `rich` output, and add `--json` to every command.
   - **v0.1 commands:** `login`, `logout`, `whoami` (status and preferences), `workouts list|show ID`, `exercises list [--custom] [--search]`, `planner month 2026-11` / `planner range A B`, `tests list|show ID`, `dashboard`, `export DIR` (full JSON backup), `raw GET PATH` (GET only).

9. **Capture-to-spec pipeline.**
   - **Private:** HAR files go in a gitignored `captures/`.
   - **`tools/sanitize.py HAR`:** Filter to Sequence hosts and drop headers and cookies.
     - Replace IDs with deterministic fakes using a local salt, so links between objects survive.
     - Replace free text with `"text"` but keep the types and enum values.
     - Cut lists to 2 items instead of nulling them.
     - Write the results to `docs/samples/`.
   - **`tools/gen_docs.py`:** Build `docs/api.md` from the registry plus the samples. Each endpoint gets its status, verification date, query parameters and an example.
   - **`tools/lint_samples.py`:** Run it in pre-commit and CI. It rejects real-looking emails, JWT/CSRF-like strings, `Set-Cookie`, and UUIDs not on the fake list.

10. **README legal and ethics section.**
    - **Say:**
      - "Unofficial; not affiliated with or endorsed by Sequence."
      - The library uses your own account through the same endpoints the web app uses, and may break at any time.
      - No warranty; writes can damage your plan, so use dry-run.
      - Use it gently; it is throttled.
      - Read Sequence's Terms of Service yourself.
      - For read-only use, prefer the official MCP server.
    - **Do not include:** HARs, cookies, tokens, real IDs or names, the dashboard's JS bundle, logos, the built-in exercise library text and thumbnails, or paid plan or template content.
    - **Worth doing:** a polite note to Sequence before publishing on PyPI.

11. **Scope.**
    - **v0.1:** Auth with session persistence and re-login, all the observed reads, the CLI, `export`, and the write guard already in place.
    - **Write roadmap, lowest risk first:**
      1. Add a test result (append-only)
      2. Create a note
      3. Schedule a single workout
      4. Create or edit a workout with its exercises and sets
      5. Move or update a scheduled item
      6. Create a test template
      7. Single deletes
      8. Bulk schedule and clear last
    - Each step needs a capture, a fixture, and a live round-trip test on a throwaway object.

12. **Things a reviewer would flag.**
    - **Sanitizer bugs in the samples:**
      - `password_set_from_plan_purchase: "[REDACTED]"` is probably a boolean, so the type got lost.
      - Custom-test `fields[].key` is redacted, but you will likely need those keys to submit results. Fake them consistently instead.
    - **Truncated reads:** `/activities` and `/exercise_library_items` came back null. Re-capture them and check for pagination parameters (`page`, `limit`, `skip_widgets`).
    - **Dates and time zones:** Planner dates are local to the user's `time_zone`. Model them as `date`, not `datetime`. `user_month` takes `start_date_of_period`, which seems to be the Monday of the grid, so put that rule in the range helper.
    - **Privacy:** `/accounts/get_preferences` returns the user's email and name. Leave them out of `repr` and logs.
    - **Thread-safety:** One client per thread, or guard re-login with a lock. This matters for the MCP wrapper.
    - **Packaging:** Ship the MCP wrapper as an extra or a separate package (`[mcp]`). Version as SemVer 0.x and keep a CHANGELOG. Pin minimum versions only.
    - **Drift detection:** A periodic, manual live check that reports new fields or endpoints.
