"""
evaluate_extensibility.py — M3.9: LLM extensibility to novel computation patterns

Demonstrates that LlmGenerator can produce structurally correct BraneScript for a
multi-round federated k-means pattern (2 rounds, 2-input compute_assignments) without
any code changes — only the study_objective and container_yml change. TemplateGenerator
is hardcoded to single-round map-reduce and cannot adapt regardless of the scenario.

No Brane execution. No registered package. Structural analysis only.
Rule 9 (package_registered) is excluded — fed_kmeans is hypothetical.

Custom structural properties checked (not covered by standard 9-rule Validator):
  P1: compute_assignments called exactly N_PARTICIPANTS * N_ROUNDS times
  P2: every compute_assignments call has exactly 2 arguments (data + centroids)
  P3: round 2 calls use the output variable of round 1's aggregate_and_update as centroids arg
"""

import sys
import os
import json
import re
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

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")
N_RUNS = 3
N_PARTICIPANTS = 2
N_ROUNDS = 2

# Hypothetical fed_kmeans package — 2-input compute_assignments is the key difference
# from all existing packages. Template cannot call it correctly (always generates 1 arg).
CONTAINER_YML = """name: fed_kmeans
version: 1.0.0
kind: ecu
base: python:3.10-slim
contributors:
  - name: Brane Integrator
entrypoint:
  kind: task
  exec: run.sh
files:
  - package.py
  - run.sh
actions:
  compute_assignments:
    command:
      args:
        - compute_assignments
    input:
      - name: local_data
        type: Data
      - name: centroids
        type: string
    output:
      - name: output
        type: string
  aggregate_and_update:
    command:
      args:
        - aggregate_and_update
    input:
      - name: result_1
        type: string
      - name: result_2
        type: string
    output:
      - name: output
        type: string"""


def build_kmeans_config() -> IntegratorConfig:
    project = ProjectBlock(
        project_id=9,
        study_objective=(
            "Federated k-means clustering with K=2 rounds. "
            "Round 1: each participant computes local cluster assignments using initial centroids "
            "and reports centroid sums and point counts per cluster. The coordinator aggregates "
            "these to produce updated global centroids. "
            "Round 2: participants repeat the assignment step using the updated centroids from "
            "round 1 as input — NOT the initial centroids. The coordinator aggregates again to "
            "produce the final centroids. "
            "This requires two full rounds of participant computation each followed by coordinator "
            "aggregation. It is NOT a single map-reduce pass."
        ),
        data_sensitivity="High",
        legal_basis="consent",
        third_party_collaboration=None,
        security_measures_planned=None,
        result_sharing_policy="Aggregated results only",
        participant_responsibilities=None,
    )
    workflow = WorkflowSpec(
        package="fed_kmeans",
        local_function="compute_assignments",
        combine_function="aggregate_and_update",
        coordinator_node="coordinator-1",
        finalize_function=None,
    )
    participants = [
        ParticipantPolicy(
            user_id=1,
            brane_node="participant-1",
            dataset_name="kmeans_data_p1",
            identifiability="Pseudonymized",
            jurisdictions=["EU"],
        ),
        ParticipantPolicy(
            user_id=3,
            brane_node="participant-3",
            dataset_name="kmeans_data_p3",
            identifiability="Anonymized",
            jurisdictions=["EU"],
        ),
    ]
    return IntegratorConfig(project=project, workflow=workflow, participants=participants)


