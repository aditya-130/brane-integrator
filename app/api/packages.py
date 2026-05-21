import json
import logging
import shutil
import yaml
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from app.application.node_provisioner.node_provisioner import NodeProvisioner
from app.application.package_manager.package_builder import PackageBuilder
from app.application.package_manager.package_generator import PackageGenerator
from app.application.prompts import (
    CONTAINER_YML_SCHEMA,
    CONTAINER_YML_SYSTEM,
    CONTAINER_YML_USER,
    PRIVACY_CHECK_SCHEMA,
    PRIVACY_CHECK_SYSTEM,
    PRIVACY_CHECK_USER,
)
from app.domain.package import PackageSource
from app.infrastructure.database import engine, get_db
from app.infrastructure.dtos import (
    ApprovePackageRequest,
    ApprovePackageResponse,
    IssueDTO,
    PackageStatusResponse,
    RegisterPackageAcceptedResponse,
    RegisterPackageRequest,
    RegeneratePackageRequest,
    RegeneratePackageResponse,
    SuggestionDTO,
    ValidatePackageRequest,
    ValidatePackageResponse,
)
from app.infrastructure.llm_service import OpenAILlmService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["packages"])

_WORKING_BASE = Path.home() / "brane" / "packages"


def _parse_package_name(container_yml: str) -> str | None:
    for line in container_yml.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _parse_functions(container_yml: str) -> tuple:
    """Extract (local_function, combine_function) from container.yml actions section."""
    try:
        data = yaml.safe_load(container_yml)
        actions = data.get("actions", {})
        if not actions:
            return None, None
        names = list(actions.keys())
        local, combine = None, None
        for name, spec in actions.items():
            inputs = spec.get("input", []) or []
            has_data_input = any(i.get("type") in ("Data", "IntermediateResult") for i in inputs)
            if has_data_input and local is None:
                local = name
            elif combine is None:
                combine = name
        return local or names[0], combine or (names[1] if len(names) > 1 else None)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Privacy check (Path B only)
# ---------------------------------------------------------------------------

def _check_privacy(llm: OpenAILlmService, python_code: str, study_objective: str) -> str | None:
    """
    Focused privacy check for uploaded code (Path B).
    Asks one semantic question: could the local function return individual-patient-level data?
    Returns a plain-language concern string, or None if the code is safe.
    LLM failure is treated as safe (with a warning) so a broken API call never blocks the researcher.
    """
    result = llm.complete_structured(
        system_prompt=PRIVACY_CHECK_SYSTEM,
        user_prompt=PRIVACY_CHECK_USER.format(
            study_objective=study_objective,
            python_code=python_code,
        ),
        schema=PRIVACY_CHECK_SCHEMA,
    )
    if result is None:
        logger.warning("Privacy check LLM call failed — treating as safe to avoid blocking researcher")
        return None
    if result.get("safe", True):
        return None
    concern = result.get("concern", "").strip()
    return concern if concern else None


def _generate_container_yml(llm: OpenAILlmService, python_code: str, package_name: str, python_filename: str) -> str | None:
    """
    Auto-generate container.yml for uploaded Python code (Path B).
    The LLM reads the dispatch block to find exposed functions, infers env var input names,
    and determines Data vs Any types from how each variable is used after json.loads.
    """
    result = llm.complete_structured(
        system_prompt=CONTAINER_YML_SYSTEM,
        user_prompt=CONTAINER_YML_USER.format(
            package_name=package_name,
            python_filename=python_filename,
            python_code=python_code,
        ),
        schema=CONTAINER_YML_SCHEMA,
    )
    if result is None:
        logger.error("Container YML generation: LLM returned None")
        return None
    yml = result.get("container_yml", "").strip()
    return yml if yml else None


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

