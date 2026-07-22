import os
import json
import csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        gradients = [0.0]
        n_samples = 0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                x = float(row["feature"])
                y = float(row["label"])
                pred = 1.0 / (1.0 + __import__("math").exp(-x))
                gradients[0] += (pred - y) * x
                n_samples += 1
        result = {"gradients": gradients, "n_samples": n_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        combined_gradients = [
            g1 + g2
            for g1, g2 in zip(result_1["gradients"], result_2["gradients"])
        ]
        combined = {
            "gradients": combined_gradients,
            "n_samples": result_1["n_samples"] + result_2["n_samples"],
        }
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        n = accumulated["n_samples"]
        lr = 0.01
        weights = [0.0]
        if n > 0:
            avg_gradients = [g / n for g in accumulated["gradients"]]
            weights = [-lr * g for g in avg_gradients]
        result = {"weights": weights, "n_samples": n}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
