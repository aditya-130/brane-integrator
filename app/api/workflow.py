import json
import logging
from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService
from app.infrastructure.database import get_db, engine
from app.infrastructure.dtos import GenerateWorkflowRequest, RunWorkflowRequest, RejectWorkflowRequest, AbortWorkflowRequest, DismissedWorkflowRequest
from app.infrastructure.llm_service import OpenAILlmService
from app.application.workflow_generation.workflow_job_handler import WorkflowJobHandler
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

router = APIRouter(prefix="/projects", tags=["workflows"])

logger = logging.getLogger(__name__)


@router.post("/{project_id}/workflows/generate", status_code=200)
def generate_workflow(
    project_id: int,
    request: GenerateWorkflowRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    existing = db_session.exec(
        select(Workflow).where(
            Workflow.project_id == project_id,
            Workflow.cycle_id == request.cycle_id,
        )
    ).first()
    if existing:
        return

    workflow = Workflow(
        project_id=project_id,
        cycle_id=request.cycle_id,
        triggered_at=request.triggered_at,
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    _workflow_id = workflow.workflow_id
    _cycle_id = request.cycle_id

    def job():
        with Session(engine) as db:
            try:
                WorkflowJobHandler(
                    db=db,
                    branehub_service=BraneHubService(),
                    llm_service=OpenAILlmService(),
                ).handle_generation(
                    _workflow_id,
                    project_id,
                    _cycle_id,
                )
            except Exception as exc:
                logger.error(
                    "[generate p%d c%d] generation failed: %s",
                    project_id, _cycle_id, exc,
                )
                BraneHubService().send_completed(
                    project_id=project_id,
                    cycle_id=_cycle_id,
                    script_version=0,
                    status="completed_failed",
                    result=None,
                    error=f"Generation failed: {str(exc)[:400]}",
                    duration_seconds=0,
                )

    background_tasks.add_task(job)
    return


@router.post("/{project_id}/workflows/reject", status_code=200)
def reject_workflow(
    project_id: int,
    request: RejectWorkflowRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    # Idempotency: only regenerate if this exact script_version is still awaiting review
    workflow = db_session.exec(
        select(Workflow).where(
            Workflow.project_id == project_id,
            Workflow.cycle_id == request.cycle_id,
            Workflow.script_version == request.script_version,
            Workflow.status == "generated",
        )
    ).first()

    if not workflow:
        # Duplicate rejection or unknown state — safe to ignore
        return

    # Reset so handle_generation can re-run the full pipeline
    workflow.status = "pending"
    db_session.add(workflow)
    db_session.commit()

    _workflow_id = workflow.workflow_id
    _cycle_id = request.cycle_id
    _script_version = request.script_version

    def job():
        with Session(engine) as db:
            try:
                WorkflowJobHandler(
                    db=db,
                    branehub_service=BraneHubService(),
                    llm_service=OpenAILlmService(),
                ).handle_generation(
                    _workflow_id,
                    project_id,
                    _cycle_id,
                )
            except Exception as exc:
                logger.error(
                    "[reject p%d c%d] regeneration failed: %s",
                    project_id, _cycle_id, exc,
                )
                BraneHubService().send_completed(
                    project_id=project_id,
                    cycle_id=_cycle_id,
                    script_version=_script_version,
                    status="completed_failed",
                    result=None,
                    error=f"Regeneration failed: {str(exc)[:400]}",
                    duration_seconds=0,
                )

    background_tasks.add_task(job)
    return


@router.post("/{project_id}/workflows/run", status_code=200)
def run_workflow(
    project_id: int,
    request: RunWorkflowRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    workflow = db_session.exec(
        select(Workflow)
        .where(
            Workflow.project_id == project_id,
            Workflow.cycle_id == request.cycle_id,
            Workflow.status == "generated",
        )
    ).first()

    if not workflow:
        raise HTTPException(
            status_code=404,
            detail="No generated workflow found for this project/cycle",
        )

    workflow.script_version = request.script_version
    db_session.add(workflow)
    db_session.commit()

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(
                db=db,
                branehub_service=BraneHubService(),
            ).handle_execution(workflow.workflow_id)

    background_tasks.add_task(job)
    return


@router.post("/{project_id}/abort", status_code=200)
def abort_workflow(
    project_id: int,
    request: AbortWorkflowRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    # Idempotency: only act if this (cycle_id, script_version) is currently executing
    workflow = db_session.exec(
        select(Workflow).where(
            Workflow.project_id == project_id,
            Workflow.cycle_id == request.cycle_id,
            Workflow.script_version == request.script_version,
            Workflow.status == "executing",
        )
    ).first()

    if not workflow:
        return

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(
                db=db,
                branehub_service=BraneHubService(),
            ).handle_abort(
                workflow.workflow_id,
                project_id,
                request.cycle_id,
                request.script_version,
            )

    background_tasks.add_task(job)
    return


@router.post("/{project_id}/workflows/dismissed", status_code=200)
def dismissed_workflow(
    project_id: int,
    request: DismissedWorkflowRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    # Idempotency: find any active workflow for this (project_id, cycle_id)
    workflow = db_session.exec(
        select(Workflow).where(
            Workflow.project_id == project_id,
            Workflow.cycle_id == request.cycle_id,
            Workflow.status.in_(["pending", "generating", "generated", "executing"]),
        )
    ).first()

    if not workflow:
        return

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(
                db=db,
                branehub_service=BraneHubService(),
            ).handle_dismissed(workflow.workflow_id)

    background_tasks.add_task(job)
    return


@router.get("/{project_id}/workflows/latest", status_code=200)
def get_latest_workflow(project_id: int, db_session: Session = Depends(get_db)):
    workflow = db_session.exec(
        select(Workflow)
        .where(Workflow.project_id == project_id)
        .where(Workflow.status.in_(["generated", "executing", "completed", "failed"]))
        .order_by(Workflow.created_at.desc())
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="No workflow found for this project")

    traceability = None
    if workflow.traceability_report:
        try:
            traceability = json.loads(workflow.traceability_report)
        except Exception:
            pass

    validation = None
    if workflow.validation_result:
        try:
            v = json.loads(workflow.validation_result)
            rules = v.get("rules", [])
            validation = {
                "passed": sum(1 for r in rules if r.get("passed")),
                "failed": sum(1 for r in rules if not r.get("passed")),
                "rules": rules,
            }
        except Exception:
            pass

    execution_result = None
    if workflow.execution_result:
        try:
            execution_result = json.loads(workflow.execution_result)
        except Exception:
            pass

    return {
        "workflow_id": workflow.workflow_id,
        "project_id": workflow.project_id,
        "cycle_id": workflow.cycle_id,
        "script_version": workflow.script_version,
        "status": workflow.status,
        "branescript": workflow.branescript,
        "traceability_report": traceability,
        "validation": validation,
        "note": workflow.note,
        "execution_result": execution_result,
        "generation_strategy": workflow.generation_strategy,
        "llm_calls_made": workflow.llm_calls_made,
        "regeneration_count": workflow.regeneration_count,
        "triggered_at": workflow.triggered_at,
        "executed_at": str(workflow.executed_at) if workflow.executed_at else None,
    }


@router.get("/{project_id}/workflows/{workflow_id}/metrics", status_code=200)
def get_workflow_metrics(
    project_id: int,
    workflow_id: str,
    db_session: Session = Depends(get_db),
):
    workflow = db_session.exec(
        select(Workflow).where(
            Workflow.workflow_id == workflow_id,
            Workflow.project_id == project_id,
        )
    ).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    validation_rules = None
    if workflow.validation_result:
        try:
            parsed = json.loads(workflow.validation_result)
            validation_rules = parsed.get("rules")
        except (json.JSONDecodeError, AttributeError):
            pass

    passed = sum(1 for r in validation_rules if r.get("passed")) if validation_rules else None
    failed = sum(1 for r in validation_rules if not r.get("passed")) if validation_rules else None

    execution_result = None
    if workflow.execution_result:
        try:
            execution_result = json.loads(workflow.execution_result)
        except Exception:
            pass

    return {
        "workflow_id": workflow.workflow_id,
        "project_id": workflow.project_id,
        "cycle_id": workflow.cycle_id,
        "status": workflow.status,
        "generation_strategy": workflow.generation_strategy,
        "llm_calls_made": workflow.llm_calls_made,
        "regeneration_count": workflow.regeneration_count,
        "generated_at": workflow.triggered_at,
        "executed_at": str(workflow.executed_at) if workflow.executed_at else None,
        "note": workflow.note,
        "execution_result": execution_result,
        "validation": {
            "passed": passed,
            "failed": failed,
            "rules": validation_rules,
        } if validation_rules is not None else None,
    }