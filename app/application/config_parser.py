from app.domain.infra import ParticipantNodeMap, ProjectConfig
from sqlmodel import Session, select
from app.domain.config import (
    IntegratorConfig,
    ParticipantPolicy,
    ProjectBlock,
    WorkflowSpec,
)


class ConfigParser:
    def __init__(self, db_session: Session):
        self._db_session = db_session

    def parse(self, raw: dict) -> IntegratorConfig:
        return IntegratorConfig(
            project=self._build_project_block(raw),
            workflow=self._build_workflow_spec(raw),
            participants=self._build_participant_policies(raw),
        )

    def _build_project_block(self, raw: dict) -> ProjectBlock:
        fdp = raw["project"]["fdp_config"]
        return ProjectBlock(
            project_id=raw["project_id"],
            study_objective=fdp.get("study_objective"),
            data_sensitivity=fdp.get("data_sensitivity_level"),
            legal_basis=fdp.get("legal_basis_for_processing"),
        )

    def _build_workflow_spec(self, raw: dict) -> WorkflowSpec:
        project_id = raw["project_id"]
        project_config = self._db_session.exec(
            select(ProjectConfig).where(ProjectConfig.project_id == project_id)
        ).first()

        if not project_config:
            raise ValueError(f"No ProjectConfig found for project_id={project_id}")

        return WorkflowSpec(
            package=project_config.package,
            local_function=project_config.local_function,
            combine_function=project_config.combine_function,
            coordinator_node=project_config.coordinator_node,
        )

    def _build_participant_policies(self, raw: dict) -> list[ParticipantPolicy]:
        policies = []

        for participant in raw["accepted_participants"]:
            if not participant.get("is_active", True):
                continue

            user_id = participant["user_id"]
            node_mapping = self._db_session.exec(
                select(ParticipantNodeMap).where(ParticipantNodeMap.user_id == user_id)
            ).first()

            if not node_mapping:
                raise ValueError(f"No node mapping found for user_id={user_id}")

            policies.append(
                ParticipantPolicy(
                    user_id=user_id,
                    brane_node=node_mapping.brane_node,
                    dataset_name=participant["brane_metadata"]["dataset_name"],
                    identifiability=participant["onboarding_answers"].get(
                        "identifiability.processingLevel"
                    ),
                )
            )

        return policies