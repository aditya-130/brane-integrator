import os
import json
import csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        count = 0
        mean = 0.0
        M2 = 0.0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                x = float(row["value"])
                count += 1
                delta = x - mean
                mean += delta / count
                delta2 = x - mean
                M2 += delta * delta2
        result = {"count": count, "mean": mean, "M2": M2}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        r1 = json.loads(json.loads(os.environ["RESULT_1"]))
        r2 = json.loads(json.loads(os.environ["RESULT_2"]))
        n1, mean1, M2_1 = r1["count"], r1["mean"], r1["M2"]
        n2, mean2, M2_2 = r2["count"], r2["mean"], r2["M2"]
        n = n1 + n2
        if n == 0:
            combined = {"count": 0, "mean": 0.0, "M2": 0.0}
        else:
            delta = mean2 - mean1
            mean = (n1 * mean1 + n2 * mean2) / n
            M2 = M2_1 + M2_2 + delta * delta * n1 * n2 / n
            combined = {"count": n, "mean": mean, "M2": M2}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        count = accumulated["count"]
        variance = accumulated["M2"] / count if count > 1 else 0.0
        result = {"variance": round(variance, 6), "mean": round(accumulated["mean"], 6), "count": count}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
