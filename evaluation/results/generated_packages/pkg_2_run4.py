import os
import json
import csv
import math

# Sigmoid function for logistic regression
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

# Local function: Calculate gradient and count sample size
# File contains: feature (numeric), label (0 or 1)
# local_function outputs: {"gradients": [g], "n_samples": N}
def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])  # Data type: MUST json.loads
        gradient = 0.0
        n_samples = 0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                feature = float(row["feature"])
                label = float(row["label"])
                prediction_error = sigmoid(feature) - label
                gradient += prediction_error * feature
                n_samples += 1
        result = {"gradients": [gradient], "n_samples": n_samples}
        # Double-encode: inner json.dumps makes it a String, outer wraps it in {"output": ...}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Combine function: Accumulate gradients and sample counts
# Input/output structure: {"gradients": [g], "n_samples": N}
def combine_results():
    try:
        # Double-decode: env var is JSON-encoded String; first json.loads gives the string, second gives the dict
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        # Summing gradients and n_samples
        combined_gradient = [g1 + g2 for g1, g2 in zip(result_1["gradients"], result_2["gradients"])]
        combined_n_samples = result_1["n_samples"] + result_2["n_samples"]
        combined = {"gradients": combined_gradient, "n_samples": combined_n_samples}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Finalize function: Compute updated weights after gradient step
# Input: Accumulated result from combine; output: {"weights": [...], "n_samples": N}
# Applies one gradient descent step to update weights with learning rate 0.01
def finalize():
    try:
        # Double-decode the accumulated result
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        learning_rate = 0.01
        # Compute average gradient
        avg_gradient = [g / accumulated["n_samples"] for g in accumulated["gradients"]] if accumulated["n_samples"] > 0 else [0]
        # Apply one gradient descent step and update weights
        weights = [-learning_rate * g for g in avg_gradient]
        result = {"weights": weights, "n_samples": accumulated["n_samples"]}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
