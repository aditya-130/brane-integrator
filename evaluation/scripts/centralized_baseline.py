import sys
import os
import json
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

DATASETS_DIR = os.path.join(os.path.dirname(__file__), "../datasets")
PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../packages")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../results")

PACKAGES = {
    "pkg_1": {"has_finalize": True},
    "pkg_2": {"has_finalize": True},
    "pkg_3": {"has_finalize": True},
    "pkg_4": {"has_finalize": True},
    "pkg_5": {"has_finalize": False},
}


def call_function(script_path, function_name, env_vars):
    env = os.environ.copy()
    env.update(env_vars)
    result = subprocess.run(
        [sys.executable, script_path, function_name],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{function_name} failed: {result.stderr}")
    output = json.loads(result.stdout.strip())
    return json.loads(output["output"])


def run_baseline(pkg_name, has_finalize):
    script_path = os.path.join(PACKAGES_DIR, pkg_name, "package.py")
    pooled_csv = os.path.join(DATASETS_DIR, f"pooled_{pkg_name}.csv")

    if not os.path.exists(pooled_csv):
        raise FileNotFoundError(
            f"Pooled dataset not found: {pooled_csv}\n"
            f"Run generate_datasets.py first."
        )

    # Step 1: compute_local on pooled data (simulates single-site baseline)
    local_result = call_function(
        script_path, "compute_local",
        {"LOCAL_DATA": json.dumps(str(pooled_csv))},
    )
    print(f"  compute_local: {str(local_result)[:80]}...")

    if not has_finalize:
        return local_result

    # Step 2: finalize on the local result
    final_result = call_function(
        script_path, "finalize",
        {"ACCUMULATOR": json.dumps(json.dumps(local_result))},
    )
    print(f"  finalize:      {str(final_result)[:80]}...")
    return final_result


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for pkg_name, opts in PACKAGES.items():
        print(f"\n{pkg_name}:")
        try:
            result = run_baseline(pkg_name, opts["has_finalize"])
            out_path = os.path.join(RESULTS_DIR, f"baseline_{pkg_name}.json")
            with open(out_path, "w") as f:
                json.dump({"package": pkg_name, "result": result}, f, indent=2)
            print(f"  Written: {out_path}")
        except Exception as e:
            print(f"  ERROR: {e}")

    print("\nDone. Baseline results are the ground truth for M4.1 (numerical equivalence).")


if __name__ == "__main__":
    main()
