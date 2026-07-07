import os, json, csv
import math

def sigmoid(x):
    return 1 / (1 + math.exp(-x))

def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        gradients = 0.0
        n_samples = 0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                feature = float(row["feature"])
                label = int(row["label"])
                # Calculate the gradient component based on the logistic function
                prediction = sigmoid(feature)
                gradients += (prediction - label) * feature
                n_samples += 1
        result = {"gradients": [gradients], "n_samples": n_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        combined_gradients = [g1 + g2 for g1, g2 in zip(result_1["gradients"], result_2["gradients"])]
        combined_n_samples = result_1["n_samples"] + result_2["n_samples"]
        combined = {"gradients": combined_gradients, "n_samples": combined_n_samples}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        total_gradient = accumulated["gradients"][0]
        total_samples = accumulated["n_samples"]
        if total_samples == 0:
            final_weights = 0.0
        else:
            # Divide the accumulated gradient by the total number of samples and apply the learning rate
            gradient_step = (total_gradient / total_samples) * 0.01
            final_weights = -gradient_step  # Apply gradient descent step
        result = {"weights": [final_weights], "n_samples": total_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
