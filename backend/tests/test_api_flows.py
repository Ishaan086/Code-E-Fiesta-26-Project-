"""Integration regression tests for the unified predefined + Gemma app flows."""
from __future__ import annotations

import os
# Ensure API-flow tests use an isolated local SQLite file, never a developer DB.
os.environ["DATABASE_URL"] = "sqlite:///./.test_helios_api.db"

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.workflow.ai_simulation as ai_simulation
from backend.db import Base, engine
from backend.healing.gemma_simulator import GemmaSimulationSpec


@pytest.fixture(autouse=True)
def reset_test_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_predefined_schema_drift_recovers():
    with TestClient(main_module.app) as client:
        response = client.post("/runs", json={"inject": "schema_drift"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]

        run = client.get(f"/runs/{run_id}").json()
        assert run["status"] == "RECOVERED"
        assert run["traces"]
        assert run["incidents"][0]["status"] == "RECOVERED"


def test_missing_email_approval_and_rejection():
    with TestClient(main_module.app) as client:
        pending_response = client.post("/runs", json={"inject": "missing_field"})
        pending_run_id = pending_response.json()["run_id"]
        pending_run = client.get(f"/runs/{pending_run_id}").json()
        assert pending_run["status"] == "PENDING_APPROVAL"
        incident = next(
            item for item in pending_run["incidents"]
            if item["status"] == "PENDING_APPROVAL"
        )

        approved = client.post(
            f"/incidents/{incident['id']}/approve",
            json={"field": "email", "value": "synthetic@example.com"},
        )
        assert approved.status_code == 202
        assert client.get(f"/runs/{pending_run_id}").json()["status"] == "RECOVERED"

        reject_response = client.post("/runs", json={"inject": "missing_field"})
        rejected_run_id = reject_response.json()["run_id"]
        rejected_run = client.get(f"/runs/{rejected_run_id}").json()
        rejected_incident = next(
            item for item in rejected_run["incidents"]
            if item["status"] == "PENDING_APPROVAL"
        )

        rejected = client.post(f"/incidents/{rejected_incident['id']}/reject")
        assert rejected.status_code == 200
        assert client.get(f"/runs/{rejected_run_id}").json()["status"] == "CLOSED_MANUAL"


def test_recoverybench_completes_and_persists_trials():
    with TestClient(main_module.app) as client:
        response = client.post(
            "/benchmark",
            json={"repetitions": 1, "include_human_approval_simulation": True},
        )
        assert response.status_code == 202
        benchmark_id = response.json()["benchmark_id"]

        result = client.get(f"/benchmark/{benchmark_id}").json()
        assert result["status"] == "COMPLETED"
        assert len(result["trials"]) == 9
        assert set(result["metrics"]) == {"retry_only", "rule_only", "full"}


def test_gemma_generated_failure_uses_shared_approval_flow(monkeypatch):
    generated_spec = GemmaSimulationSpec(
        issue_category="Package delivery contact failure",
        title="Missing customer email for tracking",
        description=(
            "The package shipment workflow has no verified email for sending tracking details."
        ),
        automation_component="Delivery notification mapper",
        mutations=[{"op": "remove_field", "field": "email"}],
    )

    monkeypatch.setattr(main_module, "gemma_is_configured", lambda: True)
    monkeypatch.setattr(
        ai_simulation,
        "generate_simulation_spec",
        lambda prompt, previous_types=None: generated_spec,
    )

    with TestClient(main_module.app) as client:
        response = client.post(
            "/runs",
            json={
                "inject": "gemma_simulate",
                "simulation_prompt": "Generate a synthetic package delivery failure requiring approval.",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]

        run = client.get(f"/runs/{run_id}").json()
        assert run["simulation"]["status"] == "GENERATED"
        assert run["simulation"]["expected_handling"] == "HUMAN_APPROVAL"
        assert run["status"] == "PENDING_APPROVAL"


def test_production_frontend_cors_preflight_is_allowed():
    with TestClient(main_module.app) as client:
        response = client.options(
            "/dashboard/summary",
            headers={
                "Origin": "https://code-e-fiesta-26-project.vercel.app",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == (
            "https://code-e-fiesta-26-project.vercel.app"
        )
