import sys
import os
import json
import subprocess
import shutil
import tempfile
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../packages")
DATASETS_DIR = os.path.join(os.path.dirname(__file__), "../datasets")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")

PACKAGES = ["pkg_1", "pkg_2", "pkg_3", "pkg_4", "pkg_5"]

# Expected container.yml types for M4.5 type inference accuracy check
EXPECTED_TYPES = {
    "pkg_1": {
        "compute_local": {"input": "Data", "output": "String"},
        "combine_results": {"input": "String", "output": "String"},
        "finalize": {"input": "String", "output": "String"},
    },
    "pkg_2": {
        "compute_local": {"input": "Data", "output": "String"},
        "combine_results": {"input": "String", "output": "String"},
        "finalize": {"input": "String", "output": "String"},
    },
    "pkg_3": {
        "compute_local": {"input": "Data", "output": "String"},
        "combine_results": {"input": "String", "output": "String"},
        "finalize": {"input": "String", "output": "String"},
    },
    "pkg_4": {
        "compute_local": {"input": "Data", "output": "String"},
        "combine_results": {"input": "String", "output": "String"},
        "finalize": {"input": "String", "output": "String"},
    },
    "pkg_5": {
        "compute_local": {"input": "Data", "output": "String"},
    },
}

# BraneScript for a 2-participant fed_mean run using scenario 1 datasets
EVAL_BRANESCRIPT = """import fed_mean;

let data_1 := #[on("participant-1")] new Data { name := "cancer_age_s1_p1" };
let data_3 := #[on("participant-3")] new Data { name := "cancer_age_s1_p3" };

let stats_1 := #[on("participant-1")] #[tag("identifiability.Pseudonymized")] compute_local(data_1);
let stats_3 := #[on("participant-3")] #[tag("identifiability.Anonymized")] compute_local(data_3);

let combined := #[on("coordinator-1")] combine_results(stats_1, stats_3);
let final := #[on("coordinator-1")] finalize(combined);
return final;
"""


