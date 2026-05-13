import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.application.package_manager.package_builder import PackageBuilder
from app.application.package_manager.package_generator import PackageGenerator
from app.application.package_manager.package_validator import Issue, PackageAssessment, PackageValidator, Suggestion
from app.domain.package import PackageSource
from app.infrastructure.database import get_db
from app.infrastructure.dtos import (
    ApprovePackageRequest,
    ApprovePackageResponse,
    IssueDTO,
    PackageStatusResponse,
    RegisterPackageRequest,
    RegisterPackageResponse,
    RegeneratePackageRequest,
    RegeneratePackageResponse,
    SuggestionDTO,
)
from app.infrastructure.llm_service import OpenAILlmService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["packages"])

_WORKING_BASE = Path.home() / "brane" / "packages"


def _assessment_to_response(
    project_id: int,
    source_type: str,
    package_name: str,
    assessment: PackageAssessment | None,
    design_note: str | None = None,
) -> RegisterPackageResponse:
    if assessment is None:
        return RegisterPackageResponse(
            project_id=project_id,
            source_type=source_type,
            package_name=package_name,
            assessment_status="pending",
            has_critical_issues=False,
            issues=[],
            suggestions=[],
            assessment_note="Assessment unavailable — LLM service error.",
            design_note=design_note,
        )
    return RegisterPackageResponse(
        project_id=project_id,
        source_type=source_type,
        package_name=package_name,
        assessment_status=assessment.status,
        has_critical_issues=assessment.has_critical_issues,
        issues=[IssueDTO(**vars(i)) for i in assessment.issues],
        suggestions=[SuggestionDTO(**vars(s)) for s in assessment.suggestions],
        assessment_note=assessment.assessment_note,
        design_note=design_note,
    )


def _parse_package_name(container_yml: str) -> str | None:
    for line in container_yml.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _assessment_from_json(raw: str) -> PackageAssessment | None:
    try:
        data = json.loads(raw)
        return PackageAssessment(
            status=data.get("status", "suitable"),
            issues=[Issue(**i) for i in data.get("issues", [])],
            suggestions=[Suggestion(**s) for s in data.get("suggestions", [])],
            assessment_note=data.get("assessment_note", ""),
        )
    except Exception:
        return None


@router.post("/{project_id}/register", status_code=200, response_model=RegisterPackageResponse)
def register_package(
    project_id: int,
    request: RegisterPackageRequest,
    db: Session = Depends(get_db),
):
    existing = db.get(PackageSource, project_id)
    if existing and existing.build_status == "built":
        assessment = _assessment_from_json(existing.llm_assessment) if existing.llm_assessment else None
        return _assessment_to_response(project_id, existing.source_type, existing.package_name, assessment)

    llm = OpenAILlmService()

    if request.source_type == "generate":
        if not request.computation_description:
            raise HTTPException(status_code=400, detail="computation_description required for source_type='generate'")

        package = PackageGenerator(llm).generate(
            study_objective=request.study_objective,
            computation_description=request.computation_description,
            data_types=request.data_types,
        )
        if package is None:
            raise HTTPException(status_code=502, detail="Package generation failed — LLM service error")

        assessment = PackageValidator(llm).validate(package.python_code, package.container_yml, request.study_objective)

        row = PackageSource(
            project_id=project_id,
            source_type="generated",
            study_objective=request.study_objective,
            python_code=package.python_code,
            container_yml=package.container_yml,
            package_name=package.package_name,
            llm_assessment=json.dumps({
                "status": assessment.status if assessment else "pending",
                "issues": [vars(i) for i in assessment.issues] if assessment else [],
                "suggestions": [vars(s) for s in assessment.suggestions] if assessment else [],
                "assessment_note": assessment.assessment_note if assessment else "",
                "design_note": package.design_note,
            }),
            assessment_status="pending",
        )
        db.merge(row)
        db.commit()
        return _assessment_to_response(project_id, "generated", package.package_name, assessment, design_note=package.design_note)

    elif request.source_type == "upload":
        if not request.python_code or not request.container_yml:
            raise HTTPException(status_code=400, detail="python_code and container_yml required for source_type='upload'")

        package_name = _parse_package_name(request.container_yml) or f"project_{project_id}_package"
        assessment = PackageValidator(llm).validate(request.python_code, request.container_yml, request.study_objective)

        row = PackageSource(
            project_id=project_id,
            source_type="uploaded",
            study_objective=request.study_objective,
            python_code=request.python_code,
            container_yml=request.container_yml,
            package_name=package_name,
            llm_assessment=json.dumps({
                "status": assessment.status if assessment else "pending",
                "issues": [vars(i) for i in assessment.issues] if assessment else [],
                "suggestions": [vars(s) for s in assessment.suggestions] if assessment else [],
                "assessment_note": assessment.assessment_note if assessment else "",
            }),
            assessment_status="pending",
        )
        db.merge(row)
        db.commit()
        return _assessment_to_response(project_id, "uploaded", package_name, assessment)

    else:
        raise HTTPException(status_code=400, detail="source_type must be 'generate' or 'upload'")


@router.get("/{project_id}/package", status_code=200, response_model=PackageStatusResponse)
def get_package(project_id: int, db: Session = Depends(get_db)):
    row = db.get(PackageSource, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="No package registered for this project")
    return PackageStatusResponse(**row.model_dump())


@router.post("/{project_id}/package/approve", status_code=200, response_model=ApprovePackageResponse)
def approve_package(
    project_id: int,
    request: ApprovePackageRequest,
    db: Session = Depends(get_db),
):
    row = db.get(PackageSource, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="No package registered for this project")

    no_edits = not request.updated_python_code and not request.updated_container_yml
    if row.build_status == "built" and no_edits:
        return ApprovePackageResponse(success=True, image_name=row.package_name, build_output="Already built")

    if request.updated_python_code:
        row.python_code = request.updated_python_code
    if request.updated_container_yml:
        row.container_yml = request.updated_container_yml

    working_dir = _WORKING_BASE / f"project_{project_id}" / row.package_name
    working_dir.mkdir(parents=True, exist_ok=True)
    container_yml_path = working_dir / "container.yml"
    (working_dir / f"{row.package_name}.py").write_text(row.python_code)
    container_yml_path.write_text(row.container_yml)

    result = PackageBuilder().build(working_dir, container_yml_path)

    if result.success:
        row.build_status = "built"
        row.assessment_status = "approved"
        row.working_dir = str(working_dir)
        row.built_at = datetime.now(timezone.utc)
        row.approved_at = datetime.now(timezone.utc)
        db.add(row)
        db.commit()
        return ApprovePackageResponse(success=True, image_name=result.image_name, build_output="Build succeeded")
    else:
        row.build_status = "failed"
        db.add(row)
        db.commit()
        return ApprovePackageResponse(success=False, error=result.stderr)


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
    row.assessment_status = "pending"
    db.add(row)
    db.commit()

    return RegeneratePackageResponse(
        python_code=package.python_code,
        container_yml=package.container_yml,
        design_note=package.design_note,
    )
