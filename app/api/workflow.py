from app.domain.workflow import Workflow
from app.infrastructure.database import get_db, engine
from app.infrastructure.dtos import GenerateWorkflowRequest
from app.application.workflow_job_handler import WorkflowJobHandler
from app.infrastructure.branehub_service import BraneHubService
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlmodel import Session

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.post("/generate-workflow", status_code=200)
def generate_workflow(request: GenerateWorkflowRequest, background_tasks: BackgroundTasks, db_session: Session = Depends(get_db)):
    workflow = Workflow(
        project_id=request.project_id,
        cycle_id=request.cycle_id,
        triggered_at=request.triggered_at,
    )
    db_session.add(workflow)
    db_session.commit()
    db_session.refresh(workflow)

    def job():
        with Session(engine) as db:
            WorkflowJobHandler(db=db, branehub_service=BraneHubService()).run(
                workflow.workflow_id, request.project_id, request.cycle_id
            )

    background_tasks.add_task(job)
    return