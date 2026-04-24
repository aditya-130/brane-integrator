from app.domain.infra import ParticipantNodeMap, ProjectConfig
from sqlmodel import Session, select
from app.infrastructure.dtos import GenerateWorkflowRequest
from app.domain.config import (
    IntegratorConfig,
    ParticipantPolicy,
    ProjectBlock,
    WorkflowSpec,
)


class ConfigParser:
    def __init__(self, config: GenerateWorkflowRequest, db_session: Session):
        self.config = config
        self._db_session = db_session

    def parse(self) -> IntegratorConfig:
        return IntegratorConfig(
            project=self._build_project_block(),
            workflow=self._build_workflow_spec(),
            participants=self._build_participant_policies(),
        )

    def _build_project_block(self) -> ProjectBlock:
        project_dto = self.config.project
        return ProjectBlock(
            project_id=self.config.project_id,
            study_objective=project_dto.study_objective,
            data_sensitivity=project_dto.data_sensitivity_level,
            legal_basis=project_dto.legal_basis_for_processing,
        )

    def _build_workflow_spec(self) -> WorkflowSpec:
        statement = select(ProjectConfig).where(
            ProjectConfig.project_id == self.config.project_id
        )
        project_config = self._db_session.exec(statement).first()

        if not project_config:
            raise ValueError(
                f"No ProjectConfig found for project_id={self.config.project_id}"
            )

        return WorkflowSpec(
            package=project_config.package,
            local_function=project_config.local_function,
            combine_function=project_config.combine_function,
            coordinator_node=project_config.coordinator_node,
        )

    def _build_participant_policies(self) -> list[ParticipantPolicy]:
        participant_policies = []

        for participant in self.config.accepted_participants:
            statement = select(ParticipantNodeMap).where(
                ParticipantNodeMap.participant_id == participant.participant_id
            )
            node_mapping = self._db_session.exec(statement).first()

            if not node_mapping:
                raise ValueError(
                    f"No node mapping found for participant {participant.participant_id}"
                )

            participant_policies.append(
                ParticipantPolicy(
                    brane_node=node_mapping.brane_node,
                    dataset_name=participant.dataset_name,
                    identifiability=participant.onboarding_answers.get(
                        "identifiability.processingLevel"
                    ),
                    network_policy=participant.onboarding_answers.get(
                        "securityInfrastructure.networkConnectionPolicy"
                    ),
                    audit_logging=participant.onboarding_answers.get(
                        "securityInfrastructure.auditLoggingRequired"
                    ),
                    model_updates_allowed=participant.onboarding_answers.get(
                        "dataGovernance.modelUpdatesAllowed"
                    ),
                    requires_unlearning=participant.onboarding_answers.get(
                        "retention.requires_unlearning"
                    ),
                    requires_per_round_approval=participant.onboarding_answers.get(
                        "dataGovernance.requiresPerRoundApproval"
                    ),
                    data_format=participant.data_format_answers.get(
                        "storage.file_format"
                    ),
                )
            )

        return participant_policies