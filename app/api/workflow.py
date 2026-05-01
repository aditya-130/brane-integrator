from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService
from app.infrastructure.database import get_db, engine
from app.infrastructure.dtos import GenerateWorkflowRequest
from app.application.workflow_job_handler import WorkflowJobHandler
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlmodel import Session

router = APIRouter(prefix="/projects", tags=["workflows"])


@router.post("/{project_id}/workflows/generate", status_code=200)
def generate_workflow(
    project_id: int,
    request: GenerateWorkflowRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    workflow = Workflow(project_id=project_id, cycle_id=request.cycle_id, triggered_at=request.triggered_at)
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(db=db, branehub_service=BraneHubService(),).handle_generation(workflow.workflow_id, project_id, request.cycle_id)

    background_tasks.add_task(job)
    return