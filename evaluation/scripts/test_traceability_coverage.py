"""
Regression checks for the M1.1 traceability-coverage fix.

Plain-assertion script (no pytest in this project's requirements.txt) — run directly:
    .venv/bin/python3 evaluation/scripts/test_traceability_coverage.py

These exist to prove verify_traceability.py's coverage_rate is a real, sensitive
measurement and not a constant — see EvaluationProcess/final_metrics.md M1.1 note
and the 2026-07-22 fix to validator.py / verify_traceability.py.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from app.domain.config import IntegratorConfig, ProjectBlock, WorkflowSpec, ParticipantPolicy, ExtractedClaim
from app.application.workflow_generation.policy_interpreter import PolicyInterpreter
from app.application.workflow_generation.validator import Validator
from app.application.workflow_generation.strategy.template_generator import TemplateGenerator
from verify_traceability import expected_field_keys, covered_field_keys, compute_metrics

interpreter = PolicyInterpreter()
generator = TemplateGenerator()
validator = Validator()

PASS = []
FAIL = []


def check(name, condition):
    (PASS if condition else FAIL).append(name)
    print(f"{'PASS' if condition else 'FAIL'} — {name}")


def make_config(participants_kwargs, **project_kwargs):
    project = ProjectBlock(project_id=1, data_sensitivity="High", legal_basis="Consent", **project_kwargs)
    workflow = WorkflowSpec(package="fed_mean", local_function="compute_local",
                             combine_function="combine_results", coordinator_node="coordinator-1",
                             finalize_function="finalize")
    participants = [ParticipantPolicy(**kw) for kw in participants_kwargs]
    return IntegratorConfig(project=project, workflow=workflow, participants=participants)


def run(config):
    interpreted = interpreter.interpret(config)
    branescript = generator.generate(config, interpreted)
    mappings = validator.generate_traceability_report(branescript, config, interpreted)["mappings"]
    return mappings, compute_metrics(mappings, config)


# --- Test 1: removing an expected mapping drops coverage below 1.0 -----------------
config = make_config([
    dict(user_id=1, brane_node="participant-1", dataset_name="ds1", identifiability="Pseudonymized"),
])
mappings, metrics = run(config)
check("baseline coverage_rate == 1.0 before tampering", metrics["coverage_rate"] == 1.0)

tampered = [m for m in mappings if m["policy_field"] != "identifiability"]
tampered_metrics = compute_metrics(tampered, config)
check("removing an expected mapping makes coverage_rate < 1.0", tampered_metrics["coverage_rate"] < 1.0)
check("the removed field shows up in missing_field_keys", "participant:1:identifiability" in tampered_metrics["missing_field_keys"])

# --- Test 2: non-empty free-text field with zero extracted claims is still accounted for --
config = make_config([
    dict(user_id=1, brane_node="participant-1", dataset_name="ds1",
         privacy_legal_notes="Some free text the LLM found nothing actionable in.",
         extracted_claims=[]),
])
mappings, metrics = run(config)
ft_mappings = [m for m in mappings if m["policy_field"] == "privacy_legal_notes"]
check("a zero-claim free-text field still produces exactly one mapping entry", len(ft_mappings) == 1)
check("that entry is flagged (not silently dropped)", ft_mappings and ft_mappings[0]["flagged"] is True)
check("'participant:1:privacy_legal_notes' is in expected_field_keys", "participant:1:privacy_legal_notes" in expected_field_keys(config))
check("'participant:1:privacy_legal_notes' is covered despite zero claims", "participant:1:privacy_legal_notes" in covered_field_keys(mappings, config))
check("coverage_rate == 1.0 with the zero-claim field present", metrics["coverage_rate"] == 1.0)

# --- Test 3: empty optional fields are not counted ---------------------------------
config = make_config([
    dict(user_id=1, brane_node="participant-1", dataset_name="ds1", quasi_identifiers=None),
])
keys = expected_field_keys(config)
check("an empty (None) optional field is excluded from expected_field_keys", "participant:1:quasi_identifiers" not in keys)

# --- Test 4: same-named participant fields are distinguished by participant --------
config = make_config([
    dict(user_id=1, brane_node="participant-1", dataset_name="ds1", identifiability="Pseudonymized"),
    dict(user_id=2, brane_node="participant-2", dataset_name="ds2", identifiability="Anonymized"),
])
mappings, metrics = run(config)
keys = expected_field_keys(config)
covered = covered_field_keys(mappings, config)
check("both participants' identifiability keys are distinct in expected_field_keys",
      {"participant:1:identifiability", "participant:2:identifiability"} <= keys)
check("both participants' identifiability keys are independently covered",
      {"participant:1:identifiability", "participant:2:identifiability"} <= covered)

# --- Test 5: construct-generating and flagged fields both count as covered ---------
config = make_config([
    dict(user_id=1, brane_node="participant-1", dataset_name="ds1",
         identifiability="Pseudonymized",  # construct-generating (PARTICIPANT_REGISTRY)
         involves_human_research="Yes"),   # flagged (not in any registry)
])
mappings, metrics = run(config)
covered = covered_field_keys(mappings, config)
check("a construct-generating field counts as covered", "participant:1:identifiability" in covered)
check("a flag-only field counts as covered", "participant:1:involves_human_research" in covered)

# --- Test 6: jurisdictions (list-valued, aggregated) handled per-participant -------
config = make_config([
    dict(user_id=1, brane_node="participant-1", dataset_name="ds1", jurisdictions=["EU", "US"]),
    dict(user_id=2, brane_node="participant-2", dataset_name="ds2", jurisdictions=["EU"]),
])
mappings, metrics = run(config)
keys = expected_field_keys(config)
covered = covered_field_keys(mappings, config)
check("both participants get their own jurisdictions key in expected_field_keys",
      {"participant:1:jurisdictions", "participant:2:jurisdictions"} <= keys)
check("both participants' jurisdictions are covered when all their values are present",
      {"participant:1:jurisdictions", "participant:2:jurisdictions"} <= covered)

# Now drop the "US" jurisdiction mapping only — participant 1 requires EU+US, participant 2 only EU
tampered = [m for m in mappings if not (m["policy_field"] == "jurisdictions" and m["policy_value"] == "US")]
tampered_covered = covered_field_keys(tampered, config)
check("participant 1 (needs US) loses jurisdictions coverage when the US tag is missing",
      "participant:1:jurisdictions" not in tampered_covered)
check("participant 2 (only needs EU) keeps jurisdictions coverage — aggregation is value-based by design",
      "participant:2:jurisdictions" in tampered_covered)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