def check_structural_properties(branescript: str) -> dict:
    """
    Custom structural checker for multi-round federated patterns.
    The standard 9-rule Validator does not check any of these.
    """
    lines = branescript.splitlines()
    results = {}

    # P1: compute_assignments called N_PARTICIPANTS * N_ROUNDS times
    ca_calls = re.findall(r'\bcompute_assignments\s*\(', branescript)
    expected = N_PARTICIPANTS * N_ROUNDS
    results["P1_round_count"] = {
        "passed": len(ca_calls) == expected,
        "expected": expected,
        "found": len(ca_calls),
        "description": f"compute_assignments called {N_PARTICIPANTS}x{N_ROUNDS}={expected} times (one per participant per round)",
    }

    # P2: every compute_assignments call has exactly 2 arguments
    ca_arg_lists = re.findall(r'\bcompute_assignments\s*\(([^)]+)\)', branescript)
    wrong_arity = [
        s for s in ca_arg_lists
        if len([a.strip() for a in s.split(',') if a.strip()]) != 2
    ]
    results["P2_compute_arity"] = {
        "passed": len(ca_arg_lists) > 0 and len(wrong_arity) == 0,
        "total_calls_found": len(ca_arg_lists),
        "calls_with_wrong_arity": len(wrong_arity),
        "description": "every compute_assignments call has exactly 2 args: (local_data, centroids)",
    }

    # P3: round 2 calls thread centroids from round 1's aggregate_and_update output variable
    # Find the variable assigned by the first aggregate_and_update call
    first_agg = re.search(r'let\s+(\w+)\s*:=\s*aggregate_and_update\s*\(', branescript)
    if first_agg:
        round1_var = first_agg.group(1)
        # Everything after the first aggregate_and_update assignment
        post_agg = branescript[first_agg.end():]
        later_ca_calls = re.findall(r'\bcompute_assignments\s*\(([^)]+)\)', post_agg)
        threaded = any(
            round1_var in [a.strip() for a in call.split(',')]
            for call in later_ca_calls
        )
        results["P3_centroids_threaded"] = {
            "passed": threaded,
            "round1_output_variable": round1_var,
            "later_compute_calls_found": len(later_ca_calls),
            "description": "round 2 compute_assignments calls pass round 1 aggregate_and_update output as centroids argument",
        }
    else:
        results["P3_centroids_threaded"] = {
            "passed": False,
            "round1_output_variable": None,
            "later_compute_calls_found": 0,
            "description": "round 2 compute_assignments calls pass round 1 aggregate_and_update output as centroids argument",
        }

    passed = sum(1 for k, v in results.items() if v["passed"])
    total = len(results)
    results["summary"] = {
        "passed": passed,
        "total": total,
        "score": f"{passed}/{total}",
    }
    return results


def strip_bare_hash_comments(script: str) -> str:
    """Remove bare # comment lines — invalid BraneScript syntax. Only #[ and #![ are valid."""
    lines = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith('#') and not stripped.startswith('#[') and not stripped.startswith('#!['):
            continue
        lines.append(line)
    return '\n'.join(lines)


def run_validator_rules_1_8(branescript: str, config: IntegratorConfig, interpreted) -> tuple:
    """Run the standard Validator and return only Rules 1-8 results (exclude Rule 9)."""
    result = Validator().validate(branescript, config, interpreted)
    rules_1_8 = [
        r for r in result.rules
        if not r.rule.startswith("package_registered")
        and not r.rule.startswith("function_registered")
    ]
    passed = all(r.passed for r in rules_1_8)
    failed = [r.rule for r in rules_1_8 if not r.passed]
    return passed, failed


