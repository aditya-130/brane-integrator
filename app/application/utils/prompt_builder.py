from app.application.utils.prompts import (
    BRANE_CONTEXT,
    BRANESCRIPT_CONSTRUCTS,
    NOTE_GENERATION_ROLE,
    NOTE_GENERATION_TASK,
    NOTE_GENERATION_USER,
    TRACEABILITY_REPORT_EXPLANATION,
    POLICY_FIELDS_REFERENCE,
    FREE_TEXT_EXTRACTION_TASK,
    FREE_TEXT_EXTRACTION_USER,
)

_SEP = "\n\n"


class PromptBuilder:
    def build_note_prompt(self, branescript: str, traceability_report: str) -> tuple[str, str]:
        system = _SEP.join([
            NOTE_GENERATION_ROLE,
            BRANE_CONTEXT,
            BRANESCRIPT_CONSTRUCTS,
            TRACEABILITY_REPORT_EXPLANATION,
            NOTE_GENERATION_TASK,
        ])
        user = NOTE_GENERATION_USER.format(
            branescript=branescript,
            traceability_report=traceability_report,
        )
        return system, user

    def build_extraction_prompt(self, participant_inputs: dict[str, str]) -> tuple[str, str]:
        system = _SEP.join([
            BRANE_CONTEXT,
            BRANESCRIPT_CONSTRUCTS,
            POLICY_FIELDS_REFERENCE,
            FREE_TEXT_EXTRACTION_TASK,
        ])
        formatted_inputs = "\n".join(
            f'- {field}: "{value}"' for field, value in participant_inputs.items()
        )
        user = FREE_TEXT_EXTRACTION_USER.format(free_text_inputs=formatted_inputs)
        return system, user
