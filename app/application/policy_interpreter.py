from app.domain.config import IntegratorConfig, InterpretedParticipant, InterpretedWorkflow

PARTICIPANT_REGISTRY = {
    "brane_node": lambda v: f'#[on("{v}")]',
    "dataset_name": lambda v: f'new Data {{ name := "{v}" }}',
    "identifiability": lambda v: f'#[tag("identifiability.{v}")]',
}

WORKFLOW_REGISTRY = {
    "data_sensitivity": lambda v: f'#![wf_tag("sensitivity.{v}")]',
}

PARTICIPANT_SKIP_FIELDS = {"user_id"}
WF_SKIP_FIELDS = {"project_id", "study_objective", "legal_basis"}


class PolicyInterpreter:
    def interpret(self, config: IntegratorConfig) -> InterpretedWorkflow:
        wf_tags = []
        for field, value in config.project.model_dump().items():
            if field in WF_SKIP_FIELDS or value is None:
                continue
            if field in WORKFLOW_REGISTRY:
                wf_tags.append(WORKFLOW_REGISTRY[field](value))

        participants = []
        for participant in config.participants:
            on_annotation = None
            dataset_name = None
            tag_annotations = []
            flagged = []

            for field, value in participant.model_dump().items():
                if field in PARTICIPANT_SKIP_FIELDS or value is None:
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