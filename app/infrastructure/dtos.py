from pydantic import BaseModel
from typing import List, Dict, Any

class ParticipantNodeMappingRequest(BaseModel):
    user_id: int
    brane_node: str

class ProjectConfigRequest (BaseModel):
    project_id: int 
    coordinator_node: str
    package: str
    local_function: str
    combine_function: str

class GenerateWorkflowRequest(BaseModel):
    schema_version: str
    project_id: int
    cycle_id: int
    triggered_at: str