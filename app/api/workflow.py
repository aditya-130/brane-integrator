from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService
from app.infrastructure.database import get_db, engine
from app.infrastructure.dtos import GenerateWorkflowRequest, RunWorkflowRequest
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