def run_subprocess(cmd, cwd=None, env=None, timeout=120):
    result = subprocess.run(
        cmd, cwd=cwd, env=env or os.environ.copy(),
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode == 0, result.stdout, result.stderr


def brane_is_running():
    ok, _, _ = run_subprocess(["brane", "--help"])
    return ok


def load_container_yml(pkg_name):
    path = os.path.join(PACKAGES_DIR, pkg_name, "container.yml")
    if not os.path.exists(path):
        return None
    import yaml
    with open(path) as f:
        return yaml.safe_load(f)


def validate_container_yml_schema(yml):
    required_top_keys = {"name", "version", "kind", "entrypoint", "actions"}
    if not isinstance(yml, dict):
        return False, "Not a mapping"
    missing = required_top_keys - set(yml.keys())
    if missing:
        return False, f"Missing keys: {missing}"
    if yml.get("kind") != "ecu":
        return False, f"Expected kind=ecu, got {yml.get('kind')}"
    if not isinstance(yml.get("actions"), dict):
        return False, "actions must be a mapping"
    return True, "ok"


def check_type_inference(pkg_name, yml):
    expected = EXPECTED_TYPES.get(pkg_name, {})
    actions = yml.get("actions", {})
    correct, total = 0, 0
    details = {}
    for fn_name, exp in expected.items():
        if fn_name not in actions:
            details[fn_name] = {"status": "missing"}
            continue
        action = actions[fn_name]
        params = {p["name"]: p["type"] for p in action.get("input", [])}
        out_type = action.get("output", {}).get("type")
        fn_ok = True
        for param_name, param_type in exp.items():
            if param_name == "output":
                if out_type != param_type:
                    fn_ok = False
            else:
                if params.get(param_name) != param_type:
                    fn_ok = False
        total += 1
        if fn_ok:
            correct += 1
        details[fn_name] = {"correct": fn_ok, "expected": exp}
    return round(correct / total, 4) if total else 0.0, details


def call_package_function(pkg_name, function_name, env_vars):
    script_path = os.path.join(PACKAGES_DIR, pkg_name, "package.py")
    env = os.environ.copy()
    env.update(env_vars)
    result = subprocess.run(
        [sys.executable, script_path, function_name],
        capture_output=True, text=True, env=env, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{function_name} stderr: {result.stderr[:200]}")
    return json.loads(json.loads(result.stdout.strip())["output"])


def run_federated_pkg(pkg_name):
    participant_1_csv = os.path.join(DATASETS_DIR, f"participant_1_{pkg_name}.csv")
    participant_3_csv = os.path.join(DATASETS_DIR, f"participant_3_{pkg_name}.csv")

    if not os.path.exists(participant_1_csv) or not os.path.exists(participant_3_csv):
        raise FileNotFoundError(
            f"Dataset files missing for {pkg_name}. Run generate_datasets.py first."
        )

    local_1 = call_package_function(pkg_name, "compute_local", {"LOCAL_DATA": json.dumps(str(participant_1_csv))})
    local_3 = call_package_function(pkg_name, "compute_local", {"LOCAL_DATA": json.dumps(str(participant_3_csv))})

    has_combine = (pkg_name != "pkg_5")
    if not has_combine:
        return local_1

    combined = call_package_function(
        pkg_name, "combine_results",
        {
            "RESULT_1": json.dumps(json.dumps(local_1)),
            "RESULT_2": json.dumps(json.dumps(local_3)),
        },
    )
    final = call_package_function(pkg_name, "finalize", {"ACCUMULATOR": json.dumps(json.dumps(combined))})
    return final


def compare_results(federated, baseline):
    if federated is None or baseline is None:
        return False, "missing data"
    if type(federated) != type(baseline):
        return False, f"type mismatch: {type(federated).__name__} vs {type(baseline).__name__}"
    if isinstance(federated, dict):
        if set(federated.keys()) != set(baseline.keys()):
            return False, f"key mismatch: {set(federated.keys())} vs {set(baseline.keys())}"
        for k in federated:
            equal, reason = compare_results(federated[k], baseline[k])
            if not equal:
                return False, f"key {k!r}: {reason}"
        return True, "equal"
    if isinstance(federated, (int, float)):
        tol = 1e-6
        if abs(federated - baseline) > tol:
            return False, f"numeric diff: {federated} vs {baseline} (tol={tol})"
        return True, "equal"
    if federated != baseline:
        return False, f"value mismatch: {federated!r} vs {baseline!r}"
    return True, "equal"


def run_on_brane(pkg_name):
    wf_file = tempfile.NamedTemporaryFile(mode="w", suffix=".bs", delete=False)
    wf_file.write(EVAL_BRANESCRIPT)
    wf_file.close()

    start = time.time()
    ok, stdout, stderr = run_subprocess(
        ["brane", "workflow", "run", "--package-dir", os.path.join(PACKAGES_DIR, pkg_name), wf_file.name],
        timeout=180,
    )
    latency_ms = int((time.time() - start) * 1000)
    os.unlink(wf_file.name)

    return ok, stdout, stderr, latency_ms


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Load centralized baselines
    baselines = {}
    for pkg_name in PACKAGES:
        baseline_path = os.path.join(RESULTS_DIR, f"baseline_{pkg_name}.json")
        if os.path.exists(baseline_path):
            with open(baseline_path) as f:
                baselines[pkg_name] = json.load(f)["result"]
        else:
            print(f"WARNING: baseline not found for {pkg_name} — run centralized_baseline.py first")

    brane_available = brane_is_running()
    if not brane_available:
        print("WARNING: brane CLI not found — M4.7 (end-to-end) will be skipped")

    results = {}

    for pkg_name in PACKAGES:
        print(f"\n{pkg_name}:")
        pkg_result = {
            "package": pkg_name,
            "schema_valid": None,
            "type_accuracy": None,
            "numerical_match": None,
            "brane_e2e": None,
        }

        # M4.6: container.yml schema validity
        yml = load_container_yml(pkg_name)
        if yml is None:
            print(f"  container.yml not found")
        else:
            schema_ok, schema_msg = validate_container_yml_schema(yml)
            pkg_result["schema_valid"] = schema_ok
            print(f"  M4.6 schema_valid: {schema_ok} ({schema_msg})")

            # M4.5: type inference accuracy
            type_acc, type_details = check_type_inference(pkg_name, yml)
            pkg_result["type_accuracy"] = type_acc
            pkg_result["type_details"] = type_details
            print(f"  M4.5 type_accuracy: {type_acc}")

        # M4.1: numerical equivalence (federated vs centralized)
        baseline = baselines.get(pkg_name)
        try:
            federated = run_federated_pkg(pkg_name)
            equal, reason = compare_results(federated, baseline)
            pkg_result["numerical_match"] = equal
            pkg_result["numerical_match_reason"] = reason
            print(f"  M4.1 numerical_match: {equal} ({reason})")
        except Exception as e:
            print(f"  M4.1 ERROR: {e}")
            pkg_result["numerical_match"] = False
            pkg_result["numerical_match_reason"] = str(e)

        # M4.7: end-to-end execution on live Brane (pkg_1 only — uses the EVAL_BRANESCRIPT above)
        if brane_available and pkg_name == "pkg_1":
            try:
                ok, stdout, stderr, latency_ms = run_on_brane(pkg_name)
                pkg_result["brane_e2e"] = {"success": ok, "latency_ms": latency_ms}
                print(f"  M4.7 brane_e2e: success={ok} latency={latency_ms}ms")
                if not ok:
                    print(f"  stderr: {stderr[:200]}")
            except Exception as e:
                print(f"  M4.7 ERROR: {e}")
                pkg_result["brane_e2e"] = {"success": False, "error": str(e)}

        results[pkg_name] = pkg_result

    # Aggregate metrics
    schema_valid_rate = round(
        sum(1 for r in results.values() if r["schema_valid"]) / len(results), 4
    )
    avg_type_accuracy = round(
        sum(r["type_accuracy"] for r in results.values() if r["type_accuracy"] is not None)
        / len(results), 4
    )
    numerical_match_rate = round(
        sum(1 for r in results.values() if r["numerical_match"]) / len(results), 4
    )

    output = {
        "schema_valid_rate": schema_valid_rate,
        "avg_type_accuracy": avg_type_accuracy,
        "numerical_match_rate": numerical_match_rate,
        "per_package": results,
    }

    out_path = os.path.join(RESULTS_DIR, "package_metrics.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nM4.6 Schema valid rate:    {schema_valid_rate:.1%}")
    print(f"M4.5 Avg type accuracy:    {avg_type_accuracy:.1%}")
    print(f"M4.1 Numerical match rate: {numerical_match_rate:.1%}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
