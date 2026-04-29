from app.application.config_parser import ConfigParser
from sqlmodel import Session
from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService


class WorkflowJobHandler:
    def __init__(self, db: Session, branehub_service: BraneHubService):
        self.db = db
        self.branehub_service = branehub_service
        self.config_parser = ConfigParser(db_session=db)

    def run(self, workflow_id: str, project_id: int, cycle_id: int):

        # 1. update workflow status 
        workflow = self.db.get(Workflow, workflow_id)
        workflow.status = "generating"
        self.db.add(workflow)
        self.db.commit()

        # 2. fetch raw project config from BraneHub
        raw = self.branehub_service.fetch_mock_project_config(project_id)

        # 3. parse into IntegratorConfig
        integrator_config = self.config_parser.parse(raw)
        print(integrator_config.model_dump_json(indent=2))



        # 4. interpret policies
        # 5. generate branescript + traceability report
        # 6. save to workflow row
        # 7. upload script to BraneHub
        pass