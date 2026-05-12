import json
import logging
import subprocess
import tempfile
import re
import os
import time
from datetime import datetime, timezone
from app.infrastructure.settings import settings

logger = logging.getLogger(__name__)
from app.application.config_parser import ConfigParser
from app.application.free_text_extractor import FreeTextExtractor
from app.application.policy_interpreter import PolicyInterpreter
from app.application.prompt_builder import PromptBuilder
from app.application.workflow_generation.template_generator import TemplateGenerator
from app.application.workflow_generation.llm_generator import LlmGenerator
from app.application.validator import Validator
from sqlmodel import Session
from app.domain.workflow import Workflow
from app.infrastructure.branehub_service import BraneHubService
from app.infrastructure.llm_service import LlmService

# Keyed by workflow_id. Populated when a Brane subprocess starts; removed when it exits.
_running_processes: dict[str, subprocess.Popen] = {}
# workflow_ids that were externally stopped (abort/dismissed). handle_execution checks this
# after communicate() returns to decide whether to call send_completed itself.
_aborted_workflows: set[str] = set()


class WorkflowJobHandler:
    def __init__(self, db: Session, branehub_service: BraneHubService, llm_service: LlmService | None = None):
        self.db = db
        self.branehub_service = branehub_service
        self.llm_service = llm_service
        self.config_parser = ConfigParser(db_session=db)
        self.free_text_extractor = FreeTextExtractor()
        self.policy_interpreter = PolicyInterpreter()
        self.prompt_builder = PromptBuilder()
        self.validator = Validator()

    def handle_generation(self, workflow_id: str, project_id: int, cycle_id: int):
        logger.info("[%s] Starting generation for project_id=%d cycle_id=%d", workflow_id, project_id, cycle_id)

        # 1. update workflow status
        workflow = self.db.get(Workflow, workflow_id)
        workflow.status = "generating"
        self.db.add(workflow)
        self.db.commit()

        # 2. fetch raw project config from BraneHub
        raw = self.branehub_service.fetch_project_config(project_id)

        # 3. parse into IntegratorConfig
        integrator_config = self.config_parser.parse(raw)
        logger.info("[%s] Config parsed — package=%s, participants=%d", workflow_id, integrator_config.workflow.package, len(integrator_config.participants))

        # 3.5 extract policy claims from free-text fields
        llm_calls = 0
        integrator_config = self.free_text_extractor.extract(integrator_config, self.llm_service)
        if self.llm_service:
            llm_calls += 1
            logger.info("[%s] Free-text extraction done (llm_calls so far: %d)", workflow_id, llm_calls)

        # 4. interpret policies
        interpreted = self.policy_interpreter.interpret(integrator_config)
        logger.info("[%s] Policies interpreted — wf_tags=%s", workflow_id, interpreted.wf_tags)

        # 5. generate branescript — dispatch to template or LLM generator
        pattern = settings.WORKFLOW_GENERATION_STRATEGY
        logger.info("[%s] Generation strategy: %s", workflow_id, pattern)
        if pattern == "llm":
            if not self.llm_service:
                raise RuntimeError("LlmGenerator requires llm_service but none was provided")
            generator = LlmGenerator(self.llm_service)
            branescript = generator.generate(integrator_config, interpreted)
            llm_calls += generator.llm_calls_made
            logger.info("[%s] LlmGenerator done — llm_calls_made=%d total_llm_calls=%d", workflow_id, generator.llm_calls_made, llm_calls)
        else:
            branescript = TemplateGenerator().generate(integrator_config, interpreted)
            logger.info("[%s] TemplateGenerator done", workflow_id)

        # 6. validate + generate traceability report
        validation_result = self.validator.validate(branescript, integrator_config, interpreted)
        passed = sum(1 for r in validation_result.rules if r.passed)
        failed = sum(1 for r in validation_result.rules if not r.passed)
        logger.info("[%s] Validation complete — passed=%d failed=%d overall=%s", workflow_id, passed, failed, "PASS" if validation_result.passed else "FAIL")
        if not validation_result.passed:
            for r in validation_result.rules:
                if not r.passed:
                    logger.warning("[%s] Rule FAILED: %s — %s", workflow_id, r.rule, r.message)

        traceability_report = self.validator.generate_traceability_report(
            branescript, integrator_config, interpreted
        )

        if not validation_result.passed:
            workflow.status = "failed"
            workflow.generation_strategy = pattern
            workflow.validation_result = validation_result.model_dump_json()
            self.db.add(workflow)
            self.db.commit()
            failed_rules = [r.rule for r in validation_result.rules if not r.passed]
            raise RuntimeError(f"Validation failed: {failed_rules}")

        # 7. save to workflow row
        regeneration_count = (workflow.regeneration_count or 0) + (1 if workflow.branescript else 0)
        workflow.branescript = branescript
        workflow.traceability_report = json.dumps(traceability_report)
        workflow.validation_result = validation_result.model_dump_json()
        workflow.generation_strategy = pattern
        workflow.llm_calls_made = llm_calls
        workflow.regeneration_count = regeneration_count
        workflow.status = "generated"
        self.db.add(workflow)
        self.db.commit()

        # 8. generate plain-language note for the owner review UI
        note = self._generate_note(branescript, json.dumps(traceability_report))

        # 9. upload script to BraneHub
        participants_used = [p.user_id for p in integrator_config.participants]
        script_version = self.branehub_service.send_script_to_branehub(
            branescript=branescript,
            traceability_report=json.dumps(traceability_report),
            project_id=workflow.project_id,
            cycle_id=workflow.cycle_id,
            participants_used=participants_used,
            note=note,
        )
        workflow.script_version = script_version
        self.db.add(workflow)
        self.db.commit()
        logger.info("[%s] Generation complete — strategy=%s llm_calls=%d regenerations=%d script_version=%s", workflow_id, pattern, llm_calls, workflow.regeneration_count, script_version)

    def handle_execution(self, workflow_id: str) -> str:

        # 1. update workflow status
        workflow = self.db.get(Workflow, workflow_id)
        workflow.status = "executing"
        workflow.executed_at = datetime.now(timezone.utc)
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

        # 3. run brane CLI — Popen so handle_abort/handle_dismissed can kill the process
        start_time = time.time()
        proc = subprocess.Popen(
            ["/usr/local/bin/brane", "workflow", "run", "--remote", "central", tmpfile],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _running_processes[workflow_id] = proc
        try:
            stdout, stderr = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        finally:
            _running_processes.pop(workflow_id, None)
            os.unlink(tmpfile)

        # 4. if an external stop (abort/dismissed) killed the process, hand off to that handler
        if proc.returncode < 0 and workflow_id in _aborted_workflows:
            _aborted_workflows.discard(workflow_id)
            return

        # 5. parse result and update status
        duration = int(time.time() - start_time)
        match = re.search(r"Workflow returned value '(.+)'", stdout)
        if proc.returncode == 0 and match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                result = None

            if result:
                workflow.status = "completed"
                self.db.add(workflow)
                self.db.commit()
                self.branehub_service.send_completed(
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
                self.branehub_service.send_completed(
                    project_id=workflow.project_id,
                    cycle_id=workflow.cycle_id,
                    script_version=workflow.script_version,
                    status="completed_failed",
                    result=None,
                    error="Brane output could not be parsed as JSON",
                    duration_seconds=duration,
                )
        else:
            error = stderr or stdout or "brane exited with no output"
            workflow.status = "failed"
            self.db.add(workflow)
            self.db.commit()
            self.branehub_service.send_completed(
                project_id=workflow.project_id,
                cycle_id=workflow.cycle_id,
                script_version=workflow.script_version,
                status="completed_failed",
                result=None,
                error=error,
                duration_seconds=duration,
            )

    def handle_abort(self, workflow_id: str, project_id: int, cycle_id: int, script_version: int):
        workflow = self.db.get(Workflow, workflow_id)
        duration = 0
        if workflow and workflow.executed_at:
            executed_at = workflow.executed_at
            if executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=timezone.utc)
            duration = int((datetime.now(timezone.utc) - executed_at).total_seconds())

        # Signal handle_execution to not call send_completed, then kill the process
        _aborted_workflows.add(workflow_id)
        proc = _running_processes.get(workflow_id)
        if proc and proc.poll() is None:
            proc.terminate()

        if workflow:
            workflow.status = "failed"
            self.db.add(workflow)
            self.db.commit()

        self.branehub_service.send_completed(
            project_id=project_id,
            cycle_id=cycle_id,
            script_version=script_version,
            status="aborted",
            result=None,
            error=None,
            duration_seconds=duration,
            abort_acknowledged=True,
        )

    def _generate_note(self, branescript: str, traceability_report: str) -> str | None:
        if self.llm_service is None:
            return None
        system, user = self.prompt_builder.build_note_prompt(branescript, traceability_report)
        return self.llm_service.complete(system, user)

    def handle_dismissed(self, workflow_id: str):
        # Signal handle_execution to not call send_completed, then kill the process
        _aborted_workflows.add(workflow_id)
        proc = _running_processes.get(workflow_id)
        if proc and proc.poll() is None:
            proc.terminate()

        workflow = self.db.get(Workflow, workflow_id)
        if workflow:
            workflow.status = "failed"
            self.db.add(workflow)
            self.db.commit()
        # Do NOT call send_completed — cycle is abandoned on BraneHub side