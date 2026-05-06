import json
from app.domain.config import ExtractedClaim, IntegratorConfig, ParticipantPolicy
from app.infrastructure.llm_service import LlmService
from app.application.prompt_builder import PromptBuilder

FREE_TEXT_FIELDS = ["privacy_legal_notes", "data_provenance", "source_of_truth"]


class FreeTextExtractor:
    def __init__(self):
        self._prompt_builder = PromptBuilder()

    def extract(self, config: IntegratorConfig, llm_service: LlmService | None) -> IntegratorConfig:
        if llm_service is None:
            return config
        updated = [self._process_participant(p, llm_service) for p in config.participants]
        return config.model_copy(update={"participants": updated})

    def _process_participant(self, participant: ParticipantPolicy, llm_service: LlmService) -> ParticipantPolicy:
        inputs = {
            field: getattr(participant, field)
            for field in FREE_TEXT_FIELDS
            if getattr(participant, field)
        }
        if not inputs:
            return participant
        claims = self._call_llm(inputs, llm_service)
        return participant.model_copy(update={"extracted_claims": claims})

    def _call_llm(self, inputs: dict[str, str], llm_service: LlmService) -> list[ExtractedClaim]:
        system, user = self._prompt_builder.build_extraction_prompt(inputs)
        print(f"[FreeTextExtractor] sending to LLM — fields: {list(inputs.keys())}")
        try:
            raw = llm_service.complete(system, user)
            print(f"[FreeTextExtractor] LLM result received: {raw!r}")
            if not raw:
                return []
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
            claims = [ExtractedClaim(**item) for item in data if isinstance(item, dict)]
            print(f"[FreeTextExtractor] extracted {len(claims)} claim(s): {claims}")
            return claims
        except Exception as e:
            print(f"[FreeTextExtractor] failed: {e}")
            return []
