from app.domain.config import IntegratorConfig, InterpretedParticipant

POLICY_REGISTRY = {
    "brane_node": lambda v: f'#[on("{v}")]',
}

SKIP_FIELDS = {"dataset_name"}


class PolicyInterpreter:
    def interpret(self, config: IntegratorConfig) -> list[InterpretedParticipant]:
        result = []

        for participant in config.participants:
            fields = participant.model_dump()
            on_annotation = None
            flagged = []

            for field, value in fields.items():
                if field in SKIP_FIELDS:
                    continue

                if field in POLICY_REGISTRY:
                    if field == "brane_node":
                        on_annotation = POLICY_REGISTRY[field](value)
                else:
                    flagged.append(field)

            result.append(
                InterpretedParticipant(
                    brane_node=participant.brane_node,
                    dataset_name=participant.dataset_name,
                    on_annotation=on_annotation,
                    flagged=flagged,
                )
            )

        return result