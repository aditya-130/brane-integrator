import json
import subprocess
import tempfile
import re
import os
import time
from app.application.config_parser import ConfigParser
from app.application.policy_interpreter import PolicyInterpreter
from app.application.workflow_generator import WorkflowGenerator
from app.application.validator import Validator
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
        self.validator = Validator()

    def handle_generation(self, workflow_id: str, project_id: int, cycle_id: int):

        # 1. update workflow status
        workflow = self.db.get(Workflow, workflow_id)
        workflow.status = "generating"
        self.db.add(workflow)
        self.db.commit()

        # 2. fetch raw project config from BraneHub
        raw = self.branehub_service.fetch_project_config(project_id)

        # 3. parse into IntegratorConfig
        integrator_config = self.config_parser.parse(raw)

        # 4. interpret policies
        interpreted = self.policy_interpreter.interpret(integrator_config)

        # 5. generate branescript
        branescript = self.workflow_generator.generate(integrator_config, interpreted)

        # 6. validate + generate traceability report
        validation_result = self.validator.validate(branescript, integrator_config, interpreted)
        traceability_report = self.validator.generate_traceability_report(
            branescript, integrator_config, interpreted
        )

        if not validation_result.passed:
            workflow.status = "failed"
            self.db.add(workflow)
            self.db.commit()
            failed_rules = [r.rule for r in validation_result.rules if not r.passed]
            raise RuntimeError(f"Validation failed: {failed_rules}")

        # 7. save to workflow row
        workflow.branescript = branescript
        workflow.traceability_report = json.dumps(traceability_report)
        workflow.status = "generated"
        self.db.add(workflow)
        self.db.commit()

        # 8. upload script to BraneHub
        self.branehub_service.mock_send_bs_to_branehub(
            branescript,
            traceability_report,
            workflow.project_id,
            workflow.cycle_id,
        )

    def handle_execution(self, workflow_id: str) -> str:

        # 1. update workflow status
        workflow = self.db.get(Workflow, workflow_id)
        workflow.status = "executing"
        self.db.add(workflow)
        self.db.commit()

        # 2. strip tag annotations before submitting to Brane
        #
        # The generated BraneScript (stored in DB) includes #[tag()] and #![wf_tag()]
        # annotations produced by the PolicyInterpreter. These constructs are correct
        # per the Brane policy design and form part of the traceability report.
        #
        # ROOT CAUSE (Brane nightly 3.0.0-nightly_7175fba8 bug):
        # The eFLINT base ontology defines tag as a 2-component fact:
        #   Fact tag Identified by user * string.   (brane-chk/policy/metadata.eflint)
        # However, the Brane Rust checker (brane-chk/src/workflow/eflint.rs:74)
        # serialises tag annotations as a 1-component assertion:
        #   +tag("identifiability.Pseudonymized")   <- missing the user component
        # The eFLINT engine rejects this with "elements of tag have 2 components,
        # 1 given", causing the checker to return an internal gRPC error, which
        # causes the planner to abort with "Failed to plan workflow".
        #
        # Workaround: strip #[tag()] and #![wf_tag()] lines before writing the
        # temp file submitted to Brane. The full annotated script remains in the DB.
        executable_script = "\n".join(
            line for line in workflow.branescript.splitlines()
            if not line.startswith("#[tag(") and not line.startswith("#![wf_tag(")
        )

        with tempfile.NamedTemporaryFile(suffix=".bs", mode="w", delete=False) as f:
            f.write(executable_script)
            tmpfile = f.name

        # 3. run brane CLI
        start_time = time.time()
        try:
            proc = subprocess.run(
                ["/usr/local/bin/brane", "workflow", "run", "--remote", "central", tmpfile],
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            os.unlink(tmpfile)

        # 4. parse result and update status
        duration = int(time.time() - start_time)
        match = re.search(r"Workflow returned value '(.+)'", proc.stdout)
        if proc.returncode == 0 and match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                result = None

            if result:
                workflow.status = "completed"
                self.db.add(workflow)
                self.db.commit()
                self.branehub_service.mock_send_completed(
                    project_id=workflow.project_id,
                    cycle_id=workflow.cycle_id,
                    script_version=workflow.script_version,
                    status="completed_success",
                    result=result,
                    error=None,
                    duration_seconds=duration,
                )
            else:
                workflow.status = "failed"
                self.db.add(workflow)
                self.db.commit()
                self.branehub_service.mock_send_completed(
                    project_id=workflow.project_id,
                    cycle_id=workflow.cycle_id,
                    script_version=workflow.script_version,
                    status="completed_failed",
                    result=None,
                    error="Brane output could not be parsed as JSON",
                    duration_seconds=duration,
                )
        else:
            error = proc.stderr or proc.stdout or "brane exited with no output"
            workflow.status = "failed"
            self.db.add(workflow)
            self.db.commit()
            self.branehub_service.mock_send_completed(
                project_id=workflow.project_id,
                cycle_id=workflow.cycle_id,
                script_version=workflow.script_version,
                status="completed_failed",
                result=None,
                error=error,
                duration_seconds=duration,
            )