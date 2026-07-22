import os, json, csv, math

# Sigmoid function
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

# Local computation function
def compute_local():
    try:
        # Load dataset path
        path = json.loads(os.environ["LOCAL_DATA"])
        feature_values = []
        labels = []
        
        # Read data
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                feature_values.append(float(row["feature"]))
                labels.append(int(row["label"]))

        # Calculate gradients
        gradients = 0
        for feature, label in zip(feature_values, labels):
            prediction = sigmoid(feature)
            gradients += (prediction - label) * feature

        n_samples = len(labels)
        result = {"gradients": [gradients], "n_samples": n_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Combination function
def combine_results():
    try:
        # Double-decode inputs
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        # Accumulate gradients and n_samples
        combined_gradient = [r1 + r2 for r1, r2 in zip(result_1["gradients"], result_2["gradients"])]
        combined_samples = result_1["n_samples"] + result_2["n_samples"]

        combined = {"gradients": combined_gradient, "n_samples": combined_samples}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Finalize function
def finalize():
    try:
        # Double-decode the accumulated result
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        # Gradient descent
        learning_rate = 0.01

        if accumulated["n_samples"] > 0:
            average_gradient = [g / accumulated["n_samples"] for g in accumulated["gradients"]]
            weights = [-learning_rate * g for g in average_gradient]
        else:
            weights = [0.0]

        result = {"weights": weights, "n_samples": accumulated["n_samples"]}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
