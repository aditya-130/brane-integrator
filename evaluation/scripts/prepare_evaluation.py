"""
prepare_evaluation.py

Step 1 of the end-to-end evaluation.
- Builds + pushes all 5 packages to the Brane registry
- Registers all datasets
- Checks M4.6 (schema validity) and M4.5 (type accuracy) for each container.yml
- Generates BraneScript via TemplateGenerator for all 5 packages
- Generates BraneScript via LlmGenerator for all 5 packages (if OPENAI_API_KEY set)
- Saves all scripts to evaluation/results/generated/

No Brane execution. No Integrator API calls. Fast and deterministic.
"""

import sys
import os
import json
import shutil
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

import yaml

from app.infrastructure.settings import settings
from app.domain.config import IntegratorConfig, ProjectBlock, WorkflowSpec, ParticipantPolicy
from app.application.workflow_generation.policy_interpreter import PolicyInterpreter
from app.application.workflow_generation.strategy.template_generator import TemplateGenerator
from app.application.package_manager.package_builder import PackageBuilder
from app.application.node_provisioner.node_provisioner import _check_node_running, _register_dataset

EVAL_DIR = Path(__file__).parent.parent
PACKAGES_DIR = EVAL_DIR / "packages"
DATASETS_DIR = EVAL_DIR / "datasets"
RESULTS_DIR = EVAL_DIR / "results"
GENERATED_DIR = RESULTS_DIR / "generated"

PACKAGES = [
    {
        "pkg_id": "pkg_1",
        "brane_name": "fed_mean",
        "local_fn": "compute_local",
        "combine_fn": "combine_results",
        "finalize_fn": "finalize",
        "p1_dataset": "cancer_age_s1_p1",
        "p3_dataset": "cancer_age_s1_p3",
        "participants": [1, 3],
    },
    {
        "pkg_id": "pkg_2",
        "brane_name": "fed_logreg",
        "local_fn": "compute_local",
        "combine_fn": "combine_results",
        "finalize_fn": "finalize",
        "p1_dataset": "eval_logreg_p1",
        "p3_dataset": "eval_logreg_p3",
        "participants": [1, 3],
    },
    {
        "pkg_id": "pkg_3",
        "brane_name": "fed_histogram",
        "local_fn": "compute_local",
        "combine_fn": "combine_results",
        "finalize_fn": "finalize",
        "p1_dataset": "eval_hist_p1",
        "p3_dataset": "eval_hist_p3",
        "participants": [1, 3],
    },
    {
        "pkg_id": "pkg_4",
        "brane_name": "fed_variance",
        "local_fn": "compute_local",
        "combine_fn": "combine_results",
        "finalize_fn": "finalize",
        "p1_dataset": "eval_var_p1",
        "p3_dataset": "eval_var_p3",
        "participants": [1, 3],
    },
    {
        "pkg_id": "pkg_5",
        "brane_name": "fed_single",
        "local_fn": "compute_local",
        "combine_fn": "combine_results",
        "finalize_fn": None,
        "p1_dataset": "eval_single_p1",
        "p3_dataset": None,
        "participants": [1],
    },
]

EXPECTED_ACTION_TYPES = {
    "compute_local":   {"input": [{"type": "Data"}],                       "output": [{"type": "string"}]},
    "combine_results": {"input": [{"type": "string"}, {"type": "string"}], "output": [{"type": "string"}]},
    "finalize":        {"input": [{"type": "string"}],                     "output": [{"type": "string"}]},
}


