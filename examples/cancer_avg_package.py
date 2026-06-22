# =============================================================================
# HOW TO WRITE A BRANE PACKAGE
# =============================================================================
#
# A Brane package is a Python file run inside a Docker container. Every package
# used by this integrator must follow these exact rules or it will fail at
# runtime.
#
# RULE 1 — THREE FUNCTIONS REQUIRED
# -----------------------------------
# Every package needs exactly three functions:
#   - compute_local()  : runs at each participant site on their local dataset
#   - combine_results(): runs at the central coordinator to merge two local results
#   - finalize()       : runs ONCE on the coordinator after all combines to produce the final answer
#
# RULE 2 — INPUTS ARRIVE AS ENVIRONMENT VARIABLES
# -------------------------------------------------
# Brane passes all inputs via os.environ. There are two input types:
#
#   a) Data (a local dataset file path):
#      Brane JSON-encodes the path, so you MUST call json.loads() once:
#        path = json.loads(os.environ["LOCAL_DATA"])
#        # now 'path' is a plain string like "/data/my-dataset"
#        with open(path) as f: ...
#
#   b) String (a computation result from another function):
#      Results are double-encoded, so you MUST call json.loads() TWICE:
#        result = json.loads(json.loads(os.environ["RESULT_1"]))
#        # first  json.loads: JSON string  -> Python string (still looks like JSON)
#        # second json.loads: Python string -> Python dict/value you can work with
#
# RULE 3 — OUTPUT MUST BE DOUBLE-ENCODED
# ----------------------------------------
# Because Brane's container.yml declares outputs as type: string (lowercase — NOT
# type: String capital S, which Brane parses as a class type and causes a runtime
# type mismatch), your output value must itself be a JSON string, not a JSON object.
# This means you call json.dumps TWICE — once on your result dict, once to wrap the envelope:
#
#   result = {"count": 10, "sum": 500.0}
#   print(json.dumps({"output": json.dumps(result)}))
#   #                           ^^^^^^^^^^^^^^^^^^^
#   #                           inner json.dumps turns the dict into a STRING first
#
#   On error:
#   print(json.dumps({"output": json.dumps({"error": str(e)})}))
#
# RULE 4 — combine_results MUST BE AN ACCUMULATOR, NOT A FINALIZER
# -----------------------------------------------------------------
# combine_results receives EXACTLY TWO inputs: RESULT_1 and RESULT_2.
# It must output the SAME structure as compute_local.
# This is because BraneScript chains combine() in a left-fold for N>2 sites:
#
#   let acc    := combine_results(local_1, local_2);  # acc has same shape as local_1
#   let result := combine_results(acc, local_3);      # works because shapes match
#
# DO NOT compute a final answer (e.g. divide sum by count to get mean) inside
# combine_results. Accumulate the partial sums only.
#
# RULE 5 — finalize() COMPUTES THE FINAL ANSWER
# -----------------------------------------------
# finalize() receives ONE input: ACCUMULATOR — the final combined result.
# It decodes it (double json.loads), then converts the accumulator into the
# human-readable final answer (e.g. divides age_sum by count to get mean age).
# This is the ONLY place division or post-processing should happen.
#
# RULE 6 — DISPATCH BLOCK
# ------------------------
# The bottom of the file must dispatch by sys.argv[1] so Brane can call each
# function by name:
#
#   if __name__ == "__main__":
#       import sys
#       {"compute_local": compute_local, "combine_results": combine_results,
#        "finalize": finalize}[sys.argv[1]]()
#
# =============================================================================

import os
import json
import csv
from collections import defaultdict


def compute_local():
    try:
        # Data input: Brane JSON-encodes the file path — must json.loads once to get plain path
        path = json.loads(os.environ["LOCAL_DATA"])

        stats = defaultdict(lambda: {
            "count": 0,
            "age_sum": 0.0
        })

        with open(path, newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                cancer_type = row["cancer_type"].strip()
                age = float(row["age"])

                stats[cancer_type]["count"] += 1
                stats[cancer_type]["age_sum"] += age

        # Output must be double-encoded: inner json.dumps makes a String, outer wraps the Brane envelope
        print(json.dumps({"output": json.dumps(dict(stats))}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        # String inputs: Brane double-encodes computation results — must json.loads twice
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        # Accumulator pattern: merge two partial stats dicts into one with the same structure.
        # Do NOT compute the final average here — that would break the left-fold for N>2 sites.
        combined = {}
        for cancer_type in set(result_1) | set(result_2):
            c1 = result_1.get(cancer_type, {"count": 0, "age_sum": 0.0})
            c2 = result_2.get(cancer_type, {"count": 0, "age_sum": 0.0})
            combined[cancer_type] = {
                "count": c1["count"] + c2["count"],
                "age_sum": c1["age_sum"] + c2["age_sum"],
            }

        # Same output structure as compute_local so the BraneScript left-fold works correctly
        print(json.dumps({"output": json.dumps(combined)}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        # Double-decode the final accumulated result
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))

        # Compute average age per cancer type from the accumulated {count, age_sum} dict
        result = {}
        for cancer_type, stats in accumulated.items():
            count = stats.get("count", 0)
            age_sum = stats.get("age_sum", 0.0)
            result[cancer_type] = round(age_sum / count, 2) if count else 0.0

        # Same double-encoded output pattern
        print(json.dumps({"output": json.dumps(result)}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys

    {
        "compute_local": compute_local,
        "combine_results": combine_results,
        "finalize": finalize,
    }[sys.argv[1]]()
