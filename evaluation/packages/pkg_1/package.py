import os
import json
import csv
from collections import defaultdict


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        stats = defaultdict(lambda: {"count": 0, "age_sum": 0.0})
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cancer_type = row["cancer_type"].strip()
                age = float(row["age"])
                stats[cancer_type]["count"] += 1
                stats[cancer_type]["age_sum"] += age
        print(json.dumps({"output": json.dumps(dict(stats))}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        combined = {}
        for cancer_type in set(result_1) | set(result_2):
            c1 = result_1.get(cancer_type, {"count": 0, "age_sum": 0.0})
            c2 = result_2.get(cancer_type, {"count": 0, "age_sum": 0.0})
            combined[cancer_type] = {
                "count": c1["count"] + c2["count"],
                "age_sum": c1["age_sum"] + c2["age_sum"],
            }
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        result = {}
        for cancer_type, stats in accumulated.items():
            count = stats.get("count", 0)
            age_sum = stats.get("age_sum", 0.0)
            result[cancer_type] = round(age_sum / count, 2) if count else 0.0
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
