import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from app.domain.config import IntegratorConfig, ProjectBlock, WorkflowSpec, ParticipantPolicy
from app.application.workflow_generation.policy_interpreter import PolicyInterpreter
from app.application.workflow_generation.validator import Validator

FI_DIR = os.path.join(os.path.dirname(__file__), "../fault_injection")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")

EXPECTED = {
    "FI-1.bs":  ["import_present"],
    "FI-2.bs":  ["return_present"],
    "FI-3.bs":  ["on_annotation_participant-3"],
    "FI-4.bs":  ["combine_pinned_to_coordinator"],
    "FI-5.bs":  ["wf_tag_present"],
    "FI-6.bs":  ["tag_annotation_participant-1"],
    "FI-7.bs":  ["dataset_ref_participant-1", "dataset_ref_participant-3"],
    "FI-8.bs":  ["combine_exactly_two_args"],
    "FI-9.bs":  ["package_registered", "function_registered"],
    "FI-10.bs": ["on_annotation_participant-3", "tag_annotation_participant-1"],
}


def make_config():
    config = IntegratorConfig(
        project=ProjectBlock(
            project_id=1,
            data_sensitivity="High",
            legal_basis="consent",
        ),
        workflow=WorkflowSpec(
            package="fed_mean",
            local_function="compute_local",
            combine_function="combine_results",
            coordinator_node="coordinator-1",
            finalize_function="finalize",
        ),
        participants=[
            ParticipantPolicy(
                user_id=1,
                brane_node="participant-1",
                dataset_name="cancer_age_s1_p1",
                identifiability="Pseudonymized",
                jurisdictions=["EU"],
            ),
            ParticipantPolicy(
                user_id=3,
                brane_node="participant-3",
                dataset_name="cancer_age_s1_p3",
                identifiability="Anonymized",
                jurisdictions=["EU"],
            ),
        ],
    )
    interpreted = PolicyInterpreter().interpret(config)
    return config, interpreted


def rule_matches(failed_rules, expected_rules):
    for er in expected_rules:
        for fr in failed_rules:
            if fr == er or fr.startswith(er) or er.startswith(fr):
                return True
    return False


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    config, interpreted = make_config()
    validator = Validator()
    results = []

    for filename in sorted(EXPECTED.keys()):
        path = os.path.join(FI_DIR, filename)
        with open(path) as f:
            branescript = f.read()

        validation = validator.validate(branescript, config, interpreted)
        failed_rules = [r.rule for r in validation.rules if not r.passed]
        expected_rules = EXPECTED[filename]
        caught = rule_matches(failed_rules, expected_rules)

        results.append({
            "file": filename,
            "expected_rules": expected_rules,
            "failed_rules": failed_rules,
            "caught": caught,
        })
        print(f"{'CAUGHT' if caught else 'MISSED':6s}  {filename}  failed={failed_rules}")

    caught_count = sum(1 for r in results if r["caught"])
    catch_rate = round(caught_count / len(results), 4)

    output = {
        "summary": {"total": len(results), "caught": caught_count, "missed": len(results) - caught_count},
        "catch_rate": catch_rate,
        "results": results,
    }

    out_path = os.path.join(RESULTS_DIR, "fault_injection_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nM2.3 catch rate: {catch_rate:.1%} ({caught_count}/{len(results)})")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
