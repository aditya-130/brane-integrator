from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService
from app.infrastructure.database import get_db, engine
from app.infrastructure.dtos import GenerateWorkflowRequest, RunWorkflowRequest, RejectWorkflowRequest, AbortWorkflowRequest, DismissedWorkflowRequest
from app.application.workflow_job_handler import WorkflowJobHandler
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

router = APIRouter(prefix="/projects", tags=["workflows"])


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
    if existing and existing.status != "pending":
        return

    workflow = Workflow(
        project_id=project_id,
        cycle_id=request.cycle_id,
        triggered_at=request.triggered_at,
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(
                db=db,
                branehub_service=BraneHubService(),
            ).handle_generation(
                workflow.workflow_id,
                project_id,
                request.cycle_id,
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

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(
                db=db,
                branehub_service=BraneHubService(),
            ).handle_generation(
                workflow.workflow_id,
                project_id,
                request.cycle_id,
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