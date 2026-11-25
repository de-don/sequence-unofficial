# Agent brief — sequence-unofficial

Unofficial Python client + CLI for the Sequence climbing-training web app (dashboard.sequence-app.com).
Personal-use, open-source, will be published on GitHub by an individual. NOT affiliated with Sequence.

## Binding design decisions
`docs/opus_design_answer.md` is the approved design (made by Opus). Follow it. Summary: PyPI name `sequence-unofficial`,
import `sequence_unofficial`, CLI `sequence-unofficial` (+ alias `squ`), MIT, src layout, sync httpx, pydantic v2 (`extra="allow"`,
fields optional except `id`, `.raw`), session cookie + CSRF persisted at user_state_dir with 0600, retries only for GET,
writes OFF by default (`allow_writes`), `dry_run`, destructive calls need `confirm=`, declarative endpoint registry
(`status="verified"|"experimental"`), Typer + rich CLI with `--json`, pytest + respx offline tests on sanitized fixtures.
`docs/opus_design_brief.md` has the context; `docs/samples/samples.json` has sanitized API samples (the only API data you may use).

## Hard rules
- There are NO real credentials and you must NOT call dashboard.sequence-app.com. All tests run offline (respx). No live tests are run by you.
- Never put real personal data in the repo: no emails, names, real ids, cookies, tokens. Fixtures come only from `docs/samples/`.
- Never run `git push`, never add a remote, never publish to PyPI. Local commits on the current branch are OK.
- Write operations are not captured yet. Implement the safety machinery (registry, `WritesDisabled`, dry-run, confirm) but do NOT invent
  write endpoints or request bodies. Only what is in the samples exists.
- Python >= 3.10. Use `uv` for the venv (`~/.hermes/tools/uv-0.12.3-darwin-arm64/uv`, put its directory on PATH in your commands; the Python is `~/.hermes/tools/python-3.14.7+*/bin/python3`, pass it with `uv venv --python`). Dev tools: pytest, respx, ruff, pyright.
- Keep it small and readable. No speculative abstractions.
- Do not edit `docs/opus_design_answer.md` or `docs/opus_design_brief.md`.

## Consulting Opus (required for architectural decisions)
When you hit a decision that is not already settled in the design (public API shape, how a model should treat a tricky field,
session/CSRF edge cases, anything you hesitate about), ask Opus before deciding. Write the question + the relevant facts to a file in
`.opus/` (no personal data) and run:

    CLAUDE_CONFIG_DIR="$HOME/.claude-personal" claude -p --model opus --effort high --tools "" --max-turns 2 --no-session-persistence < .opus/q1.md > .opus/a1.md

Read the answer, follow it, and record each consultation in `docs/decisions.md` (question, answer summary, what you did).
Aim for at least 3 consultations about real decisions; do not invent trivial ones.

## Definition of done for this task (v0.1)
1. Project scaffold: pyproject.toml (hatchling), src layout, LICENSE (MIT), README (with the legal/ethics section from the design), CHANGELOG, .gitignore already exists, py.typed.
2. Auth + session persistence + re-login on expiry, CSRF kept (header name unknown: make it configurable, default `X-CSRF-Token`, mark as unverified).
3. All observed READ endpoints as typed resources with models, built from `docs/samples/samples.json` (parse every sample in tests).
4. Registry-driven transport with retries/throttle/User-Agent/log redaction as specified.
5. CLI (Typer): login, logout, whoami, workouts list|show, exercises list, planner month, tests list|show, dashboard, export DIR, raw GET PATH.
6. tests/ with fixtures split from docs/samples, contract tests, auth-expiry replay test, write-guard test, dry-run test; all green; ruff clean; pyright clean.
7. tools/: `sanitize_captures.py` already exists, document it, add `tools/lint_samples.py` (reject emails, JWT-like strings, UUIDs not from the fake list).
8. docs/api.md generated from the registry + samples (`tools/gen_docs.py`), docs/decisions.md.
9. Local git commits in logical steps. Final message: what was built, how to run tests, open questions, known gaps.
