import logging
import re
from dataclasses import dataclass

from app.application.prompts import (
    PACKAGE_GENERATOR_SCHEMA,
    PACKAGE_GENERATOR_SYSTEM,
    PACKAGE_GENERATOR_USER,
)
from app.infrastructure.llm_service import LlmService

logger = logging.getLogger(__name__)


@dataclass
class GeneratedPackage:
    package_name: str
    python_filename: str
    local_function: str
    combine_function: str
    finalize_function: str
    python_code: str
    container_yml: str
    design_note: str


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:40] or "federated_package"


class PackageGenerator:
    def __init__(self, llm_service: LlmService):
        self._llm = llm_service

    def generate(
        self,
        study_objective: str,
        computation_description: str,
        data_types: list[str] | None = None,
        package_name: str | None = None,
    ) -> GeneratedPackage | None:
        package_name = package_name or _slugify(study_objective)
        local_function = "compute_local"
        combine_function = "combine_results"
        finalize_function = "finalize"
        python_filename = f"{package_name}.py"

        user_prompt = PACKAGE_GENERATOR_USER.format(
            study_objective=study_objective,
            computation_description=computation_description,
            data_types=", ".join(data_types) if data_types else "unspecified",
            package_name=package_name,
            local_function=local_function,
            combine_function=combine_function,
            finalize_function=finalize_function,
            python_filename=python_filename,
        )

        result = self._llm.complete_structured(
            system_prompt=PACKAGE_GENERATOR_SYSTEM,
            user_prompt=user_prompt,
            schema=PACKAGE_GENERATOR_SCHEMA,
        )

        if result is None:
            logger.error("PackageGenerator: LLM returned None")
            return None

        return GeneratedPackage(
            package_name=package_name,
            python_filename=python_filename,
            local_function=local_function,
            combine_function=combine_function,
            finalize_function=finalize_function,
            python_code=result["python_code"],
            container_yml=result["container_yml"],
            design_note=result["design_note"],
        )
