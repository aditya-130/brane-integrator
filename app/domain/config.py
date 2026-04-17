from pydantic import BaseModel
from typing import List


class ProjectBlock(BaseModel):
    project_id: str
    objective: str
    data_sensitivity: str  # Low | Medium | High
    legal_basis: str


class WorkflowSpec(BaseModel):
    package: str
    local_function: str
    combine_function: str
    coordinator_node: str
    invocation_pattern: str  # "string_id" | "data_object"


class DataFormat(BaseModel):
    storage_types: List[str]
    file_formats: List[str]
    database_types: List[str]


class ParticipantPolicy(BaseModel):
    brane_node: str
    dataset_name: str
    data_locality: str          # local_only | flexible
    purpose: str                # research | clinical_care | secondary_use
    lawfulness_basis: str       # consent | public_interest | ...
    identifiability: str        # Anonymized | Pseudonymized | Identifiable
    network_policy: str         # Yes | No | ProxyOnly | VPNOnly | Restricted
    audit_logging: str          # Yes | No | Conditional
    model_updates_allowed: str  # Yes | AfterDifferentialPrivacy | No
    requires_unlearning: str    # Yes | No | CaseByCase
    requires_per_round_approval: bool
    data_format: DataFormat


class IntegratorConfig(BaseModel):
    project: ProjectBlock
    workflow: WorkflowSpec
    participants: List[ParticipantPolicy]