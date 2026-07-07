import os, json, csv
import math

# Sigmoid function
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

# Local function to compute gradient and number of samples

def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        gradients = 0.0
        n_samples = 0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                feature = float(row["feature"])
                label = float(row["label"])
                pred = sigmoid(feature)
                gradients += (pred - label) * feature
                n_samples += 1
        result = {"gradients": [gradients], "n_samples": n_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Combine function to accumulate gradients and samples

def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        combined_gradients = [result_1["gradients"][0] + result_2["gradients"][0]]
        combined_n_samples = result_1["n_samples"] + result_2["n_samples"]
        combined = {"gradients": combined_gradients, "n_samples": combined_n_samples}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Finalize function to compute final weights

def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        gradients = accumulated["gradients"][0]
        n_samples = accumulated["n_samples"]
        learning_rate = 0.01
        weights = [gradients / n_samples * learning_rate] if n_samples != 0 else [0]
        result = {"weights": weights, "n_samples": n_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()