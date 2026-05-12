# BraneHub questionnaire field IDs — the external schema contract.
# All keys used to extract answers from BraneHub payloads live here.
# If Mingjiang renames a question ID, update it in one place.

# --- FDP config (Project.fdp_config) ---
FDP_STUDY_OBJECTIVE = "study_objective"
FDP_DATA_SENSITIVITY = "data_sensitivity_level"
FDP_LEGAL_BASIS = "legal_basis_for_processing"
FDP_THIRD_PARTY_COLLABORATION = "third_party_collaboration"
FDP_SECURITY_MEASURES = "security_measures_planned"
FDP_RESULT_SHARING_POLICY = "result_sharing_policy"
FDP_PARTICIPANT_RESPONSIBILITIES = "participant_responsibilities"

# --- Onboarding answers (OnboardingRequest.answers) ---
ONB_JURISDICTIONS = "organization.jurisdictions"
ONB_INVOLVES_HUMAN_RESEARCH = "dataNature.involvesHumanResearch"
ONB_RETROSPECTIVE_CONSENT = "dataNature.retrospectiveConsent"
ONB_IRB_APPROVAL = "ethicalLegal.irbApproval"
ONB_IDENTIFIABILITY = "identifiability.processingLevel"
ONB_DIRECT_IDENTIFIERS = "identifiability.directIdentifiers"
ONB_QUASI_IDENTIFIERS = "identifiability.quasiIdentifiers"
ONB_AUDIT_LOGGING = "securityInfrastructure.auditLoggingRequired"
ONB_NETWORK_CONNECTIVITY = "securityInfrastructure.networkConnectionPolicy"
ONB_SECURITY_CERTIFICATIONS = "securityInfrastructure.securityCertifications"
ONB_DATA_SHARING_AGREEMENTS = "dataGovernance.agreementsExist"
ONB_MODEL_UPDATES_ALLOWED = "dataGovernance.modelUpdatesAllowed"
ONB_PER_ROUND_APPROVAL = "dataGovernance.requiresPerRoundApproval"
ONB_REQUIRES_UNLEARNING = "retentionRevocation.requiresUnlearning"

# --- Data format answers (OnboardingRequest.data_format_answers) ---
DFM_PRIVACY_LEGAL_NOTES = "meta.privacy_legal"
DFM_DATA_PROVENANCE = "meta.provenance"
DFM_SOURCE_OF_TRUTH = "storage.source_of_truth"
