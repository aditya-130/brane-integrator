import sys
import os
import json
import logging
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from app.domain.config import IntegratorConfig, ProjectBlock, WorkflowSpec, ParticipantPolicy
from app.application.workflow_generation.free_text_extractor import FreeTextExtractor
from app.infrastructure.llm_service import OpenAILlmService

GOLD_SET_PATH = os.path.join(os.path.dirname(__file__), "../gold_set.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")
N_RUNS = 5


class ConfidenceLogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.entries = []

    def emit(self, record):
        msg = record.getMessage()
        m = re.search(r"Raw claims from LLM: (\d+) total — high=(\d+) medium=(\d+) low=(\d+)", msg)
        if m:
            self.entries.append({
                "total": int(m.group(1)),
                "high": int(m.group(2)),
                "medium": int(m.group(3)),
                "low": int(m.group(4)),
            })


def make_config_for_entry(entry):
    kwargs = {entry["source_field"]: entry["input_text"]}
    participant = ParticipantPolicy(
        user_id=1,
        brane_node="eval-node",
        dataset_name="eval-dataset",
        **kwargs,
    )
    return IntegratorConfig(
        project=ProjectBlock(project_id=999),
        workflow=WorkflowSpec(
            package="eval",
            local_function="f",
            combine_function="c",
            coordinator_node="eval-coord",
        ),
        participants=[participant],
    )


def claims_to_set(claims):
    return frozenset((c.policy_field, c.policy_value) for c in claims)


def expected_to_set(expected):
    return frozenset((c["policy_field"], c["policy_value"]) for c in expected)


def precision_recall_f1(extracted, expected):
    if not extracted and not expected:
        return 1.0, 1.0, 1.0
    if not extracted:
        return 0.0, 0.0, 0.0
    if not expected:
        return 0.0, 1.0, 0.0
    tp = len(extracted & expected)
    precision = tp / len(extracted)
    recall = tp / len(expected)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def jaccard(set_a, set_b):
    union = set_a | set_b
    if not union:
        return 1.0
    return round(len(set_a & set_b) / len(union), 4)


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    os.makedirs(RESULTS_DIR, exist_ok=True)

    with open(GOLD_SET_PATH) as f:
        gold_set = json.load(f)

    llm_service = OpenAILlmService()
    extractor = FreeTextExtractor()

    log_capture = ConfidenceLogCapture()
    log_capture.setLevel(logging.INFO)
    logging.getLogger("app.application.workflow_generation.free_text_extractor").addHandler(log_capture)

    all_precisions, all_recalls, all_f1s, all_jaccards = [], [], [], []
    per_entry = []

    for entry in gold_set:
        config = make_config_for_entry(entry)
        expected = expected_to_set(entry["expected_claims"])
        run_sets = []

        for run in range(N_RUNS):
            updated = extractor.extract(config, llm_service)
            extracted = claims_to_set(updated.participants[0].extracted_claims)
            run_sets.append(extracted)

        prec_list, rec_list, f1_list = [], [], []
        for extracted in run_sets:
            p, r, f = precision_recall_f1(extracted, expected)
            prec_list.append(p)
            rec_list.append(r)
            f1_list.append(f)

        pairs = [(i, j) for i in range(N_RUNS) for j in range(i + 1, N_RUNS)]
        jac_scores = [jaccard(run_sets[i], run_sets[j]) for i, j in pairs]
        avg_jac = round(sum(jac_scores) / len(jac_scores), 4) if jac_scores else 1.0

        avg_p = round(sum(prec_list) / N_RUNS, 4)
        avg_r = round(sum(rec_list) / N_RUNS, 4)
        avg_f = round(sum(f1_list) / N_RUNS, 4)

        all_precisions.append(avg_p)
        all_recalls.append(avg_r)
        all_f1s.append(avg_f)
        all_jaccards.append(avg_jac)

        per_entry.append({
            "id": entry["id"],
            "source_field": entry["source_field"],
            "expected_claims": entry["expected_claims"],
            "avg_precision": avg_p,
            "avg_recall": avg_r,
            "avg_f1": avg_f,
            "avg_jaccard": avg_jac,
            "runs": [list(s) for s in run_sets],
        })
        print(f"  {entry['id']}: P={avg_p} R={avg_r} F1={avg_f} J={avg_jac}")

    total = len(gold_set)
    macro_p = round(sum(all_precisions) / total, 4)
    macro_r = round(sum(all_recalls) / total, 4)
    macro_f = round(sum(all_f1s) / total, 4)
    macro_j = round(sum(all_jaccards) / total, 4)

    # M4.11: aggregate confidence distribution across all log captures
    conf_totals = {"high": 0, "medium": 0, "low": 0, "total": 0}
    for rec in log_capture.entries:
        conf_totals["high"] += rec["high"]
        conf_totals["medium"] += rec["medium"]
        conf_totals["low"] += rec["low"]
        conf_totals["total"] += rec["total"]

    low_filtered = conf_totals["low"]
    kept = conf_totals["high"] + conf_totals["medium"]
    low_filtered_rate = round(low_filtered / conf_totals["total"], 4) if conf_totals["total"] else 0.0

    output = {
        "precision": macro_p,
        "recall": macro_r,
        "f1": macro_f,
        "jaccard_consistency": macro_j,
        "confidence_distribution": {
            "high": conf_totals["high"],
            "medium": conf_totals["medium"],
            "low": conf_totals["low"],
            "total": conf_totals["total"],
        },
        "low_filtered_rate": low_filtered_rate,
        "n_runs": N_RUNS,
        "n_entries": total,
        "per_entry": per_entry,
    }

    out_path = os.path.join(RESULTS_DIR, "extraction_metrics.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nM4.8 Precision:          {macro_p}")
    print(f"M4.9 Recall:             {macro_r}")
    print(f"M4.9 F1:                 {macro_f}")
    print(f"M4.10 Jaccard:           {macro_j}")
    print(f"M4.11 Confidence dist:   high={conf_totals['high']} medium={conf_totals['medium']} low={conf_totals['low']}")
    print(f"M4.11 Low-filtered rate: {low_filtered_rate:.1%}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
