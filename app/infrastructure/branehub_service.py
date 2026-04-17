import json
from pathlib import Path
from app.domain.config import (
    IntegratorConfig, ProjectBlock, WorkflowSpec,
    ParticipantPolicy, DataFormat
)

MOCKDATA_DIR = Path(__file__).parent.parent / "mockdata"


class BraneHubService:

    def get_integrator_config(self, project_id: str) -> IntegratorConfig | None:
        raw_data = self._fetch_project(project_id)
        if raw_data is None:
            return None

        fdp_config = raw_data["fdp_config"]

        return IntegratorConfig(
            project=self._build_project_block(project_id, fdp_config),
            workflow=WorkflowSpec(**raw_data["workflow"]),
            participants=[
                self._build_participant_policy(participant, fdp_config)
                for participant in raw_data["accepted_participants"]
            ],
        )

    def _fetch_project(self, project_id: str) -> dict | None:
        path = MOCKDATA_DIR / f"{project_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def _build_project_block(self, project_id: str, fdp_config: dict) -> ProjectBlock:
        return ProjectBlock(
            project_id=project_id,
            objective=fdp_config["study_objective"],
            data_sensitivity=fdp_config["data_sensitivity_level"],
            legal_basis=fdp_config["legal_basis_for_processing"],
        )

    def _build_participant_policy(self, participant: dict, fdp_config: dict) -> ParticipantPolicy:
        onboarding = participant["onboarding_answers"]
        data_format = participant["data_format_answers"]

        return ParticipantPolicy(
            brane_node=participant["brane_node"],
            dataset_name=participant["dataset_name"],
            data_locality="local_only",
            purpose=fdp_config["study_objective"],
            lawfulness_basis=fdp_config["legal_basis_for_processing"],
            identifiability=onboarding["identifiability.processingLevel"],
            data_format=DataFormat(
                storage_types=[data_format["storage.location"]],
                file_formats=data_format["storage.file_format"],
                database_types=[],
            ),
            network_policy=onboarding["securityInfrastructure.networkConnectionPolicy"],
            audit_logging=onboarding["securityInfrastructure.auditLoggingRequired"],
            model_updates_allowed=onboarding["dataGovernance.modelUpdatesAllowed"],
            requires_unlearning=onboarding["retention.requires_unlearning"],
            requires_per_round_approval=onboarding["dataGovernance.requiresPerRoundApproval"],
        )