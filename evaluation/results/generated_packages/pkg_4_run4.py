import os, json, csv

# Local function to compute count, mean, and M2 using Welford's method

def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        count = 0
        mean = 0.0
        M2 = 0.0
        
        # Read the data and compute using Welford's algorithm
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                count += 1
                x = float(row['value'])
                delta = x - mean
                mean += delta / count
                delta2 = x - mean
                M2 += delta * delta2
        
        # Structure the result
        result = {"count": count, "mean": mean, "M2": M2}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Combine function to merge results from two sites using parallel variance formula

def combine_results():
    try:
        # Decode the inputs
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        
        # Extract values
        n1, mean1, M2_1 = result_1["count"], result_1["mean"], result_1["M2"]
        n2, mean2, M2_2 = result_2["count"], result_2["mean"], result_2["M2"]
        
        # Combine results
        n = n1 + n2
        if n == 0:
            mean = 0.0
            M2 = 0.0
        else:
            delta = mean2 - mean1
            mean = (n1 * mean1 + n2 * mean2) / n
            M2 = M2_1 + M2_2 + delta * delta * n1 * n2 / n
        
        combined = {"count": n, "mean": mean, "M2": M2}
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Finalize function to compute the variance

def finalize():
    try:
        # Decode the accumulated result
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        count = accumulated["count"]
        mean = accumulated["mean"]
        M2 = accumulated["M2"]
        
        # Compute the variance
        if count > 1:
            variance = M2 / (count - 1)
        else:
            variance = 0
        
        result = {"variance": variance, "mean": mean, "count": count}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Dispatch block for Brane
if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()