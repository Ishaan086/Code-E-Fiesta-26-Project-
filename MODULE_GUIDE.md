# PS4 module-by-module guide

## Recommended build order

1. `backend/schemas.py` — define the order and patch contracts first.
2. `backend/models.py` + `backend/db.py` — persist runs, traces, incidents, business writes, repair memory and benchmark results.
3. `backend/workflow/injector.py` — make failures repeatable before building AI.
4. `backend/workflow/services.py` — create idempotent mock CRM and email-sink writes.
5. `backend/observability.py` — use the same event/trace functions throughout the codebase.
6. `backend/healing/diagnoser.py` — rule-based signatures first, optional model fallback second.
7. `backend/healing/patch_ops.py` + `backend/healing/validator.py` — allowlisted patch application and deterministic validation.
8. `backend/healing/repair_proof.py` — verify business invariants after the retry.
9. `backend/workflow/pipeline.py` — connect detection, diagnosis, risk routing, approval, retries and final verification.
10. `backend/memory/repair_memory.py` — reuse previously verified safe patches without bypassing validation.
11. `backend/evaluation/benchmark.py` — compare retry-only, rule-only, and full system modes.
12. `backend/main.py` — REST endpoints and app startup.
13. `frontend/src/api/client.js` + `frontend/src/App.jsx` + `frontend/src/styles.css` — connect the dashboard to the REST API.

## Module ownership

| Module | Responsibility |
|---|---|
| `schemas.py` | Pydantic API and data contracts |
| `models.py` | SQLAlchemy database tables |
| `db.py` | SQLite engine, sessions and table initialization |
| `workflow/injector.py` | Controlled, reproducible failure mutation |
| `workflow/pipeline.py` | Main lifecycle and retry/approval orchestration |
| `workflow/services.py` | Mock CRM/email sink; idempotent writes |
| `observability.py` | Persistent step traces and incident events |
| `healing/diagnoser.py` | Error signatures, rule diagnosis, repair-memory lookup and LLM fallback |
| `healing/llm_provider.py` | Optional IBM watsonx.ai REST adapter |
| `healing/patch_ops.py` | Apply only declared patch operation types |
| `healing/validator.py` | Allowlist, protected fields, operation limit and schema validation |
| `healing/repair_proof.py` | Verify post-recovery invariants |
| `memory/repair_memory.py` | Store/reuse verified patches; does not store customer-specific email values |
| `evaluation/benchmark.py` | Execute comparable test cases and aggregate metrics |
| `main.py` | REST endpoints and dashboard summary endpoint |
| `frontend/src/App.jsx` | Dashboard screens, polling and operator actions |

## Test checkpoints

- `pytest backend/tests -q`: unit tests for injection and patch validation.
- API smoke test: `POST /runs` with `schema_drift` should reach `RECOVERED`.
- API smoke test: `POST /runs` with `bad_format` should reach `RECOVERED`.
- API smoke test: `POST /runs` with `missing_field` should reach `PENDING_APPROVAL`, then recover after an operator provides a valid email.
- RepairProof should show all invariants as true for a successful demo recovery.
- `POST /benchmark` should produce results for all three modes and the configured repetition count.
