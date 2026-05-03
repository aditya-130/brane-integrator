from typing import List, Optional
from pydantic import BaseModel


class ProjectBlock(BaseModel):
    project_id: int
    study_objective: str
    data_sensitivity: str
    legal_basis: str


class WorkflowSpec(BaseModel):
    package: str
    local_function: str
    combine_function: str
    coordinator_node: str


class ParticipantPolicy(BaseModel):
    user_id: int
    brane_node: str
    dataset_name: str
    identifiability: Optional[str] = None


class IntegratorConfig(BaseModel):
    project: ProjectBlock
    workflow: WorkflowSpec
    participants: List[ParticipantPolicy]


class InterpretedParticipant(BaseModel):
    brane_node: str
    dataset_name: str
    on_annotation: str
    tag_annotations: List[str] = []
    flagged: List[str] = []


class InterpretedWorkflow(BaseModel):
    wf_tags: List[str] = []
    participants: List[InterpretedParticipant]

class RuleResult(BaseModel):
    rule: str
    passed: bool
    message: Optional[str] = None


class ValidationResult(BaseModel):
    passed: bool
    rules: list[RuleResult]