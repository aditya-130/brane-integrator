"""
evaluate_package_generation.py

Path A evaluation: PackageGenerator.generate(study_objective, computation_description)
called with no Python code given -- the LLM writes python_code + container_yml from scratch.

Collects: M4.2 (accumulator contract), M4.4 (build success), M4.5 (type accuracy),
          M4.6 (schema validity), M4.12 (numerical correctness), M4.13/M4.14 (Jaccard consistency)

Usage: .venv/bin/python3 evaluation/scripts/evaluate_package_generation.py [--build]
  --build   also attempt M4.4 (PackageBuilder build+push) -- requires Brane running
"""

import sys
import os
import json
import shutil
import subprocess
import sys as _sys
from pathlib import Path

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

from app.application.package_manager.package_generator import PackageGenerator
from app.application.package_manager.package_builder import PackageBuilder
from app.infrastructure.settings import settings

EVAL_DIR = Path(__file__).parent.parent
DESCRIPTIONS_PATH = EVAL_DIR / "package_descriptions.json"
DATASETS_DIR = EVAL_DIR / "datasets"
PACKAGES_DIR = EVAL_DIR / "packages"
RESULTS_DIR = EVAL_DIR / "results"
GENERATED_DIR = RESULTS_DIR / "generated_packages"
BUILD_BASE = Path("/tmp/eval_package_generation_build")

N_RUNS = 5
REQUIRED_SCHEMA_KEYS = {"name", "version", "kind", "actions"}


# ---------------------------------------------------------------------------
# Shared helpers (mirrors centralized_baseline.py / run_evaluation.py exactly
# so all three "does the generated computation give the right answer" checks
# in the thesis use the same comparison logic)
# ---------------------------------------------------------------------------

def _unwrap(x):
    """Strip semantically-named single-key wrapper dicts, e.g. {"mean_age": 56.7} -> 56.7.
    LLM-generated finalize functions sometimes wrap a bare scalar/list in a descriptively
    named key even when the reference doesn't. Only collapses dicts with exactly one key --
    a real multi-field dict (e.g. {"count":, "age_sum":}) is left untouched, so a wrong
    grouping or a dropped field is still caught below. Recursion happens per comparison call,
    so if the unwrapped value itself is wrong it still fails the numeric/key checks -- this
    only removes shape noise, never value-correctness signal."""
    while isinstance(x, dict) and len(x) == 1:
        x = next(iter(x.values()))
    return x


def compare(a, b):
    a, b = _unwrap(a), _unwrap(b)

    a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
    b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
    if a_num and b_num:
        # int vs float (e.g. count: 50 vs 50.0) is the same number -- compare by value,
        # not by type, so representation differences don't register as mismatches.
        return abs(a - b) <= 1e-6, f"diff={abs(a - b)}"

    if type(a) != type(b):
        return False, f"type mismatch: {type(a).__name__} vs {type(b).__name__} ({a!r} vs {b!r})"

    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False, f"key mismatch: {set(a.keys())} vs {set(b.keys())}"
        for k in a:
            ok, reason = compare(a[k], b[k])
            if not ok:
                return False, f"{k}: {reason}"
        return True, "equal"

    if isinstance(a, list):
        if len(a) != len(b):
            return False, f"list length mismatch: {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            ok, reason = compare(x, y)
            if not ok:
                return False, f"[{i}]: {reason}"
        return True, "equal"

    return a == b, f"{a!r} != {b!r}"


def jaccard(set_a, set_b):
    union = set_a | set_b
    return round(len(set_a & set_b) / len(union), 4) if union else 1.0


def jaccard_lines(code_a, code_b):
    set_a = set(l.strip() for l in code_a.splitlines() if l.strip())
    set_b = set(l.strip() for l in code_b.splitlines() if l.strip())
    return jaccard(set_a, set_b)


