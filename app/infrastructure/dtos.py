from pydantic import BaseModel
from typing import List, Dict, Any, Optional

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