def jaccard_lines(a: str, b: str) -> float:
    sa = set(l.strip() for l in a.splitlines() if l.strip())
    sb = set(l.strip() for l in b.splitlines() if l.strip())
    union = sa | sb
    return round(len(sa & sb) / len(union), 4) if union else 1.0


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    config = build_kmeans_config()
    interpreted = PolicyInterpreter().interpret(config)

    print("=== M3.9: Extensibility to Novel Computation Patterns ===")
    print("Scenario: Federated k-means, K=2 rounds, package=fed_kmeans")
    print("Rule 9 excluded — fed_kmeans is hypothetical, not registered in Brane\n")

    # ── Template ────────────────────────────────────────────────────────────
    print("Running TemplateGenerator...")
    template_script = TemplateGenerator().generate(config, interpreted)
    t_v_passed, t_v_failed = run_validator_rules_1_8(template_script, config, interpreted)
    t_structural = check_structural_properties(template_script)

    print(f"  Validator Rules 1-8: {'PASS' if t_v_passed else 'FAIL'} | failed: {t_v_failed or 'none'}")
    for k, v in t_structural.items():
        if k != "summary":
            print(f"  {k}: {'PASS' if v['passed'] else 'FAIL'} — {v['description']}")
    print(f"  Structural score: {t_structural['summary']['score']}\n")

    with open(os.path.join(RESULTS_DIR, "m39_template.bs"), "w") as f:
        f.write(template_script)

    # ── LLM ─────────────────────────────────────────────────────────────────
    has_llm = bool(os.environ.get("OPENAI_API_KEY"))
    llm_run_results = []
    avg_jac = None
    template_vs_llm_jac = None

    if not has_llm:
        print("WARNING: OPENAI_API_KEY not set — skipping LLM runs")
    else:
        from app.infrastructure.llm_service import OpenAILlmService
        llm_service = OpenAILlmService()
        gen = LlmGenerator(llm_service)

        for run in range(N_RUNS):
            print(f"Running LlmGenerator (run {run + 1}/{N_RUNS})...")
            start = time.time()
            script = gen.generate(config, interpreted, container_yml=CONTAINER_YML)
            latency_ms = int((time.time() - start) * 1000)
            script = strip_bare_hash_comments(script)

            l_v_passed, l_v_failed = run_validator_rules_1_8(script, config, interpreted)
            l_structural = check_structural_properties(script)

            print(f"  Validator Rules 1-8: {'PASS' if l_v_passed else 'FAIL'} | failed: {l_v_failed or 'none'}")
            for k, v in l_structural.items():
                if k != "summary":
                    print(f"  {k}: {'PASS' if v['passed'] else 'FAIL'}")
            print(f"  Structural score: {l_structural['summary']['score']} | latency: {latency_ms}ms\n")

            llm_run_results.append({
                "run": run + 1,
                "script": script,
                "validator_rules_1_8_passed": l_v_passed,
                "failed_rules": l_v_failed,
                "structural": l_structural,
                "latency_ms": latency_ms,
            })

        # Jaccard across LLM runs (consistency)
        scripts = [r["script"] for r in llm_run_results]
        pairs = [(i, j) for i in range(N_RUNS) for j in range(i + 1, N_RUNS)]
        jac_scores = [jaccard_lines(scripts[i], scripts[j]) for i, j in pairs]
        avg_jac = round(sum(jac_scores) / len(jac_scores), 4) if jac_scores else 1.0

        # Jaccard between template and LLM run 1 — low value = structurally diverged
        template_vs_llm_jac = jaccard_lines(template_script, scripts[0])

        with open(os.path.join(RESULTS_DIR, "m39_llm_run1.bs"), "w") as f:
            f.write(scripts[0])

    # ── Save results ─────────────────────────────────────────────────────────
    output = {
        "metric": "M3.9",
        "scenario": "Federated k-means with K=2 rounds (hypothetical fed_kmeans package)",
        "note": "Rule 9 (package_registered) excluded — fed_kmeans not registered in Brane. Structural analysis only.",
        "template": {
            "validator_rules_1_8_passed": t_v_passed,
            "failed_rules": t_v_failed,
            "structural_properties": t_structural,
        },
        "llm": {
            "n_runs": N_RUNS,
            "runs": [
                {
                    "run": r["run"],
                    "validator_rules_1_8_passed": r["validator_rules_1_8_passed"],
                    "failed_rules": r["failed_rules"],
                    "structural_properties": r["structural"],
                    "latency_ms": r["latency_ms"],
                }
                for r in llm_run_results
            ],
            "avg_structural_score": round(
                sum(r["structural"]["summary"]["passed"] for r in llm_run_results) / len(llm_run_results), 2
            ) if llm_run_results else None,
            "llm_jaccard_consistency": avg_jac,
            "template_vs_llm_jaccard": template_vs_llm_jac,
        } if has_llm else None,
    }

    out_path = os.path.join(RESULTS_DIR, "extensibility_results.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print("=== Final Summary ===")
    print(f"Template — Rules 1-8: {'PASS' if t_v_passed else 'FAIL'} | Structural: {t_structural['summary']['score']}")
    if llm_run_results:
        scores = [r["structural"]["summary"]["passed"] for r in llm_run_results]
        print(f"LLM     — Structural scores across {N_RUNS} runs: {scores} (max {max(scores)}/3)")
        print(f"LLM Jaccard consistency: {avg_jac}")
        print(f"Template vs LLM Jaccard: {template_vs_llm_jac}  (low = structurally diverged — expected)")
    print(f"\nWritten: {out_path}")
    print("BraneScripts saved: evaluation/results/m39_template.bs, m39_llm_run1.bs")


if __name__ == "__main__":
    main()
