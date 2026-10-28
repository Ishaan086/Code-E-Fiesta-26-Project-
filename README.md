# PS4 — Self-Healing Workflow Engine

A hackathon MVP for detecting business-workflow failures, diagnosing the cause, proposing constrained patches, validating repairs, routing risky changes for human approval, retrying safely, and verifying the final business invariants.

## Implemented in this starter

- FastAPI REST API and SQLite persistence.
- Three-step order workflow: `receive_order` → `create_crm_record` → `send_confirmation`.
- Three repeatable failure injections: schema drift, invalid date format, and missing email.
- Rule-first diagnosis and optional IBM watsonx.ai fallback for unfamiliar failures.
- Allowlisted patch operations with a maximum of two operations per patch.
- Protected fields: order ID, customer ID, and amount.
- Human approval for missing data and uncertain/high-risk proposals.
- Idempotent mock CRM/email services.
- RepairProof invariant checks after successful recovery.
- Approved repair memory, with schema fingerprint and revalidation.
- RecoveryBench: retry-only vs rule-only vs full system.
- React/Vite dashboard for pipeline, patch diff, incident timeline, approvals, mock data and benchmark results.
- Unit tests for failure injection and patch validation.

**Important limits:** the email integration is a database sink; it does not send real emails. The demo supports a bounded set of repairs, not arbitrary code changes or arbitrary production failures. The LLM is optional; without watsonx credentials, supported failure types are still handled by deterministic rules.

## Requirements

- Python 3.11+ recommended.
- Node.js 20+ recommended.
- IBM watsonx.ai credentials only if you want to enable the optional LLM diagnosis fallback.

## 1. Start the backend

Run from the project root, `ps4-self-healing/`:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The SQLite database file `ps4.db` will be created in the current working directory. Open [http://localhost:8000/docs](http://localhost:8000/docs) for interactive API documentation.

## 2. Optional: configure IBM watsonx.ai

Edit `backend/.env` and provide:

```dotenv
WATSONX_API_KEY=your_IBM_Cloud_API_key
WATSONX_PROJECT_ID=your_watsonx_project_id
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_MODEL_ID=ibm/granite-3-3-8b-instruct
WATSONX_API_VERSION=2024-05-31
```

Use the actual endpoint, model ID, and project ID available in your IBM account. Do not commit `.env` or put credentials in frontend code. The current implementation invokes the watsonx text-chat REST API as an optional diagnosis fallback. If it is unavailable or returns invalid output, the system falls back safely and escalates if no supported repair is known. The deterministic rules run before the LLM.

## 3. Start the dashboard

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The frontend polls the backend every ~1.3 seconds. To point it at another backend, create `frontend/.env`:

```dotenv
VITE_API_BASE=http://localhost:8000
```

Restart Vite after changing environment variables.

## 4. Try the demo

1. Open the dashboard and select **Schema drift**.
2. Click **Run workflow**. The system changes `phone` to `phone_number`, detects the validation error, proposes a rename, validates it, retries, then runs RepairProof.
3. Select **Bad date format** and repeat. The system converts `28/10/2026` to `2026-10-28`.
4. Select **Missing email**. The system should pause at **Pending approval**. Enter the correct email in the approval card, then click **Approve & retry**. Use synthetic data during your demo.
5. Open **Mock systems** to verify the CRM and email sink records.
6. Open **RecoveryBench** and start the 3-repetition benchmark. The dashboard will show the retry-only, rule-only, and full-system comparison after it completes.

## 5. Useful API calls

Start a schema drift run:

```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"inject":"schema_drift"}'
```

Read recent runs:

```bash
curl http://localhost:8000/runs
```

List incidents awaiting approval:

```bash
curl "http://localhost:8000/incidents?status=PENDING_APPROVAL"
```

Run a benchmark:

```bash
curl -X POST http://localhost:8000/benchmark \
  -H "Content-Type: application/json" \
  -d '{"repetitions":3,"include_human_approval_simulation":true}'
```

## 6. Run tests

From project root:

```bash
pytest backend/tests -q
```

## Architecture at a glance

```text
React dashboard
  └── FastAPI API
      ├── Workflow runner + failure injector
      ├── Detector + trace capture
      ├── Rule diagnoser → optional watsonx LLM fallback
      ├── Patch validator (allowlist, protected fields, schema check)
      ├── Risk router → auto-apply or human approval
      ├── Executor + idempotent mock CRM/email sink
      ├── RepairProof invariant checks
      ├── Approved repair memory
      └── RecoveryBench
          └── SQLite audit data and run history
```

## Safety notes and known MVP limitations

- Only the declared patch operations are supported. This code does not execute model-generated code, SQL, shell commands, or arbitrary scripts.
- The initial failure injector targets input validation at the first step. The pipeline traces all three steps and writes mock CRM/email data after validation; adding safe injection at later side-effecting steps should be done only alongside an idempotency test.
- Confidence is not a probability guarantee. It is one routing signal alongside deterministic validation and operation type.
- Benchmark results depend on the included synthetic cases and do not establish production reliability. Show the sample size and the exact baseline definitions in your presentation.
- This is an unauthenticated local hackathon prototype. Do not expose it publicly or use real customer data without adding authentication, authorization, secret management, and deployment security.
