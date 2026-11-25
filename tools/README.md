# tools

Scripts around the capture → spec pipeline. Raw captures (HAR/JSONL) are **private**: keep them in the gitignored
`captures/` directory and never commit them.

| script | purpose |
| --- | --- |
| `sanitize_captures.py capture.jsonl out_dir` | Turn a raw capture into publishable samples: UUIDs → deterministic fakes (also in query strings), e-mails → `user@example.com`, free text → `"text"`, lists cut to 2 items, secrets dropped. Every fake UUID minted is merged into `fake_uuids.txt`. |
| `split_samples.py` | Split `docs/samples/samples.json` into `tests/fixtures/<method>_<path>.json`. |
| `lint_samples.py [paths]` | Fail if samples/fixtures contain UUIDs not in `fake_uuids.txt`, non-`example.*` e-mails, JWT/long hex/base64 strings, cookie/authorization headers, or secret-looking values. Defaults to `docs/samples` and `tests/fixtures`. Exceptions only via `lint_allow.txt` (exact strings). |
| `gen_docs.py [--check]` | Generate `docs/api.md` from the endpoint registry plus the samples. |

Workflow for a newly captured endpoint:

1. `python tools/sanitize_captures.py captures/new.jsonl docs/samples` (review the diff).
2. `python tools/split_samples.py`, then `python tools/lint_samples.py`.
3. Add one `Endpoint(...)` line in `src/sequence_unofficial/endpoints.py` (model + `status`), one wrapper method in
   `resources/`, and a model if the body is new. The contract tests will tell you what is missing.
4. `python tools/gen_docs.py`, run the tests, commit.

Pre-commit / CI should run `lint_samples.py` over all tracked samples, not just changed files.