def call_function(script_path, function_name, env_vars):
    """Same subprocess-dispatch pattern as centralized_baseline.py. Generated packages
    use the identical `sys.argv[1]` dispatch block the PACKAGE_GENERATOR_SYSTEM prompt
    mandates, so this works on LLM-generated code without any exec()/sys.argv faking."""
    env = os.environ.copy()
    env.update(env_vars)
    result = subprocess.run(
        [_sys.executable, str(script_path), function_name],
        capture_output=True, text=True, env=env, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{function_name} exited {result.returncode}: {result.stderr[-500:]}")
    output = json.loads(result.stdout.strip())
    decoded = json.loads(output["output"])
    if isinstance(decoded, dict) and "error" in decoded and len(decoded) == 1:
        raise RuntimeError(f"{function_name} raised inside package: {decoded['error']}")
    return decoded


# ---------------------------------------------------------------------------
# container.yml parsing
# ---------------------------------------------------------------------------

def parse_triples(container_yml_text):
    """Returns {(action, param, type)} for every declared input AND output across all actions."""
    triples = set()
    try:
        data = yaml.safe_load(container_yml_text)
    except yaml.YAMLError:
        return triples
    if not isinstance(data, dict):
        return triples
    actions = data.get("actions") or {}
    if not isinstance(actions, dict):
        return triples
    for action_name, spec in actions.items():
        if not isinstance(spec, dict):
            continue
        for direction in ("input", "output"):
            for item in (spec.get(direction) or []):
                if isinstance(item, dict):
                    triples.add((action_name, item.get("name"), item.get("type")))
    return triples


def check_schema_validity(container_yml_text):
    try:
        data = yaml.safe_load(container_yml_text)
    except yaml.YAMLError as e:
        return False, f"yaml parse error: {e}"
    if not isinstance(data, dict):
        return False, "top-level is not a mapping"
    missing = REQUIRED_SCHEMA_KEYS - set(data.keys())
    if missing:
        return False, f"missing required keys: {missing}"
    if not isinstance(data.get("actions"), dict) or not data["actions"]:
        return False, "actions block missing or empty"
    return True, "valid"


def categorize_type_errors(generated_triples, reference_triples):
    """Per-category breakdown, mirrors SLR Paper 97's IaCGen failure taxonomy (see M4.5 note
    in final_metrics.md): missing_action, wrong_type, wrong_param, hallucinated_action."""
    gen_actions = {t[0] for t in generated_triples}
    ref_actions = {t[0] for t in reference_triples}

    missing_actions = ref_actions - gen_actions
    hallucinated_actions = gen_actions - ref_actions

    gen_by_action = {}
    for a, p, t in generated_triples:
        gen_by_action.setdefault(a, {})[p] = t
    ref_by_action = {}
    for a, p, t in reference_triples:
        ref_by_action.setdefault(a, {})[p] = t

    wrong_type, wrong_param, matched = [], [], []
    for action in ref_actions & gen_actions:
        ref_params = ref_by_action.get(action, {})
        gen_params = gen_by_action.get(action, {})
        for param, ref_type in ref_params.items():
            if param not in gen_params:
                wrong_param.append(f"{action}.{param} (missing)")
            elif gen_params[param] != ref_type:
                wrong_type.append(f"{action}.{param}: expected {ref_type}, got {gen_params[param]}")
            else:
                matched.append(f"{action}.{param}")

    total_ref = len(reference_triples)
    accuracy = round(len(matched) / total_ref, 4) if total_ref else None

    return {
        "accuracy": accuracy,
        "matched_count": len(matched),
        "total_reference_triples": total_ref,
        "missing_actions": sorted(missing_actions),
        "hallucinated_actions": sorted(hallucinated_actions),
        "wrong_type": wrong_type,
        "wrong_param": wrong_param,
    }


# ---------------------------------------------------------------------------
# M4.12 numerical correctness + M4.2 accumulator contract (share one execution)
# ---------------------------------------------------------------------------

def run_numerical_check(pkg_id, script_path, baseline_result):
    """Returns (numerical_result_dict). Executes compute_local on both participant CSVs,
    combine_results, finalize (if present in the generated file), compares to baseline.
    Also derives M4.2 from the same execution: does combine's output key-set match
    compute_local's output key-set? (container.yml only ever declares type: string for
    everything -- it carries no field-level structure, so the contract must be checked
    from actual runtime output shape, not from the yaml text.)
    """
    out = {"error": None, "numerical_match": None, "accumulator_contract_ok": None, "final_result": None}

    p1_csv = DATASETS_DIR / f"participant_1_{pkg_id}.csv"
    p3_csv = DATASETS_DIR / f"participant_3_{pkg_id}.csv"

    try:
        result_1 = call_function(script_path, "compute_local", {"LOCAL_DATA": json.dumps(str(p1_csv))})
    except Exception as e:
        out["error"] = f"compute_local (participant_1) failed: {e}"
        return out

    if pkg_id == "pkg_5":
        # No combine/finalize expected by design. If the LLM generated them anyway
        # (system prompt mandates all three -- see F-Path-A-Combine limitation),
        # we still only exercise compute_local, matching how pkg_5 works in production.
        out["final_result"] = result_1
        ok, reason = compare(result_1, baseline_result)
        out["numerical_match"] = ok
        out["numerical_match_note"] = (
            "pkg_5 is intentionally single-participant; baseline is pooled -- "
            "mismatch is expected, same as M4.1/e2e_results.json"
        ) if not ok else None
        return out

    try:
        result_2 = call_function(script_path, "compute_local", {"LOCAL_DATA": json.dumps(str(p3_csv))})
    except Exception as e:
        out["error"] = f"compute_local (participant_3) failed: {e}"
        return out

    try:
        accumulator = call_function(script_path, "combine_results", {
            "RESULT_1": json.dumps(json.dumps(result_1)),
            "RESULT_2": json.dumps(json.dumps(result_2)),
        })
    except Exception as e:
        out["error"] = f"combine_results failed: {e}"
        return out

    if isinstance(result_1, dict) and isinstance(accumulator, dict):
        out["accumulator_contract_ok"] = set(result_1.keys()) == set(accumulator.keys())
    else:
        out["accumulator_contract_ok"] = type(result_1) == type(accumulator)

    try:
        final_result = call_function(script_path, "finalize", {
            "ACCUMULATOR": json.dumps(json.dumps(accumulator)),
        })
    except Exception as e:
        out["error"] = f"finalize failed: {e}"
        return out

    out["final_result"] = final_result
    ok, reason = compare(final_result, baseline_result)
    out["numerical_match"] = ok
    out["numerical_match_reason"] = None if ok else reason
    return out


# ---------------------------------------------------------------------------
# M4.4 build success (last, Brane-gated)
# ---------------------------------------------------------------------------

def try_build(pkg_id, run_idx, python_code, container_yml_text, package_name):
    working_dir = BUILD_BASE / f"{pkg_id}_run{run_idx}"
    if working_dir.exists():
        shutil.rmtree(working_dir)
    working_dir.mkdir(parents=True)

    sanitized_yml = container_yml_text.replace("type: String", "type: string")
    container_yml_path = working_dir / "container.yml"
    py_filename = f"{package_name}.py"

    (working_dir / py_filename).write_text(python_code.replace("\r\n", "\n"))
    container_yml_path.write_text(sanitized_yml.replace("\r\n", "\n"))

    run_sh = working_dir / "run.sh"
    run_sh.write_text(f"#!/bin/bash\npython3 /opt/wd/{py_filename} \"$1\"\n")
    run_sh.chmod(0o755)

    branelet_src = Path(settings.BRANELET_PATH) if settings.BRANELET_PATH else None
    if branelet_src and branelet_src.exists():
        shutil.copy2(branelet_src, working_dir / "branelet")

    (working_dir / "Dockerfile").write_text(
        "FROM python:3.10-slim\n\n"
        "RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y "
        "--allow-change-held-packages --allow-downgrades fuse iptables\n\n"
        "ADD branelet /branelet\n"
        "RUN chmod +x /branelet\n\n"
        "RUN mkdir -p /opt/wd\n"
        f"COPY {py_filename} /opt/wd/{py_filename}\n"
        "COPY run.sh /opt/wd/run.sh\n"
        "RUN chmod +x /opt/wd/run.sh\n\n"
        "COPY container.yml /opt/wd/container.yml\n\n"
        "WORKDIR /opt/wd\n"
        'ENTRYPOINT ["/branelet"]\n'
    )

    builder = PackageBuilder()
    build_result = builder.build(working_dir, container_yml_path)
    if not build_result.success:
        return {"built": False, "pushed": False, "error": (build_result.stderr or "")[-500:]}

    # Push by the already-known package_name (from container.yml's `name:` field), not
    # build_result.image_name -- _parse_image_name() in package_builder.py mis-parses
    # Brane's actual build output ("Successfully built version X of container (ECU)
    # package <name>.") and returns "<name>." with a trailing sentence period. Production
    # code never hits this because every real push() call site uses its own known
    # package_name too (see app/application/workflow_generation/workflow_job_handler.py
    # and node_provisioner.py) -- image_name is only ever used cosmetically in an API
    # response field, so this bug is latent/dormant in production. Worth a fix upstream,
    # flagged separately, not touched here since it's out of scope for this eval script.
    pushed = builder.push(package_name)
    return {"built": True, "pushed": pushed, "image_name": build_result.image_name}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    do_build = "--build" in sys.argv

    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(GENERATED_DIR, exist_ok=True)

    has_llm = bool(os.environ.get("OPENAI_API_KEY"))
    if not has_llm:
        print("ERROR: OPENAI_API_KEY not set — cannot run Path A generation.")
        sys.exit(1)

    from app.infrastructure.llm_service import OpenAILlmService
    llm_service = OpenAILlmService()
    generator = PackageGenerator(llm_service)

    descriptions = json.loads(DESCRIPTIONS_PATH.read_text())

    results = {}

    for pkg_id, desc in descriptions.items():
        print(f"\n{'=' * 60}\n{pkg_id} ({desc['brane_name']})\n{'=' * 60}")

        baseline_path = RESULTS_DIR / f"baseline_{pkg_id}.json"
        baseline_result = json.loads(baseline_path.read_text())["result"]

        reference_yml_text = (PACKAGES_DIR / pkg_id / "container.yml").read_text()
        reference_triples = parse_triples(reference_yml_text)

        runs = []
        for run_idx in range(1, N_RUNS + 1):
            print(f"  run {run_idx}/{N_RUNS}: generating...", end=" ", flush=True)
            pkg = generator.generate(
                study_objective=desc["study_objective"],
                computation_description=desc["computation_description"],
                package_name=f"{pkg_id}_eval",
            )
            if pkg is None:
                print("LLM returned None, skipping run")
                runs.append({"run": run_idx, "generation_failed": True})
                continue

            py_path = GENERATED_DIR / f"{pkg_id}_run{run_idx}.py"
            yml_path = GENERATED_DIR / f"{pkg_id}_run{run_idx}.yml"
            py_path.write_text(pkg.python_code)
            yml_path.write_text(pkg.container_yml)

            schema_valid, schema_reason = check_schema_validity(pkg.container_yml)
            gen_triples = parse_triples(pkg.container_yml)
            type_report = categorize_type_errors(gen_triples, reference_triples)

            numerical = run_numerical_check(pkg_id, py_path, baseline_result)

            run_record = {
                "run": run_idx,
                "package_name": pkg.package_name,
                "python_filename": pkg.python_filename,
                "python_path": str(py_path),
                "container_yml_path": str(yml_path),
                "m4_6_schema_valid": schema_valid,
                "m4_6_schema_reason": None if schema_valid else schema_reason,
                "m4_5_type_report": type_report,
                "m4_12_numerical": numerical,
                "_gen_triples": sorted(str(t) for t in gen_triples),  # for jaccard later
            }
            runs.append(run_record)

            print(
                f"schema_valid={schema_valid} "
                f"type_acc={type_report['accuracy']} "
                f"numerical_match={numerical.get('numerical_match')} "
                f"accumulator_ok={numerical.get('accumulator_contract_ok')}"
            )

        # ---- aggregate across the N_RUNS for this package ----
        valid_runs = [r for r in runs if not r.get("generation_failed")]

        m46_rate = round(sum(1 for r in valid_runs if r["m4_6_schema_valid"]) / len(valid_runs), 4) if valid_runs else None
        m45_accs = [r["m4_5_type_report"]["accuracy"] for r in valid_runs if r["m4_5_type_report"]["accuracy"] is not None]
        m45_avg = round(sum(m45_accs) / len(m45_accs), 4) if m45_accs else None

        contract_flags = [r["m4_12_numerical"]["accumulator_contract_ok"] for r in valid_runs
                           if r["m4_12_numerical"]["accumulator_contract_ok"] is not None]
        m42_rate = round(sum(1 for c in contract_flags if c) / len(contract_flags), 4) if contract_flags else None

        match_flags = [r["m4_12_numerical"]["numerical_match"] for r in valid_runs
                       if r["m4_12_numerical"]["numerical_match"] is not None]
        m412_rate = round(sum(1 for m in match_flags if m) / len(match_flags), 4) if match_flags else None

        # M4.5 supplementary: hallucination rate (accuracy above is recall-only against
        # reference triples and does not penalize extra generated actions -- track separately
        # so pkg_5's system-prompt-mandated combine/finalize hallucination is visible).
        halluc_flags = [len(r["m4_5_type_report"]["hallucinated_actions"]) > 0 for r in valid_runs]
        m45_halluc_rate = round(sum(1 for h in halluc_flags if h) / len(halluc_flags), 4) if halluc_flags else None

        # M4.13: pairwise Jaccard on generated python_code line sets
        codes = [Path(r["python_path"]).read_text() for r in valid_runs]
        code_pairs = [(i, j) for i in range(len(codes)) for j in range(i + 1, len(codes))]
        m413_scores = [jaccard_lines(codes[i], codes[j]) for i, j in code_pairs]
        m413_avg = round(sum(m413_scores) / len(m413_scores), 4) if m413_scores else None

        # M4.14: pairwise Jaccard on (action,param,type) triple sets
        triple_sets = [set(r["_gen_triples"]) for r in valid_runs]
        triple_pairs = [(i, j) for i in range(len(triple_sets)) for j in range(i + 1, len(triple_sets))]
        m414_scores = [jaccard(triple_sets[i], triple_sets[j]) for i, j in triple_pairs]
        m414_avg = round(sum(m414_scores) / len(m414_scores), 4) if m414_scores else None

        for r in valid_runs:
            r.pop("_gen_triples", None)

        results[pkg_id] = {
            "brane_name": desc["brane_name"],
            "n_runs": N_RUNS,
            "n_generation_failures": len(runs) - len(valid_runs),
            "m4_6_schema_valid_rate": m46_rate,
            "m4_5_avg_type_accuracy": m45_avg,
            "m4_5_hallucination_rate": m45_halluc_rate,
            "m4_2_accumulator_contract_rate": m42_rate,
            "m4_12_numerical_match_rate": m412_rate,
            "m4_13_python_jaccard": m413_avg,
            "m4_14_container_yml_jaccard": m414_avg,
            "runs": runs,
        }

        if do_build:
            print(f"  M4.4: building run 1 (representative)...")
            run1 = valid_runs[0] if valid_runs else None
            if run1:
                py_code = Path(run1["python_path"]).read_text()
                yml_code = Path(run1["container_yml_path"]).read_text()
                build_result = try_build(pkg_id, 1, py_code, yml_code, run1["package_name"])
                results[pkg_id]["m4_4_build"] = build_result
                print(f"    built={build_result['built']} pushed={build_result.get('pushed')}")

    # ---- overall summary across all 5 packages ----
    def overall(key):
        vals = [results[p][key] for p in results if results[p][key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    # M4.12 headline excludes pkg_5, same convention as M4.1/e2e_results.json: pkg_5 is an
    # intentional single-participant-vs-pooled-baseline mismatch by design, not a failure.
    non_pkg5_rates = [results[p]["m4_12_numerical_match_rate"] for p in results
                       if p != "pkg_5" and results[p]["m4_12_numerical_match_rate"] is not None]
    m412_excl_pkg5 = round(sum(non_pkg5_rates) / len(non_pkg5_rates), 4) if non_pkg5_rates else None

    summary = {
        "m4_6_schema_valid_rate": overall("m4_6_schema_valid_rate"),
        "m4_5_avg_type_accuracy": overall("m4_5_avg_type_accuracy"),
        "m4_5_hallucination_rate": overall("m4_5_hallucination_rate"),
        "m4_2_accumulator_contract_rate": overall("m4_2_accumulator_contract_rate"),
        "m4_12_numerical_match_rate_all_5_packages": overall("m4_12_numerical_match_rate"),
        "m4_12_numerical_match_rate_excl_pkg5": m412_excl_pkg5,
        "m4_13_python_jaccard": overall("m4_13_python_jaccard"),
        "m4_14_container_yml_jaccard": overall("m4_14_container_yml_jaccard"),
        "note_pkg_5": (
            "pkg_5 has no combine/finalize by design, but PACKAGE_GENERATOR_SYSTEM prompt "
            "mandates generating all three functions -- shows up as hallucinated_actions in "
            "m4_5_type_report (m4_5_hallucination_rate is the pkg_5-driven signal, since "
            "m4_5_avg_type_accuracy is recall-only against reference triples and does not "
            "penalize extras) and as an expected m4_12 non-match (single-participant result "
            "vs pooled baseline, same convention as e2e_results.json). Documented limitation, "
            "not a bug. See FINDINGS.md."
        ),
        "build_attempted": do_build,
    }

    output = {"summary": summary, "packages": results}
    out_path = RESULTS_DIR / "package_generation_results.json"
    out_path.write_text(json.dumps(output, indent=2))

    print(f"\n{'=' * 60}\nSUMMARY\n{'=' * 60}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
