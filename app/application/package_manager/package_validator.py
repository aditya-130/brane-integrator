import logging
from dataclasses import dataclass, field

from app.application.prompts import (
    PACKAGE_VALIDATOR_SCHEMA,
    PACKAGE_VALIDATOR_SYSTEM,
    PACKAGE_VALIDATOR_USER,
)
from app.infrastructure.llm_service import LlmService

logger = logging.getLogger(__name__)


@dataclass
class Issue:
    severity: str   # "critical" | "warning"
    description: str
    location: str


@dataclass
class Suggestion:
    description: str
    before: str
    after: str


@dataclass
class PackageAssessment:
    status: str                         # "suitable" | "issues_found"
    issues: list[Issue] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    assessment_note: str = ""

    @property
    def has_critical_issues(self) -> bool:
        return any(i.severity == "critical" for i in self.issues)


class PackageValidator:
    def __init__(self, llm_service: LlmService):
        self._llm = llm_service

    def validate(
        self,
        python_code: str,
        container_yml: str,
        study_objective: str,
    ) -> PackageAssessment | None:
        user_prompt = PACKAGE_VALIDATOR_USER.format(
            study_objective=study_objective,
            python_code=python_code,
            container_yml=container_yml,
        )

        result = self._llm.complete_structured(
            system_prompt=PACKAGE_VALIDATOR_SYSTEM,
            user_prompt=user_prompt,
            schema=PACKAGE_VALIDATOR_SCHEMA,
        )

        if result is None:
            logger.error("PackageValidator: LLM returned None")
            return None

        issues = [Issue(**i) for i in result.get("issues", [])]
        suggestions = [Suggestion(**s) for s in result.get("suggestions", [])]

        return PackageAssessment(
            status=result["status"],
            issues=issues,
            suggestions=suggestions,
            assessment_note=result.get("assessment_note", ""),
        )
