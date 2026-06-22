from typing import List, Optional
from pydantic import BaseModel
from app.domain.config import IntegratorConfig

PARTICIPANT_REGISTRY = {
    "brane_node": lambda v: f'#[on("{v}")]',
    "dataset_name": lambda v: f'new Data {{ name := "{v}" }}',
    "identifiability": lambda v: f'#[tag("identifiability.{v}")]',
}

WORKFLOW_REGISTRY = {
    "data_sensitivity": lambda v: f'#![wf_tag("sensitivity.{v}")]',
    "legal_basis": lambda v: f'#![wf_tag("legal_basis.{v}")]',
}

# Skipped entirely — not a policy signal at the BraneScript level
PARTICIPANT_SKIP_FIELDS = {
    "user_id",
    "jurisdictions",        # aggregated at workflow level below
    "privacy_legal_notes",  # handled by FreeTextExtractor (RQ3)
    "data_provenance",      # handled by FreeTextExtractor (RQ3)
    "source_of_truth",      # handled by FreeTextExtractor (RQ3)
    "extracted_claims",     # processed separately below
}

# Skipped entirely — informational only, no construct and no flag
WF_SKIP_FIELDS = {"project_id", "study_objective"}


class InterpretedParticipant(BaseModel):
    brane_node: str
    dataset_name: str
    on_annotation: str
    tag_annotations: List[str] = []
    flagged: List[str] = []


class InterpretedWorkflow(BaseModel):
    wf_tags: List[str] = []
    participants: List[InterpretedParticipant]


class PolicyInterpreter:
    def interpret(self, config: IntegratorConfig) -> InterpretedWorkflow:
        # Iterate WORKFLOW_REGISTRY directly so canonical order (data_sensitivity → legal_basis)
        # is explicit rather than a side effect of Pydantic's model_dump() field order
        project_data = config.project.model_dump()
        wf_tags = []
        for field, fn in WORKFLOW_REGISTRY.items():
            value = project_data.get(field)
            if value:
                wf_tags.append(fn(value))

        # Jurisdictions: collect from all participants, deduplicate, emit one wf_tag per unique value
        # These always follow data_sensitivity and legal_basis in the tag block
        seen_jurisdictions: set[str] = set()
        for p in config.participants:
            for j in (p.jurisdictions or []):
                if j not in seen_jurisdictions:
                    seen_jurisdictions.add(j)
                    wf_tags.append(f'#![wf_tag("jurisdiction.{j}")]')

        participants = []
        for participant in config.participants:
            on_annotation = None
            dataset_name = None
            tag_annotations = []
            flagged = []

            for field, value in participant.model_dump().items():
                if field in PARTICIPANT_SKIP_FIELDS or not value:
                    continue
                if field in PARTICIPANT_REGISTRY:
                    construct = PARTICIPANT_REGISTRY[field](value)
                    if field == "brane_node":
                        on_annotation = construct
                    elif field == "dataset_name":
                        dataset_name = construct
                    else:
                        tag_annotations.append(construct)
                else:
                    flagged.append(field)

            # Process claims extracted from free-text fields (RQ3)
            for claim in participant.extracted_claims:
                if claim.policy_field not in PARTICIPANT_REGISTRY:
                    continue
                construct = PARTICIPANT_REGISTRY[claim.policy_field](claim.policy_value)
                if claim.policy_field == "brane_node":
                    on_annotation = on_annotation or construct
                elif claim.policy_field == "dataset_name":
                    dataset_name = dataset_name or construct
                elif construct not in tag_annotations:
                    tag_annotations.append(construct)

            participants.append(
                InterpretedParticipant(
                    brane_node=participant.brane_node,
                    dataset_name=dataset_name,
                    on_annotation=on_annotation,
                    tag_annotations=tag_annotations,
                    flagged=flagged,
                )
            )

        return InterpretedWorkflow(wf_tags=wf_tags, participants=participants)