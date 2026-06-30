import sys
import os
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from app.domain.config import IntegratorConfig, ProjectBlock, WorkflowSpec, ParticipantPolicy
from app.application.workflow_generation.policy_interpreter import PolicyInterpreter
from app.application.workflow_generation.strategy.template_generator import TemplateGenerator
from app.application.workflow_generation.strategy.llm_generator import LlmGenerator
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

FIXTURES_PATH = os.path.join(os.path.dirname(__file__), "../fixtures/scenarios.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")
N_RUNS = 5


def load_scenario(scenario_id):
    scenario_path = os.path.join(
        os.path.dirname(__file__), f"../../app/mockdata/scenario_{scenario_id}.json"
    )
    with open(scenario_path) as f:
        raw = json.load(f)
    with open(FIXTURES_PATH) as f:
        fix = json.load(f)[str(scenario_id)]

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
    return config, fix


def jaccard_lines(script_a, script_b):
    set_a = set(l.strip() for l in script_a.splitlines() if l.strip())
    set_b = set(l.strip() for l in script_b.splitlines() if l.strip())
    union = set_a | set_b
    return round(len(set_a & set_b) / len(union), 4) if union else 1.0


def run_template(config, interpreted):
    start = time.time()
    script = TemplateGenerator().generate(config, interpreted)
    latency_ms = int((time.time() - start) * 1000)
    result = Validator().validate(script, config, interpreted)
    return script, result.passed, latency_ms


def run_llm(config, interpreted, llm_service, container_yml=None):
    gen = LlmGenerator(llm_service)
    start = time.time()
    script = gen.generate(config, interpreted, container_yml=container_yml)
    latency_ms = int((time.time() - start) * 1000)
    result = Validator().validate(script, config, interpreted)
    failed_rules = [r.rule for r in result.rules if not r.passed]
    return script, result.passed, latency_ms, gen.llm_calls_made, failed_rules


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    scripts_dir = os.path.join(RESULTS_DIR, "generated_scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    has_llm = bool(os.environ.get("OPENAI_API_KEY"))
    if not has_llm:
        print("WARNING: OPENAI_API_KEY not set — skipping LLM generator measurements")

    llm_service = None
    if has_llm:
        from app.infrastructure.llm_service import OpenAILlmService
        llm_service = OpenAILlmService()

    interpreter = PolicyInterpreter()
    per_scenario = {}
    template_validity, template_latencies, llm_validity, llm_latencies = [], [], [], []
    llm_calls_all, regen_counts, jaccards = [], [], []
    rule_failure_dist = {}

    for scenario_id in range(1, 9):
        print(f"\nScenario {scenario_id}:")
        config, fix = load_scenario(scenario_id)
        interpreted = interpreter.interpret(config)

        # Template generator (single run — deterministic)
        t_script, t_passed, t_latency = run_template(config, interpreted)
        template_validity.append(1 if t_passed else 0)
        template_latencies.append(t_latency)
        print(f"  Template: passed={t_passed} latency={t_latency}ms")
        with open(os.path.join(scripts_dir, f"s{scenario_id}_template.bs"), "w") as f:
            f.write(t_script)

        scenario_result = {
            "template": {"passed": t_passed, "latency_ms": t_latency},
            "llm": None,
        }

        if has_llm:
            run_scripts, run_passed, run_calls, run_latencies_s = [], [], [], []
            run_failed_rules = []

            for run in range(N_RUNS):
                script, passed, lat, calls, failed = run_llm(config, interpreted, llm_service)
                run_scripts.append(script)
                run_passed.append(passed)
                run_calls.append(calls)
                run_latencies_s.append(lat)
                run_failed_rules.extend(failed)
                for rule in failed:
                    rule_failure_dist[rule] = rule_failure_dist.get(rule, 0) + 1

            first_pass_rate = round(sum(1 for c in run_calls if c == 1) / N_RUNS, 4)
            avg_latency = int(sum(run_latencies_s) / N_RUNS)
            avg_calls = round(sum(run_calls) / N_RUNS, 2)
            avg_regen = round(sum(c - 1 for c in run_calls) / N_RUNS, 2)

            pairs = [(i, j) for i in range(N_RUNS) for j in range(i + 1, N_RUNS)]
            jac_scores = [jaccard_lines(run_scripts[i], run_scripts[j]) for i, j in pairs]
            avg_jac = round(sum(jac_scores) / len(jac_scores), 4) if jac_scores else 1.0

            llm_validity.append(first_pass_rate)
            llm_latencies.append(avg_latency)
            llm_calls_all.append(avg_calls)
            regen_counts.append(avg_regen)
            jaccards.append(avg_jac)

            print(f"  LLM: first_pass={first_pass_rate} latency={avg_latency}ms calls={avg_calls} regen={avg_regen} jaccard={avg_jac}")

            with open(os.path.join(scripts_dir, f"s{scenario_id}_llm_run1.bs"), "w") as f:
                f.write(run_scripts[0])

            scenario_result["llm"] = {
                "first_pass_rate": first_pass_rate,
                "avg_latency_ms": avg_latency,
                "avg_llm_calls": avg_calls,
                "avg_regeneration_count": avg_regen,
                "jaccard_consistency": avg_jac,
                "failed_rules_in_runs": run_failed_rules,
            }

        per_scenario[str(scenario_id)] = scenario_result

    n = len(range(1, 9))
    output = {
        "template": {
            "first_pass_validity": round(sum(template_validity) / n, 4),
            "avg_latency_ms": int(sum(template_latencies) / n),
        },
        "llm": {
            "first_pass_validity": round(sum(llm_validity) / len(llm_validity), 4) if llm_validity else None,
            "avg_latency_ms": int(sum(llm_latencies) / len(llm_latencies)) if llm_latencies else None,
            "avg_llm_calls": round(sum(llm_calls_all) / len(llm_calls_all), 2) if llm_calls_all else None,
            "avg_regeneration_count": round(sum(regen_counts) / len(regen_counts), 2) if regen_counts else None,
            "jaccard_consistency": round(sum(jaccards) / len(jaccards), 4) if jaccards else None,
            "rule_failure_distribution": rule_failure_dist,
        } if has_llm else None,
        "per_scenario": per_scenario,
    }

    out_path = os.path.join(RESULTS_DIR, "comparison_table.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nM3.1 Template first-pass validity: {output['template']['first_pass_validity']}")
    if has_llm and output["llm"]:
        print(f"M3.1 LLM first-pass validity:      {output['llm']['first_pass_validity']}")
        print(f"M3.5 LLM avg calls:                {output['llm']['avg_llm_calls']}")
        print(f"M3.4 LLM avg regenerations:        {output['llm']['avg_regeneration_count']}")
        print(f"M3.8 LLM Jaccard consistency:      {output['llm']['jaccard_consistency']}")
        print(f"M3.3 Rule failure distribution:    {rule_failure_dist}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
