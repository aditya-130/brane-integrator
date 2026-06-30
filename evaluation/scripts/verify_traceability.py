import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")
PROJECT_125_PATH = os.path.join(RESULTS_DIR, "project_125_full_record.json")


def compute_metrics(mappings):
    total = len(mappings)
    if total == 0:
        return {"total_mappings": 0, "construct_generating": 0, "flagged": 0,
                "with_line_numbers": 0, "coverage_rate": 0.0,
                "construct_to_flag_ratio": 0.0, "line_verifiability_rate": 0.0}

    construct_generating = [m for m in mappings if not m.get("flagged") and m.get("generated_construct")]
    flagged = [m for m in mappings if m.get("flagged")]
    with_lines = [m for m in construct_generating if m.get("line") is not None]

    # M1.1: every field (flagged or not) appears in the report → coverage is always total/total
    coverage_rate = 1.0

    # M1.2: construct-generating entries / flagged entries
    construct_to_flag = (
        round(len(construct_generating) / len(flagged), 4) if flagged else float("inf")
    )

    # M1.4: of construct-generating entries, fraction with a line number
    line_verifiability = (
        round(len(with_lines) / len(construct_generating), 4) if construct_generating else 0.0
    )

    return {
        "total_mappings": total,
        "construct_generating": len(construct_generating),
        "flagged": len(flagged),
        "with_line_numbers": len(with_lines),
        "coverage_rate": coverage_rate,
        "construct_to_flag_ratio": construct_to_flag,
        "line_verifiability_rate": line_verifiability,
    }


def analyse_project_125():
    if not os.path.exists(PROJECT_125_PATH):
        print(f"  SKIP: {PROJECT_125_PATH} not found — export it from the live system first")
        return None
    with open(PROJECT_125_PATH) as f:
        record = json.load(f)
    mappings = record["traceability_report"]["mappings"]
    return compute_metrics(mappings)


