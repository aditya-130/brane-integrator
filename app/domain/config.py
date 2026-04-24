from typing import List
from pydantic import BaseModel


class ProjectBlock(BaseModel):
    project_id: str
    study_objective: str
    data_sensitivity: str
    legal_basis: str


class WorkflowSpec(BaseModel):
    package: str
    local_function: str
    combine_function: str
    coordinator_node: str  




class ParticipantPolicy(BaseModel):
    brane_node: str
    dataset_name: str
    identifiability: str
    network_policy: str 
    audit_logging: str  
    model_updates_allowed: str
    requires_unlearning: str  
    requires_per_round_approval: bool
    data_format: str


class IntegratorConfig(BaseModel):
    project: ProjectBlock
    workflow: WorkflowSpec
    participants: List[ParticipantPolicy]