import sys
import os
import json

REPO = "/home/aditya/thesis/integrator/brane-integrator"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "evaluation/scripts"))
os.chdir(REPO)
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from dotenv import load_dotenv
load_dotenv(os.path.join(REPO, ".env"))

from app.infrastructure.llm_service import OpenAILlmService
from app.api.packages import _generate_container_yml
from evaluate_package_generation import parse_triples, check_schema_validity

N_RUNS = 5
PACKAGES = {
    "pkg_1": "fed_mean",
    "pkg_2": "fed_logreg",
    "pkg_3": "fed_histogram",
    "pkg_4": "fed_variance",
    "pkg_5": "fed_single",
}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


llm = OpenAILlmService()

total_calls = 0
total_ok = 0
per_package = {}
for pkg, package_name in PACKAGES.items():
    py_path = os.path.join(REPO, f"evaluation/packages/{pkg}/package.py")
    with open(py_path) as f:
        python_code = f.read()

    print(f"\n=== {pkg} ({package_name}) ===")
    ymls = []
    for i in range(1, N_RUNS + 1):
        print(f"  run {i}/{N_RUNS}: generating container.yml (Path B)...", end=" ", flush=True)
        yml = _generate_container_yml(llm, python_code, package_name=package_name, python_filename="package.py")
        total_calls += 1
        ok = yml is not None
        total_ok += 1 if ok else 0
        ymls.append(yml)
        print("ok" if ok else "FAILED")

    valid_ymls = [y for y in ymls if y is not None]
    schema_valid_count = sum(1 for y in valid_ymls if check_schema_validity(y)[0])
    triple_sets = [parse_triples(y) for y in valid_ymls]
    pairs = [(i, j) for i in range(len(triple_sets)) for j in range(i + 1, len(triple_sets))]
    jac_scores = [jaccard(triple_sets[i], triple_sets[j]) for i, j in pairs]
    avg_jac = round(sum(jac_scores) / len(jac_scores), 4) if jac_scores else 1.0

    per_package[pkg] = {
        "schema_valid_rate": round(schema_valid_count / len(valid_ymls), 4) if valid_ymls else 0.0,
        "m_new_container_yml_jaccard": avg_jac,
        "raw_ymls": ymls,
    }
    print(f"  schema_valid_rate={per_package[pkg]['schema_valid_rate']}  jaccard={avg_jac}")

overall_jac = round(sum(v["m_new_container_yml_jaccard"] for v in per_package.values()) / len(per_package), 4)
print(f"\n{total_ok}/{total_calls} succeeded")
print(f"Overall Path B container.yml Jaccard consistency: {overall_jac}")

out = {"per_package": per_package, "overall_jaccard": overall_jac, "n_calls": total_calls, "n_ok": total_ok}
out_path = os.path.join(REPO, "evaluation/results/pathb_container_yml_results.json")
with open(out_path, "w") as f:
    json.dump(out, f, indent=2)
print(f"Written: {out_path}")

from cost_utils import print_usage_summary
print_usage_summary(llm.usage_log, label="Path B container.yml LLM usage")