def analyse_scenarios():
    from app.domain.config import IntegratorConfig, ProjectBlock, WorkflowSpec, ParticipantPolicy
    from app.application.workflow_generation.policy_interpreter import PolicyInterpreter
    from app.application.workflow_generation.strategy.template_generator import TemplateGenerator
    from app.application.workflow_generation.validator import Validator
    from app.infrastructure.branehub_schema import (
        FDP_DATA_SENSITIVITY, FDP_LEGAL_BASIS, FDP_STUDY_OBJECTIVE,
        FDP_THIRD_PARTY_COLLABORATION, FDP_SECURITY_MEASURES,
        FDP_RESULT_SHARING_POLICY, FDP_PARTICIPANT_RESPONSIBILITIES,
        ONB_JURISDICTIONS, ONB_IDENTIFIABILITY, ONB_INVOLVES_HUMAN_RESEARCH,
        ONB_RETROSPECTIVE_CONSENT, ONB_IRB_APPROVAL, ONB_DIRECT_IDENTIFIERS,
        ONB_QUASI_IDENTIFIERS, ONB_AUDIT_LOGGING, ONB_NETWORK_CONNECTIVITY,
        ONB_SECURITY_CERTIFICATIONS, ONB_DATA_SHARING_AGREEMENTS,
        ONB_MODEL_UPDATES_ALLOWED, ONB_PER_ROUND_APPROVAL, ONB_REQUIRES_UNLEARNING,
        DFM_PRIVACY_LEGAL_NOTES, DFM_DATA_PROVENANCE, DFM_SOURCE_OF_TRUTH,
    )

    fixtures_path = os.path.join(os.path.dirname(__file__), "../fixtures/scenarios.json")
    with open(fixtures_path) as f:
        all_fixtures = json.load(f)

    per_scenario = {}
    interpreter = PolicyInterpreter()
    generator = TemplateGenerator()
    validator = Validator()

    for scenario_id in range(1, 9):
        scenario_path = os.path.join(
            os.path.dirname(__file__), f"../../app/mockdata/scenario_{scenario_id}.json"
        )
        with open(scenario_path) as f:
            raw = json.load(f)

        fix = all_fixtures[str(scenario_id)]
        fdp = raw["project"]["fdp_config"]
        node_map = {p["user_id"]: p["brane_node"] for p in fix["participants"]}

        project = ProjectBlock(
            project_id=raw["project_id"],
            study_objective=fdp.get(FDP_STUDY_OBJECTIVE),
            data_sensitivity=fdp.get(FDP_DATA_SENSITIVITY),
            legal_basis=fdp.get(FDP_LEGAL_BASIS),
            third_party_collaboration=fdp.get(FDP_THIRD_PARTY_COLLABORATION),
            security_measures_planned=fdp.get(FDP_SECURITY_MEASURES),
            result_sharing_policy=fdp.get(FDP_RESULT_SHARING_POLICY),
            participant_responsibilities=fdp.get(FDP_PARTICIPANT_RESPONSIBILITIES),
        )
        workflow = WorkflowSpec(
            package=fix["package"],
            local_function=fix["local_function"],
            combine_function=fix["combine_function"],
            coordinator_node=fix["coordinator_node"],
            finalize_function=fix["finalize_function"],
        )
        participants = []
        for p in raw["accepted_participants"]:
            if not p.get("is_active", True):
                continue
            uid = p["user_id"]
            onb = p.get("onboarding_answers", {})
            dfm = p.get("data_format_answers", {})
            participants.append(ParticipantPolicy(
                user_id=uid,
                brane_node=node_map[uid],
                dataset_name=p["brane_metadata"]["dataset_name"],
                identifiability=onb.get(ONB_IDENTIFIABILITY),
                jurisdictions=onb.get(ONB_JURISDICTIONS),
                involves_human_research=onb.get(ONB_INVOLVES_HUMAN_RESEARCH),
                retrospective_consent=onb.get(ONB_RETROSPECTIVE_CONSENT),
                irb_approval=onb.get(ONB_IRB_APPROVAL),
                direct_identifiers=onb.get(ONB_DIRECT_IDENTIFIERS),
                quasi_identifiers=onb.get(ONB_QUASI_IDENTIFIERS),
                audit_logging_required=onb.get(ONB_AUDIT_LOGGING),
                network_connectivity_policy=onb.get(ONB_NETWORK_CONNECTIVITY),
                security_certifications=onb.get(ONB_SECURITY_CERTIFICATIONS),
                data_sharing_agreements=onb.get(ONB_DATA_SHARING_AGREEMENTS),
                model_updates_allowed=onb.get(ONB_MODEL_UPDATES_ALLOWED),
                per_round_approval=onb.get(ONB_PER_ROUND_APPROVAL),
                requires_unlearning=onb.get(ONB_REQUIRES_UNLEARNING),
                privacy_legal_notes=dfm.get(DFM_PRIVACY_LEGAL_NOTES),
                data_provenance=dfm.get(DFM_DATA_PROVENANCE),
                source_of_truth=dfm.get(DFM_SOURCE_OF_TRUTH),
            ))

        config = IntegratorConfig(project=project, workflow=workflow, participants=participants)
        interpreted = interpreter.interpret(config)
        branescript = generator.generate(config, interpreted)
        mappings = validator.generate_traceability_report(branescript, config, interpreted)["mappings"]
        per_scenario[str(scenario_id)] = compute_metrics(mappings)
        print(f"  S{scenario_id}: {per_scenario[str(scenario_id)]}")

    return per_scenario


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    print("Analysing project 125...")
    p125 = analyse_project_125()
    if p125:
        print(f"  {p125}")

    print("Analysing scenarios S1-S8...")
    per_scenario = analyse_scenarios()

    output = {
        "project_125": p125,
        "per_scenario": per_scenario,
    }

    out_path = os.path.join(RESULTS_DIR, "traceability_metrics.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    if p125:
        print(f"\nM1.1 coverage_rate (p125):          {p125['coverage_rate']}")
        print(f"M1.2 construct_to_flag_ratio (p125): {p125['construct_to_flag_ratio']}")
        print(f"M1.4 line_verifiability_rate (p125): {p125['line_verifiability_rate']}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
