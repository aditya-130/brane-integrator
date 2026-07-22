import os, json, csv

# Function to execute the Welford's algorithm locally at each hospital site
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

# Function to combine the results from two sites using the parallel variance merge formula
def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        n1, mean1, M2_1 = result_1["count"], result_1["mean"], result_1["M2"]
        n2, mean2, M2_2 = result_2["count"], result_2["mean"], result_2["M2"]

        n = n1 + n2
        delta = mean2 - mean1
        mean = (n1 * mean1 + n2 * mean2) / n
        M2 = M2_1 + M2_2 + delta**2 * n1 * n2 / n

        combined = {"count": n, "mean": mean, "M2": M2}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Function to finalize the computation to produce the variance from the accumulated result
def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        n = accumulated["count"]
        mean = accumulated["mean"]
        M2 = accumulated["M2"]

        if n > 1:
            variance = M2 / n
        else:
            variance = 0.0  # Or handle this as an error/exception in real scenarios

        result = {"variance": variance, "mean": mean, "count": n}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
