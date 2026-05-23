from typing import List, Optional
from pydantic import BaseModel


class ExtractedClaim(BaseModel):
    source_field: str
    policy_field: str
    policy_value: str
    confidence: str = "medium"


class ProjectBlock(BaseModel):
    project_id: int
    study_objective: Optional[str] = None
    data_sensitivity: Optional[str] = None
    legal_basis: Optional[str] = None
    # flag-only fields
    third_party_collaboration: Optional[str] = None
    security_measures_planned: Optional[List[str]] = None
    result_sharing_policy: Optional[str] = None
    participant_responsibilities: Optional[str] = None


class WorkflowSpec(BaseModel):
    package: str
    local_function: str
    combine_function: str
    coordinator_node: str
    finalize_function: Optional[str] = None


class ParticipantPolicy(BaseModel):
    user_id: int
    brane_node: str
    dataset_name: str
    # construct-generating fields
    identifiability: Optional[str] = None
    jurisdictions: Optional[List[str]] = None
    # flag-only structured fields
    involves_human_research: Optional[str] = None
    retrospective_consent: Optional[str] = None
    irb_approval: Optional[str] = None
    direct_identifiers: Optional[str] = None
    quasi_identifiers: Optional[str] = None
    audit_logging_required: Optional[str] = None
    network_connectivity_policy: Optional[str] = None
    security_certifications: Optional[List[str]] = None
    data_sharing_agreements: Optional[str] = None
    model_updates_allowed: Optional[str] = None
    per_round_approval: Optional[str] = None
    requires_unlearning: Optional[str] = None
    # free-text fields (for FreeTextExtractor — RQ3)
    privacy_legal_notes: Optional[str] = None
    data_provenance: Optional[str] = None
    source_of_truth: Optional[str] = None
    # claims extracted from free-text by FreeTextExtractor
    extracted_claims: List[ExtractedClaim] = []


class IntegratorConfig(BaseModel):
    project: ProjectBlock
    workflow: WorkflowSpec
    participants: List[ParticipantPolicy]


