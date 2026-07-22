import logging
from concurrent.futures import ThreadPoolExecutor

from app.application.utils.prompts import FREE_TEXT_EXTRACTION_SCHEMA
from app.domain.config import ExtractedClaim, IntegratorConfig, ParticipantPolicy
from app.infrastructure.llm_service import LlmService
from app.application.utils.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

FREE_TEXT_FIELDS = ["privacy_legal_notes", "data_provenance", "source_of_truth"]


class FreeTextExtractor:
    def __init__(self):
        self._prompt_builder = PromptBuilder()

    def extract(self, config: IntegratorConfig, llm_service: LlmService | None) -> IntegratorConfig:
        if llm_service is None:
            return config
        # Gap 4 fix: each participant's extraction is independent — run in parallel
        with ThreadPoolExecutor() as executor:
            updated = list(executor.map(
                lambda p: self._process_participant(p, llm_service),
                config.participants,
            ))
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
        logger.info("Sending to LLM — fields: %s", list(inputs.keys()))

        # Gap 2 fix: use structured outputs — guarantees valid JSON, eliminates silent parse failures
        result = llm_service.complete_structured(system, user, FREE_TEXT_EXTRACTION_SCHEMA)
        if result is None:
            logger.warning("Free-text extraction: LLM returned None — treating as no claims")
            return []

        raw_claims = result.get("claims", [])

        high = sum(1 for c in raw_claims if isinstance(c, dict) and c.get("confidence") == "high")
        medium = sum(1 for c in raw_claims if isinstance(c, dict) and c.get("confidence") == "medium")
        low = sum(1 for c in raw_claims if isinstance(c, dict) and c.get("confidence") == "low")
        logger.info("Raw claims from LLM: %d total — high=%d medium=%d low=%d", len(raw_claims), high, medium, low)

        # Gap 3 fix: discard low-confidence claims — weak guesses should not generate BraneScript constructs
        claims = [
            ExtractedClaim(**c)
            for c in raw_claims
            if isinstance(c, dict) and c.get("confidence") != "low"
        ]

        filtered = len(raw_claims) - len(claims)
        if filtered:
            logger.info("Extracted %d claim(s), filtered %d low-confidence", len(claims), filtered)
        else:
            logger.info("Extracted %d claim(s)", len(claims))

        return claims
