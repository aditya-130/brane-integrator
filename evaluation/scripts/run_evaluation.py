"""
run_evaluation.py

Reads pre-generated BraneScript files from evaluation/results/generated/
and runs each one on live Brane. Compares results to baselines.
"""

import sys
import os
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
os.environ.setdefault("BRANE_INTEGRATOR_API_KEY", "eval")

from app.infrastructure.settings import settings

EVAL_DIR = Path(__file__).parent.parent
GENERATED_DIR = EVAL_DIR / "results" / "generated"
RESULTS_DIR = EVAL_DIR / "results"
BRANE_CLI = settings.BRANE_CLI_PATH or "brane"
TIMEOUT = 2400

PACKAGES = ["pkg_1", "pkg_2", "pkg_3", "pkg_4", "pkg_5"]
PKG5 = "pkg_5"


def run_script(bs_path: Path) -> tuple:
    """Strip policy annotations, run brane, return (success, result, latency_ms, error)."""
    raw = bs_path.read_text()
    executable = "\n".join(
        line for line in raw.splitlines()
        if not line.startswith("#[tag(") and not line.startswith("#![wf_tag(")
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".bs", delete=False) as f:
        f.write(executable)
        tmpfile = f.name

    start = time.time()
    proc = subprocess.Popen(
        [BRANE_CLI, "workflow", "run", "--remote", "central", tmpfile],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        os.unlink(tmpfile)
        return False, None, int((time.time() - start) * 1000), "timed out"
    finally:
        try:
            os.unlink(tmpfile)
        except FileNotFoundError:
            pass

    latency_ms = int((time.time() - start) * 1000)
    match = re.search(r"Workflow returned value '(.+)'", stdout)
    if proc.returncode == 0 and match:
        try:
            return True, json.loads(match.group(1)), latency_ms, None
        except json.JSONDecodeError as exc:
            return False, None, latency_ms, f"JSON parse error: {exc}"

    error = stderr.strip() or stdout.strip() or "no output"
    return False, None, latency_ms, error


def compare(a, b):
    if type(a) != type(b):
        return False, "type mismatch"
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False, f"key mismatch: {set(a.keys())} vs {set(b.keys())}"
        for k in a:
            ok, reason = compare(a[k], b[k])
            if not ok:
                return False, f"{k}: {reason}"
        return True, "equal"
    if isinstance(a, (int, float)):
        return abs(a - b) <= 1e-6, f"diff={abs(a - b)}"
    return a == b, f"{a!r} != {b!r}"


def run_one(pkg_id: str, label: str, baseline) -> dict:
    bs_path = GENERATED_DIR / f"{pkg_id}_{label}.bs"
    if not bs_path.exists():
        print(f"  {label}: MISSING {bs_path.name}")
        return {"branescript_generated": False, "execution_success": False, "numerical_match": False, "latency_ms": 0, "error": "script file missing"}

    print(f"  {label}: running {bs_path.name} ...")
    success, result, latency_ms, error = run_script(bs_path)

    entry = {"branescript_generated": True, "execution_success": success, "numerical_match": False, "latency_ms": latency_ms}

    if success and result is not None:
        if pkg_id == PKG5:
            print(f"  {label}: OK ({latency_ms}ms) — pkg_5 intentional mismatch (single participant vs pooled baseline)")
            entry["numerical_match"] = None
            entry["note"] = "pkg_5: single-participant result vs pooled baseline — intentional mismatch"
            entry["live_result"] = result
        else:
            ok, reason = compare(result, baseline)
            entry["numerical_match"] = ok
            if ok:
                print(f"  {label}: PASS ({latency_ms}ms)")
            else:
                print(f"  {label}: FAIL — {reason} ({latency_ms}ms)")
                entry["mismatch_reason"] = reason
    else:
        print(f"  {label}: FAILED — {error}")
        entry["error"] = error

    return entry


def main():
    all_results = {}

    for pkg_id in PACKAGES:
        print(f"\n{'='*55}")
        print(f"{pkg_id}")
        print(f"{'='*55}")

        baseline_path = RESULTS_DIR / f"baseline_{pkg_id}.json"
        baseline = json.loads(baseline_path.read_text())["result"]

        all_results[pkg_id] = {
            "template": run_one(pkg_id, "template", baseline),
            "llm":      run_one(pkg_id, "llm",      baseline),
        }

    out = RESULTS_DIR / "e2e_results.json"
    out.write_text(json.dumps(all_results, indent=2))

    print(f"\n{'='*55}")
    print("SUMMARY")
    print(f"{'='*55}")
    for pkg_id, res in all_results.items():
        t, l = res["template"], res["llm"]
        print(f"\n{pkg_id}:")
        print(f"  template: exec={t['execution_success']}  match={t['numerical_match']}  latency={t['latency_ms']}ms")
        print(f"  llm:      exec={l['execution_success']}  match={l['numerical_match']}  latency={l['latency_ms']}ms")

    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
