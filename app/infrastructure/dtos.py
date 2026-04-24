from pydantic import BaseModel
from typing import List, Dict, Any

class ParticipantNodeMappingRequest(BaseModel):
    participant_id: str
    brane_node: str

class ProjectConfigRequest (BaseModel):
    project_id: str 
    coordinator_node: str
    package: str
    local_function: str
    combine_function: str

class ProjectDTO(BaseModel):
    study_objective: str
    data_sensitivity_level: str
    legal_basis_for_processing: str


class ParticipantDTO(BaseModel):
    participant_id: str
    dataset_name: str
    onboarding_answers: Dict[str, Any]
    data_format_answers: Dict[str, Any]


class GenerateWorkflowRequest(BaseModel):
    project_id: str
    project: ProjectDTO
    accepted_participants: List[ParticipantDTO]