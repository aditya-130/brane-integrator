import os, json, csv
import math

# Sigmoid function
def sigmoid(x):
    return 1 / (1 + math.exp(-x))

# Local function to compute gradients
def compute_local():
    try:
        path = json.loads(os.environ['LOCAL_DATA'])  # Data type: MUST json.loads
        gradients = 0.0
        n_samples = 0
        with open(path, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                feature = float(row['feature'])
                label = int(row['label'])
                prediction = sigmoid(feature)
                gradients += (prediction - label) * feature
                n_samples += 1
        result = {"gradients": [gradients], "n_samples": n_samples}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Combine function to accumulate results
def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ['RESULT_1']))
        result_2 = json.loads(json.loads(os.environ['RESULT_2']))

        combined_gradients = [g1 + g2 for g1, g2 in zip(result_1['gradients'], result_2['gradients'])]
        combined_n_samples = result_1['n_samples'] + result_2['n_samples']

        combined = {"gradients": combined_gradients, "n_samples": combined_n_samples}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Finalize function to compute logistic regression weights
def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ['ACCUMULATOR']))

        total_gradients = accumulated['gradients']
        total_n_samples = accumulated['n_samples']
        learning_rate = 0.01

        if total_n_samples == 0:
            result = {"weights": [0.0], "n_samples": total_n_samples}
        else:
            weights = [-learning_rate * (g / total_n_samples) for g in total_gradients]
            result = {"weights": weights, "n_samples": total_n_samples}

        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()