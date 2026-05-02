from app.application.config_parser import ConfigParser
from app.application.policy_interpreter import PolicyInterpreter
from app.application.workflow_generator import WorkflowGenerator
from sqlmodel import Session
from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService


class WorkflowJobHandler:
    def __init__(self, db: Session, branehub_service: BraneHubService):
        self.db = db
        self.branehub_service = branehub_service
        self.config_parser = ConfigParser(db_session=db)
        self.policy_interpreter = PolicyInterpreter()
        self.workflow_generator = WorkflowGenerator()

    def handle_generation(self, workflow_id: str, project_id: int, cycle_id: int):

        # 1. update workflow status 
        workflow = self.db.get(Workflow, workflow_id)
        workflow.status = "generating"
        self.db.add(workflow)
        self.db.commit()

        # 2. fetch raw project config from BraneHub
        raw = self.branehub_service.fetch_mock_project_config(project_id)

        # 3. parse into IntegratorConfig
        integrator_config = self.config_parser.parse(raw)

        # 4. interpret policies
        interpreted = self.policy_interpreter.interpret(integrator_config)

        # 5. generate branescript + traceability report
        branescript = self.workflow_generator.generate(integrator_config, interpreted)

        # 6. save to workflow row
        workflow.branescript = branescript
        workflow.status = "generated"
        self.db.add(workflow)
        self.db.commit()

        # 7. upload script to BraneHub
        self.branehub_service.mock_send_bs_to_branehub(branescript, workflow.project_id, workflow.cycle_id)
        pass