def get_registered_packages() -> set:
    try:
        body = json.dumps({"query": "{ packages { name } }"}).encode()
        req = urllib.request.Request(
            f"http://{settings.BRANE_API_URL}/graphql",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return {p["name"] for p in data["data"]["packages"]}
    except Exception as exc:
        print(f"  WARNING: could not query registry ({exc}) — will build regardless")
        return set()


def build_and_push_package(pkg_id: str, brane_name: str) -> bool:
    registered = get_registered_packages()
    if brane_name in registered:
        print(f"  {brane_name} already in registry — skipping build")
        return True

    pkg_dir = PACKAGES_DIR / pkg_id
    branelet_src = settings.BRANELET_PATH or "bin/branelet"
    shutil.copy(branelet_src, pkg_dir / "branelet")

    dockerfile = pkg_dir / "Dockerfile"
    if not dockerfile.exists():
        dockerfile.write_text(
            "FROM python:3.10-slim\n\n"
            "RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \\\n"
            "    --allow-change-held-packages --allow-downgrades fuse iptables\n\n"
            "ADD branelet /branelet\n"
            "RUN chmod +x /branelet\n\n"
            "RUN mkdir -p /opt/wd\n"
            "COPY package.py /opt/wd/package.py\n"
            "COPY run.sh /opt/wd/run.sh\n"
            "RUN chmod +x /opt/wd/run.sh\n\n"
            "COPY container.yml /opt/wd/container.yml\n\n"
            "WORKDIR /opt/wd\n"
            'ENTRYPOINT ["/branelet"]\n'
        )

    builder = PackageBuilder()
    result = builder.build(working_dir=pkg_dir, container_yml_path=pkg_dir / "container.yml")
    if not result.success:
        print(f"  ERROR: build failed: {result.stderr}")
        return False

    if not builder.push(package_name=brane_name):
        print(f"  ERROR: push failed")
        return False

    print(f"  Built and pushed {brane_name}")
    return True


def register_datasets(pkg: dict) -> bool:
    pairs = []
    if pkg["p1_dataset"]:
        pairs.append((pkg["p1_dataset"], DATASETS_DIR / f"participant_1_{pkg['pkg_id']}.csv"))
    if pkg["p3_dataset"]:
        pairs.append((pkg["p3_dataset"], DATASETS_DIR / f"participant_3_{pkg['pkg_id']}.csv"))

    for dataset_name, csv_source in pairs:
        destination = settings.brane_data_dir / dataset_name / "dataset.csv"
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(csv_source, destination)
            print(f"  Copied {csv_source.name} → {destination}")
        try:
            _register_dataset(dataset_name)
            print(f"  Registered {dataset_name}")
        except RuntimeError as exc:
            if "already exists" in str(exc):
                print(f"  {dataset_name} already registered — OK")
            else:
                print(f"  ERROR: {exc}")
                return False
    return True


def check_schema_and_types(pkg: dict) -> tuple:
    container_yml_path = PACKAGES_DIR / pkg["pkg_id"] / "container.yml"
    data = yaml.safe_load(container_yml_path.read_text())
    required_keys = {"name", "version", "kind", "entrypoint", "actions"}
    actions = data.get("actions", {})
    schema_valid = (
        required_keys.issubset(set(data.keys()))
        and data.get("kind") == "ecu"
        and all(isinstance(s.get("input"), list) and isinstance(s.get("output"), list)
                for s in actions.values())
    )
    expected = {k: v for k, v in EXPECTED_ACTION_TYPES.items() if k in actions}
    correct = total = 0
    for action_name, spec in expected.items():
        for i, exp in enumerate(spec["input"]):
            total += 1
            actual = actions[action_name].get("input", [])[i].get("type", "") if i < len(actions[action_name].get("input", [])) else ""
            correct += (actual.lower() == exp["type"].lower() if exp["type"].lower() == "string" else actual == exp["type"])
        for i, exp in enumerate(spec["output"]):
            total += 1
            actual = actions[action_name].get("output", [])[i].get("type", "") if i < len(actions[action_name].get("output", [])) else ""
            correct += (actual.lower() == exp["type"].lower() if exp["type"].lower() == "string" else actual == exp["type"])
    return schema_valid, round(correct / total, 4) if total > 0 else 1.0


def build_config(pkg: dict) -> tuple:
    project = ProjectBlock(
        project_id=1,
        study_objective="Federated analysis over distributed clinical data",
        data_sensitivity="High",
        legal_basis="consent",
    )
    workflow = WorkflowSpec(
        package=pkg["brane_name"],
        local_function=pkg["local_fn"],
        combine_function=pkg["combine_fn"],
        coordinator_node="coordinator-1",
        finalize_function=pkg["finalize_fn"],
    )
    participants = [
        ParticipantPolicy(user_id=1, brane_node="participant-1", dataset_name=pkg["p1_dataset"],
                          identifiability="Pseudonymized", jurisdictions=["EU"]),
    ]
    if pkg["p3_dataset"]:
        participants.append(
            ParticipantPolicy(user_id=3, brane_node="participant-3", dataset_name=pkg["p3_dataset"],
                              identifiability="Anonymized", jurisdictions=["EU"])
        )
    config = IntegratorConfig(project=project, workflow=workflow, participants=participants)
    return config, PolicyInterpreter().interpret(config)


def main():
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    has_llm = bool(os.environ.get("OPENAI_API_KEY"))
    llm_service = None
    if has_llm:
        from app.infrastructure.llm_service import OpenAILlmService
        from app.application.workflow_generation.strategy.llm_generator import LlmGenerator
        llm_service = OpenAILlmService()
        print("LLM generation: ENABLED")
    else:
        print("LLM generation: DISABLED (OPENAI_API_KEY not set)")

    summary = {}

    for pkg in PACKAGES:
        pkg_id = pkg["pkg_id"]
        print(f"\n{'='*60}")
        print(f"{pkg_id} ({pkg['brane_name']})")
        print(f"{'='*60}")

        entry = {
            "brane_name": pkg["brane_name"],
            "package_built": False,
            "datasets_registered": False,
            "m4_6_schema_valid": False,
            "m4_5_type_accuracy": 0.0,
            "template_script": None,
            "llm_script": None,
        }

        print("\n[1] Build + push package")
        entry["package_built"] = build_and_push_package(pkg_id, pkg["brane_name"])

        print("\n[2] Register datasets")
        entry["datasets_registered"] = register_datasets(pkg)

        print("\n[3] Schema + type accuracy")
        schema_valid, type_accuracy = check_schema_and_types(pkg)
        entry["m4_6_schema_valid"] = schema_valid
        entry["m4_5_type_accuracy"] = type_accuracy
        print(f"  M4.6 schema_valid={schema_valid}  M4.5 type_accuracy={type_accuracy}")

        print("\n[4] Generate BraneScript")
        config, interpreted = build_config(pkg)

        try:
            template_bs = TemplateGenerator().generate(config, interpreted)
            out = GENERATED_DIR / f"{pkg_id}_template.bs"
            out.write_text(template_bs)
            entry["template_script"] = str(out)
            print(f"  Template → {out.name} ({len(template_bs)} chars)")
        except Exception as exc:
            print(f"  Template ERROR: {exc}")

        if llm_service:
            try:
                from app.application.workflow_generation.strategy.llm_generator import LlmGenerator
                container_yml_str = (PACKAGES_DIR / pkg_id / "container.yml").read_text()
                llm_bs = LlmGenerator(llm_service).generate(config, interpreted, container_yml=container_yml_str)
                out = GENERATED_DIR / f"{pkg_id}_llm.bs"
                out.write_text(llm_bs)
                entry["llm_script"] = str(out)
                print(f"  LLM     → {out.name} ({len(llm_bs)} chars)")
            except Exception as exc:
                print(f"  LLM ERROR: {exc}")
        else:
            print("  LLM     → SKIPPED")

        summary[pkg_id] = entry

    out_path = RESULTS_DIR / "prepare_summary.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for pkg_id, e in summary.items():
        print(f"\n{pkg_id} ({e['brane_name']}):")
        print(f"  package_built={e['package_built']}  datasets={e['datasets_registered']}")
        print(f"  M4.6={e['m4_6_schema_valid']}  M4.5={e['m4_5_type_accuracy']}")
        print(f"  template={Path(e['template_script']).name if e['template_script'] else 'FAILED'}")
        print(f"  llm={'SKIPPED' if not llm_service else (Path(e['llm_script']).name if e['llm_script'] else 'FAILED')}")

    print(f"\nScripts saved to: {GENERATED_DIR}")
    print(f"Summary: {out_path}")


if __name__ == "__main__":
    main()