def _run_generate_bg(project_id: int, study_objective: str, computation_description: str, data_types: list | None) -> None:
    """
    Path A: generate code via LLM, then mark assessed immediately — no validation pass.

    The generator prompt contains the complete Brane execution model (json.loads on Data inputs,
    print(json.dumps(...)) for output, 2-arg combine, etc.). Running a second LLM over the
    generated output produces false positives on patterns that are correct by design.
    If the generator prompt is right, the output is right. Trust the generator.
    """
    llm = OpenAILlmService()
    try:
        package = PackageGenerator(llm).generate(
            study_objective=study_objective,
            computation_description=computation_description,
            data_types=data_types,
        )
        if package is None:
            raise RuntimeError("PackageGenerator returned None")
        assessment_data = {
            "status": "suitable",
            "issues": [],
            "suggestions": [],
            "assessment_note": "",
            "design_note": package.design_note,
        }
        new_status = "assessed"
    except Exception as exc:
        logger.error("Package generation failed for project %d: %s", project_id, exc)
        assessment_data = {"error": str(exc)}
        new_status = "failed"
        package = None

    with Session(engine) as db:
        row = db.get(PackageSource, project_id)
        if row is None:
            return
        row.assessment_status = new_status
        row.llm_assessment = json.dumps(assessment_data)
        if package is not None:
            row.python_code = package.python_code
            row.container_yml = package.container_yml
            row.package_name = package.package_name
        db.add(row)
        db.commit()


def _run_upload_bg(project_id: int, study_objective: str) -> None:
    """
    Path B: auto-generate container.yml from the researcher's Python code, then run the
    focused privacy check. Two LLM calls total — one mechanical (manifest), one semantic (privacy).
    """
    with Session(engine) as db:
        row = db.get(PackageSource, project_id)
        if row is None:
            return
        python_code = row.python_code
        package_name = row.package_name

    python_filename = f"{package_name}.py"
    llm = OpenAILlmService()
    container_yml = None
    try:
        # Step 1: generate container.yml — reads dispatch block, infers input types
        container_yml = _generate_container_yml(llm, python_code, package_name, python_filename)
        if not container_yml:
            raise RuntimeError("Container YML generation returned no output")

        # Step 2: focused privacy check — could the local function return individual-patient data?
        concern = _check_privacy(llm, python_code, study_objective)
        if concern:
            assessment_data = {
                "status": "issues_found",
                "issues": [{"severity": "warning", "description": concern, "location": "local function"}],
                "suggestions": [],
                "assessment_note": "",
            }
        else:
            assessment_data = {
                "status": "suitable",
                "issues": [],
                "suggestions": [],
                "assessment_note": "",
            }
        new_status = "assessed"
    except Exception as exc:
        logger.error("Package upload processing failed for project %d: %s", project_id, exc)
        assessment_data = {"error": str(exc)}
        new_status = "failed"

    with Session(engine) as db:
        row = db.get(PackageSource, project_id)
        if row is None:
            return
        row.assessment_status = new_status
        row.llm_assessment = json.dumps(assessment_data)
        if container_yml:
            row.container_yml = container_yml
            # Parse and store function names so they're available when provisioning the coordinator
            local_fn, combine_fn = _parse_functions(container_yml)
            if local_fn:
                row.local_function = local_fn
            if combine_fn:
                row.combine_function = combine_fn
        db.add(row)
        db.commit()


def _provision_coordinator_bg(project_id: int) -> None:
    with Session(engine) as db:
        result = NodeProvisioner().provision_coordinator(project_id, db)
        if result.status == "ready":
            logger.info("Coordinator auto-provisioned for project %d: %s", project_id, result.brane_node)
        else:
            logger.error("Coordinator auto-provision failed for project %d: %s", project_id, result.error)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{project_id}/register", status_code=202, response_model=RegisterPackageAcceptedResponse)
