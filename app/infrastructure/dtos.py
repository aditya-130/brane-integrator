from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Package Manager
# ---------------------------------------------------------------------------

class RegisterPackageRequest(BaseModel):
    source_type: str                                    # "generate" | "upload"
    study_objective: str
    computation_description: Optional[str] = None      # required for source_type="generate"
    data_types: Optional[List[str]] = None
    python_code: Optional[str] = None                  # required for source_type="upload"
    container_yml: Optional[str] = None                # required for source_type="upload"


class IssueDTO(BaseModel):
    severity: str       # "critical" | "warning"
    description: str
    location: str


class SuggestionDTO(BaseModel):
    description: str
    before: str
    after: str


class RegisterPackageResponse(BaseModel):
    project_id: int
    source_type: str
    package_name: str
    assessment_status: str
    has_critical_issues: bool
    issues: List[IssueDTO]
    suggestions: List[SuggestionDTO]
    assessment_note: str
    design_note: Optional[str] = None


class PackageStatusResponse(BaseModel):
    project_id: int
    source_type: str
    package_name: str
    package_version: str
    build_status: str
    assessment_status: str
    python_code: str
    container_yml: str
    llm_assessment: Optional[str] = None
    working_dir: Optional[str] = None
    built_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class ApprovePackageRequest(BaseModel):
    updated_python_code: Optional[str] = None
    updated_container_yml: Optional[str] = None


class ApprovePackageResponse(BaseModel):
    success: bool
    image_name: Optional[str] = None
    build_output: Optional[str] = None
    error: Optional[str] = None


class RegeneratePackageRequest(BaseModel):
    instruction: Optional[str] = None


class RegeneratePackageResponse(BaseModel):
    python_code: str
    container_yml: str
    design_note: str


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

class ParticipantNodeMappingRequest(BaseModel):
    user_id: int
    brane_node: str


class ProjectConfigRequest(BaseModel):
    project_id: int
    coordinator_node: str
    package: str
    local_function: str
    combine_function: str


class GenerateWorkflowRequest(BaseModel):
    schema_version: str
    cycle_id: int
    triggered_at: str


class RunWorkflowRequest(BaseModel):
    schema_version: str
    cycle_id: int
    script_version: int
    decided_at: str
    decided_by: str


class RejectWorkflowRequest(BaseModel):
    schema_version: str
    cycle_id: int
    script_version: int
    rejection_reason: str
    decided_at: str
    decided_by: str


class AbortWorkflowRequest(BaseModel):
    schema_version: str
    project_id: int
    cycle_id: int
    script_version: int
    reason: str
    requested_at: str
    requested_by: str


class DismissedWorkflowRequest(BaseModel):
    schema_version: str
    project_id: int
    cycle_id: int
    script_version: Optional[int] = None
    reason: Optional[str] = None
    dismissed_at: str
    dismissed_by: str
    dismissed_by_role: str
