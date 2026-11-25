# Design consultation: unofficial Python client for the Sequence climbing-training web app

You are a senior Python library architect. Be decisive and concrete. Answer in English, max ~900 words, as a numbered list of DECISIONS (each: choice + 1-2 line reason + any risk). No code unless it is a 5-line sketch.

## Context
- Sequence (https://www.sequence-app.com, web dashboard at https://dashboard.sequence-app.com) is a climbing training planner: workouts (called "activities"), exercises library, planner (scheduled workouts, `schedules`), custom tests with results, goals, notes/milestones, metrics.
- It has NO public API and no existing client. It has an official read-only MCP server (OAuth). The web dashboard talks to a JSON REST backend: `/api/v1/...` plus `/accounts/...`. We reverse-engineer it from the browser's own network traffic for a PERSONAL-USE, open-source, clearly "unofficial" package that will be published on GitHub (and maybe PyPI) by an individual, not Sequence.
- Auth observed: `POST /signin` with JSON `{email, password}`; response is JSON `{user: {...}, csrf: "..."}` (so there is a CSRF token to be sent on writes, header name still unknown) and sets a session cookie. Reads only send `Accept: application/json`. The server expires the session often (hours), then redirects to /sign-in.
- Observed READ endpoints (all 200): GET /accounts/get_preferences, /accounts/get_settings, /accounts/status, /api/v1/activities (list of workouts, large), /api/v1/activities/{id} (workout with nested exercises/sets), /api/v1/categories, /api/v1/exercise_library_items (large), /api/v1/schedules/user_month (planner for a month, query by month), /api/v1/dashboard, /api/v1/custom_test_progress, /api/v1/custom_test_templates/{id}/progress, /api/v1/metrics/{activity_all_time,activity_list,activity_magic_number}, /api/v1/strava/status, /api/v1/the_crag/status, /api/v1/coaching/messages/conversations, /api/v1/experimental_features.
- WRITE endpoints (create/update/delete workout, exercise, test template, test result, schedule single/bulk/clear, notes) are NOT captured yet. We will capture them gradually while using the web app, so the package must grow incrementally: a first version ships with auth + reads, then writes are added as captured.
- Sanitized response samples are in docs/samples/samples.json (structure, types, enums kept; text replaced by "text"; ids faked; large lists cut). Some large responses are null there because the capture truncated them.
- Constraints: personal use, rate-limit politely, never store passwords in the repo, tests must run offline on sanitized fixtures, Python >= 3.10, the author's tooling is an AI agent + Claude Code, a CLI is useful, and a thin MCP wrapper may come later (so the core must be a clean library).

## Decide
1. Package/distribution name and import name (must make "unofficial" clear; check it is plausible on PyPI), license.
2. Layout (src layout, modules), and sync vs async vs both (and why), HTTP library.
3. Models: pydantic v2 vs dataclasses vs TypedDict, and how to deal with an API we only partly understand (unknown/extra fields, forward compatibility, `raw` escape hatch).
4. Auth/session: credentials source order, cookie persistence on disk (where, permissions), CSRF handling, automatic re-login on session expiry, 2FA absence.
5. Error model and retry/backoff/rate limiting policy.
6. How to structure the client so adding a newly captured endpoint is cheap (resource classes? generic `request()` + typed wrappers?), and how to mark endpoints as "verified from capture on <date>" vs experimental. Write operations should be safe by default (dry-run? explicit flag?) because a bug could delete the user's training plan.
7. Testing strategy offline (respx/pytest-httpx? fixtures from sanitized samples), contract tests, what CI to add.
8. CLI framework and the minimal v0.1 command set.
9. The capture-to-spec pipeline: keep the raw capture private, publish only sanitized samples; suggest a tiny workflow/script layout so each new capture updates docs/api.md and fixtures.
10. Legal/ethics section for README (what to say; what NOT to include in the repo).
11. v0.1 scope: exactly which features ship first, and the roadmap order for write endpoints.
12. Anything I forgot that a reviewer would flag.
