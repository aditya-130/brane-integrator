import os
import json
import csv
from collections import defaultdict


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        counts = defaultdict(int)
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = row["category"].strip()
                counts[category] += 1
        print(json.dumps({"output": json.dumps(dict(counts))}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        combined = {}
        for category in set(result_1) | set(result_2):
            combined[category] = result_1.get(category, 0) + result_2.get(category, 0)
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        total = sum(accumulated.values())
        rates = {k: round(v / total, 4) if total else 0.0 for k, v in accumulated.items()}
        result = {"counts": accumulated, "rates": rates, "total": total}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