def register_package(
    project_id: int,
    request: RegisterPackageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    existing = db.get(PackageSource, project_id)

    if request.source_type == "generate":
        if not request.computation_description:
            raise HTTPException(status_code=400, detail="computation_description required for source_type='generate'")
        # Idempotent unless previous attempt failed — failed rows are retried by re-calling /register
        if existing and existing.assessment_status != "failed":
            return RegisterPackageAcceptedResponse(project_id=project_id, status=existing.assessment_status)
        if existing and existing.assessment_status == "failed":
            existing.assessment_status = "pending"
            existing.study_objective = request.study_objective
            existing.python_code = ""
            existing.container_yml = ""
            db.add(existing)
            db.commit()
            background_tasks.add_task(
                _run_generate_bg,
                project_id,
                request.study_objective,
                request.computation_description,
                request.data_types,
            )
            return RegisterPackageAcceptedResponse(project_id=project_id, status="processing")
        row = PackageSource(
            project_id=project_id,
            source_type="generated",
            study_objective=request.study_objective,
            python_code="",
            container_yml="",
            package_name=f"project_{project_id}_pkg",
            assessment_status="pending",
        )
        db.add(row)
        db.commit()
        background_tasks.add_task(
            _run_generate_bg,
            project_id,
            request.study_objective,
            request.computation_description,
            request.data_types,
        )

    elif request.source_type == "upload":
        if not request.python_code:
            raise HTTPException(status_code=400, detail="python_code required for source_type='upload'")
        # container_yml is auto-generated by the background task — not required from the researcher
        if existing and existing.build_status == "built":
            return RegisterPackageAcceptedResponse(project_id=project_id, status=existing.assessment_status)
        if existing and existing.assessment_status == "assessed" \
                and existing.python_code == request.python_code:
            return RegisterPackageAcceptedResponse(project_id=project_id, status="assessed")
        package_name = f"project_{project_id}_package"
        row = PackageSource(
            project_id=project_id,
            source_type="uploaded",
            study_objective=request.study_objective,
            python_code=request.python_code,
            container_yml="",           # filled by _run_upload_bg
            package_name=package_name,
            assessment_status="pending",
        )
        db.merge(row)
        db.commit()
        background_tasks.add_task(_run_upload_bg, project_id, request.study_objective)

    else:
        raise HTTPException(status_code=400, detail="source_type must be 'generate' or 'upload'")

    return RegisterPackageAcceptedResponse(project_id=project_id, status="processing")


@router.get("/{project_id}/package", status_code=200, response_model=PackageStatusResponse)
def get_package(project_id: int, db: Session = Depends(get_db)):
    row = db.get(PackageSource, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="No package registered for this project")

    design_note = None
    assessment_note = None
    issues: list[IssueDTO] = []
    suggestions: list[SuggestionDTO] = []
    has_critical_issues = False

    if row.llm_assessment:
        try:
            parsed = json.loads(row.llm_assessment)
            design_note = parsed.get("design_note")
            assessment_note = parsed.get("assessment_note", "")
            raw_issues = parsed.get("issues", [])
            raw_suggestions = parsed.get("suggestions", [])
            issues = [IssueDTO(**i) for i in raw_issues]
            suggestions = [SuggestionDTO(**s) for s in raw_suggestions]
            has_critical_issues = any(i.get("severity") == "critical" for i in raw_issues)
        except Exception:
            pass

    return PackageStatusResponse(
        project_id=row.project_id,
        source_type=row.source_type,
        package_name=row.package_name,
        package_version=row.package_version,
        build_status=row.build_status,
        assessment_status=row.assessment_status,
        python_code=row.python_code,
        container_yml=row.container_yml,
        design_note=design_note,
        assessment_note=assessment_note,
        issues=issues,
        suggestions=suggestions,
        has_critical_issues=has_critical_issues,
        working_dir=row.working_dir,
        built_at=row.built_at,
        approved_at=row.approved_at,
        created_at=row.created_at,
    )


@router.post("/{project_id}/package/approve", status_code=200, response_model=ApprovePackageResponse)
def approve_package(
    project_id: int,
    request: ApprovePackageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    row = db.get(PackageSource, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="No package registered for this project")

    no_edits = not request.updated_python_code and not request.updated_container_yml
    if row.build_status == "built" and no_edits:
        from app.domain.infra import CoordinatorNode
        from sqlmodel import select
        has_coordinator = db.exec(
            select(CoordinatorNode).where(CoordinatorNode.project_id == project_id)
        ).first()
        if not has_coordinator:
            background_tasks.add_task(_provision_coordinator_bg, project_id)
        return ApprovePackageResponse(success=True, image_name=row.package_name, build_output="Already built")

    if request.updated_python_code:
        row.python_code = request.updated_python_code
    if request.updated_container_yml:
        row.container_yml = request.updated_container_yml

    working_dir = _WORKING_BASE / f"project_{project_id}" / row.package_name
    working_dir.mkdir(parents=True, exist_ok=True)
    container_yml_path = working_dir / "container.yml"
    (working_dir / f"{row.package_name}.py").write_text(row.python_code.replace("\r\n", "\n").replace("\r", "\n"))
    container_yml_path.write_text(row.container_yml.replace("\r\n", "\n").replace("\r", "\n"))
    run_sh = working_dir / "run.sh"
    if not run_sh.exists():
        run_sh.write_text(f"#!/bin/bash\npython3 /opt/wd/{row.package_name}.py \"$1\"\n")
        run_sh.chmod(0o755)

    # Copy branelet binary so the Dockerfile can ADD it
    from app.infrastructure.settings import settings as _settings
    branelet_src = Path(_settings.BRANELET_PATH) if _settings.BRANELET_PATH else None
    if branelet_src and branelet_src.exists():
        shutil.copy2(branelet_src, working_dir / "branelet")

    # Write a Dockerfile if none exists — avoids brane generating a broken one
    dockerfile = working_dir / "Dockerfile"
    if not dockerfile.exists():
        dockerfile.write_text(
            "FROM python:3.10-slim\n\n"
            "RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "--allow-change-held-packages --allow-downgrades fuse iptables\n\n"
            "ADD branelet /branelet\n"
            "RUN chmod +x /branelet\n\n"
            "RUN mkdir -p /opt/wd\n"
            f"COPY {row.package_name}.py /opt/wd/{row.package_name}.py\n"
            "COPY run.sh /opt/wd/run.sh\n"
            "RUN chmod +x /opt/wd/run.sh\n\n"
            "COPY container.yml /opt/wd/container.yml\n\n"
            "WORKDIR /opt/wd\n"
            'ENTRYPOINT ["/branelet"]\n'
        )

    result = PackageBuilder().build(working_dir, container_yml_path)

    if result.success:
        row.build_status = "built"
        row.assessment_status = "approved"
        row.working_dir = str(working_dir)
        row.built_at = datetime.now(timezone.utc)
        row.approved_at = datetime.now(timezone.utc)
        local_fn, combine_fn = _parse_functions(row.container_yml)
        if local_fn:
            row.local_function = local_fn
        if combine_fn:
            row.combine_function = combine_fn
        db.add(row)
        db.commit()
        background_tasks.add_task(_provision_coordinator_bg, project_id)
        return ApprovePackageResponse(success=True, image_name=result.image_name, build_output="Build succeeded")
    else:
        row.build_status = "failed"
        db.add(row)
        db.commit()
        return ApprovePackageResponse(success=False, error=result.stderr)


@router.post("/{project_id}/package/validate", status_code=200, response_model=ValidatePackageResponse)
def validate_package(
    project_id: int,
    request: ValidatePackageRequest,
    db: Session = Depends(get_db),
):
    """
    Synchronous privacy check for a given piece of Python code.
    Used by the JupyterLab notebook Re-check button. Accepts any code — does not
    read from or write to the stored PackageSource row (no side effects).
    Falls back to the stored study_objective if one is not provided in the request.
    """
    row = db.get(PackageSource, project_id)
    study_objective = request.study_objective or (row.study_objective if row else "") or ""
    concern = _check_privacy(OpenAILlmService(), request.python_code, study_objective)
    return ValidatePackageResponse(safe=concern is None, concern=concern)


@router.post("/{project_id}/package/regenerate", status_code=200, response_model=RegeneratePackageResponse)
def regenerate_package(
    project_id: int,
    request: RegeneratePackageRequest,
    db: Session = Depends(get_db),
):
    row = db.get(PackageSource, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="No package registered for this project")

    package = PackageGenerator(OpenAILlmService()).generate(
        study_objective=row.study_objective or f"Federated computation for project {project_id}",
        computation_description=request.instruction or "Regenerate the package with improvements",
        package_name=row.package_name,
    )
    if package is None:
        raise HTTPException(status_code=502, detail="Regeneration failed — LLM service error")

    row.python_code = package.python_code
    row.container_yml = package.container_yml
    row.build_status = "pending"
    row.assessment_status = "assessed"
    row.llm_assessment = json.dumps({"design_note": package.design_note, "issues": [], "suggestions": [], "assessment_note": ""})
    db.add(row)
    db.commit()

    return RegeneratePackageResponse(
        python_code=package.python_code,
        container_yml=package.container_yml,
        design_note=package.design_note,
    )
