import json

from sqlalchemy import select

from backend.config import GEMMA_MODEL_ID
from backend.db import SessionLocal
from backend.models import AutomationSimulation, Run
from backend.observability import now_utc
from backend.healing.gemma_simulator import (
    DEFAULT_SIMULATION_PROMPT,
    generate_simulation_spec,
    apply_simulated_fault,
)
from backend.workflow.pipeline import execute_run


def simulate_and_execute_run(
    run_id: int,
    simulation_prompt: str | None = None,
) -> None:
    """Generate a synthetic fault, then send it through the existing engine."""

    db = SessionLocal()
    record = None

    try:
        run = db.get(Run, run_id)

        if not run:
            return

        run.status = "SIMULATING"
        run.error = None
        db.commit()

        record = AutomationSimulation(
            run_id=run_id,
            model_id=GEMMA_MODEL_ID,
            status="GENERATING",
            user_prompt=(
                simulation_prompt or DEFAULT_SIMULATION_PROMPT
            )[:1000],
            title="Generating an AI automation incident",
            description=(
                "Gemma is generating a scenario using synthetic data. "
                "No model-generated code will be executed."
            ),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        recent_types = db.scalars(
            select(AutomationSimulation.fault_type)
            .where(AutomationSimulation.status == "GENERATED")
            .order_by(AutomationSimulation.id.desc())
            .limit(5)
        ).all()

        # Use only the synthetic order already prepared by the API.
        original = json.loads(run.input_json)

        spec = generate_simulation_spec(
            simulation_prompt,
            previous_types=list(recent_types),
        )

        mutated, applied_ops, expected_handling = (
            apply_simulated_fault(original, spec)
        )

        record.status = "GENERATED"
        record.fault_type = spec.issue_category
        record.title = spec.title
        record.description = spec.description
        record.automation_component = spec.automation_component
        record.mutation_json = json.dumps(applied_ops)
        record.expected_handling = expected_handling
        record.error = None

        run.payload_json = json.dumps(mutated)
        run.inject_type = "gemma_simulate"
        run.status = "QUEUED"

        db.commit()

    except Exception as exc:
        db.rollback()

        run = db.get(Run, run_id)

        if record:
            record = db.get(AutomationSimulation, record.id)
        else:
            record = db.scalar(
                select(AutomationSimulation)
                .where(AutomationSimulation.run_id == run_id)
            )

        if record:
            record.status = "FAILED"
            record.error = str(exc)[:1500]

        if run:
            run.status = "ERROR"
            run.error = str(exc)[:1500]
            run.ended_at = now_utc()

        db.commit()
        return

    finally:
        db.close()

    # Gemma does not execute or repair the workflow directly.
    # Your existing healing engine performs diagnosis, validation,
    # approval routing, execution, retry, and RepairProof.
    execute_run(run_id)