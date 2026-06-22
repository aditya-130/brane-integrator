from sqlmodel import Session, select
from app.domain.infra import ParticipantNodeMap, ProjectConfig
from app.domain.config import (
    IntegratorConfig,
    ParticipantPolicy,
    ProjectBlock,
    WorkflowSpec,
)
from app.infrastructure.branehub_schema import (
    FDP_STUDY_OBJECTIVE,
    FDP_DATA_SENSITIVITY,
    FDP_LEGAL_BASIS,
    FDP_THIRD_PARTY_COLLABORATION,
    FDP_SECURITY_MEASURES,
    FDP_RESULT_SHARING_POLICY,
    FDP_PARTICIPANT_RESPONSIBILITIES,
    ONB_JURISDICTIONS,
    ONB_INVOLVES_HUMAN_RESEARCH,
    ONB_RETROSPECTIVE_CONSENT,
    ONB_IRB_APPROVAL,
    ONB_IDENTIFIABILITY,
    ONB_DIRECT_IDENTIFIERS,
    ONB_QUASI_IDENTIFIERS,
    ONB_AUDIT_LOGGING,
    ONB_NETWORK_CONNECTIVITY,
    ONB_SECURITY_CERTIFICATIONS,
    ONB_DATA_SHARING_AGREEMENTS,
    ONB_MODEL_UPDATES_ALLOWED,
    ONB_PER_ROUND_APPROVAL,
    ONB_REQUIRES_UNLEARNING,
    DFM_PRIVACY_LEGAL_NOTES,
    DFM_DATA_PROVENANCE,
    DFM_SOURCE_OF_TRUTH,
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
            study_objective=fdp.get(FDP_STUDY_OBJECTIVE),
            data_sensitivity=fdp.get(FDP_DATA_SENSITIVITY),
            legal_basis=fdp.get(FDP_LEGAL_BASIS),
            third_party_collaboration=fdp.get(FDP_THIRD_PARTY_COLLABORATION),
            security_measures_planned=fdp.get(FDP_SECURITY_MEASURES),
            result_sharing_policy=fdp.get(FDP_RESULT_SHARING_POLICY),
            participant_responsibilities=fdp.get(FDP_PARTICIPANT_RESPONSIBILITIES),
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
            finalize_function=project_config.finalize_function,
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

            onboarding = participant.get("onboarding_answers", {})
            data_format = participant.get("data_format_answers", {})

            policies.append(
                ParticipantPolicy(
                    user_id=user_id,
                    brane_node=node_mapping.brane_node,
                    dataset_name=participant["brane_metadata"]["dataset_name"],
                    # construct-generating
                    identifiability=onboarding.get(ONB_IDENTIFIABILITY),
                    jurisdictions=onboarding.get(ONB_JURISDICTIONS),
                    # flag-only structured fields
                    involves_human_research=onboarding.get(ONB_INVOLVES_HUMAN_RESEARCH),
                    retrospective_consent=onboarding.get(ONB_RETROSPECTIVE_CONSENT),
                    irb_approval=onboarding.get(ONB_IRB_APPROVAL),
                    direct_identifiers=onboarding.get(ONB_DIRECT_IDENTIFIERS),
                    quasi_identifiers=onboarding.get(ONB_QUASI_IDENTIFIERS),
                    audit_logging_required=onboarding.get(ONB_AUDIT_LOGGING),
                    network_connectivity_policy=onboarding.get(ONB_NETWORK_CONNECTIVITY),
                    security_certifications=onboarding.get(ONB_SECURITY_CERTIFICATIONS),
                    data_sharing_agreements=onboarding.get(ONB_DATA_SHARING_AGREEMENTS),
                    model_updates_allowed=onboarding.get(ONB_MODEL_UPDATES_ALLOWED),
                    per_round_approval=onboarding.get(ONB_PER_ROUND_APPROVAL),
                    requires_unlearning=onboarding.get(ONB_REQUIRES_UNLEARNING),
                    # free-text fields for FreeTextExtractor
                    privacy_legal_notes=data_format.get(DFM_PRIVACY_LEGAL_NOTES),
                    data_provenance=data_format.get(DFM_DATA_PROVENANCE),
                    source_of_truth=data_format.get(DFM_SOURCE_OF_TRUTH),
                )
            )

        return policies
