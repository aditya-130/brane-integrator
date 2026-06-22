import logging
import re
from app.domain.config import IntegratorConfig
from app.application.workflow_generation.policy_interpreter import InterpretedWorkflow
from app.application.utils.prompts import LLM_GENERATOR_SYSTEM, LLM_GENERATOR_USER, LLM_GENERATOR_RETRY_SUFFIX
from app.infrastructure.llm_service import LlmService

logger = logging.getLogger(__name__)


class LlmGenerator:
    """
    LLM-driven BraneScript generator.
    Generates complete BraneScript from scratch via a single LLM call.
    Validates the result and retries once if validation fails.
    """

    def __init__(self, llm_service: LlmService):
        self.llm_service = llm_service
        self.llm_calls_made = 0

    def generate(self, config: IntegratorConfig, interpreted: InterpretedWorkflow, container_yml: str | None = None) -> str:
        from app.application.workflow_generation.validator import Validator

        self.llm_calls_made = 0
        system = LLM_GENERATOR_SYSTEM
        user = self._build_user_prompt(config, interpreted, container_yml)

        logger.info("LlmGenerator: sending first prompt to LLM (model call #1)")
        raw = self.llm_service.complete(system, user)
        self.llm_calls_made += 1

        if not raw:
            raise ValueError("LlmGenerator: LLM returned no output")

        branescript = self._extract_branescript(raw)
        logger.debug("LlmGenerator: extracted branescript (%d lines)", len(branescript.splitlines()))

        validator = Validator()
        result = validator.validate(branescript, config, interpreted)

        if not result.passed:
            failed = [r for r in result.rules if not r.passed]
            failures = "\n".join(f"- {r.rule}: {r.message}" for r in failed)
            logger.warning("LlmGenerator: first attempt failed validation, retrying. Failures:\n%s", failures)

            retry_user = user + LLM_GENERATOR_RETRY_SUFFIX.format(failures=failures)

            logger.info("LlmGenerator: sending retry prompt to LLM (model call #2)")
            raw = self.llm_service.complete(system, retry_user)
            self.llm_calls_made += 1

            if not raw:
                raise ValueError("LlmGenerator: LLM returned no output on retry")

            branescript = self._extract_branescript(raw)
            logger.info("LlmGenerator: retry complete — total llm_calls_made=%d", self.llm_calls_made)
        else:
            logger.info("LlmGenerator: first attempt passed validation — llm_calls_made=%d", self.llm_calls_made)

        return branescript

    def _build_user_prompt(self, config: IntegratorConfig, interpreted: InterpretedWorkflow, container_yml: str | None = None) -> str:
        participants_lines = []
        for i, p in enumerate(interpreted.participants, start=1):
            tags = ", ".join(p.tag_annotations) if p.tag_annotations else "none"
            participants_lines.append(
                f"{i}. Node: {p.brane_node}, Dataset: {p.dataset_name}, Tags: {tags}"
            )
        participants_block = "\n".join(participants_lines)

        wf_tags_block = "\n".join(interpreted.wf_tags) if interpreted.wf_tags else "none"

        container_yml_block = f"\nPackage container.yml (use this to understand exact function signatures and argument counts):\n```yaml\n{container_yml}\n```\n" if container_yml else ""

        finalize_line = f"\nFinalize function (call once on coordinator after all combines): {config.workflow.finalize_function}" if config.workflow.finalize_function else ""

        return LLM_GENERATOR_USER.format(
            package=config.workflow.package,
            local_function=config.workflow.local_function,
            combine_function=config.workflow.combine_function,
            finalize_function_line=finalize_line,
            coordinator_node=config.workflow.coordinator_node,
            participants_block=participants_block,
            wf_tags_block=wf_tags_block,
            container_yml_block=container_yml_block,
        )

    def _extract_branescript(self, raw: str) -> str:
        # Strip markdown code fences if the LLM wrapped the output
        fenced = re.sub(r"^```[\w]*\n?", "", raw.strip(), flags=re.MULTILINE)
        fenced = re.sub(r"```$", "", fenced.strip(), flags=re.MULTILINE)
        return fenced.strip()
