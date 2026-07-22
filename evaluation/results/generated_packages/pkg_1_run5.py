import os, json, csv

# Local function
# Computes sum of ages and count of patients per cancer type at each site

def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])   # Data type: MUST json.loads
        cancer_aggregates = {}

        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cancer_type = row["cancer_type"]
                age = float(row["age"])
                if cancer_type not in cancer_aggregates:
                    cancer_aggregates[cancer_type] = {"count": 0, "age_sum": 0.0}
                cancer_aggregates[cancer_type]["count"] += 1
                cancer_aggregates[cancer_type]["age_sum"] += age

        # Output the result double-encoded
        print(json.dumps({"output": json.dumps(cancer_aggregates)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


# Combine function
# Accumulates intermediate local results without finalizing

def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))   # double json.loads
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))   # double json.loads

        combined = {}

        for key in set(result_1.keys()).union(result_2.keys()):
            count1 = result_1.get(key, {}).get("count", 0)
            age_sum1 = result_1.get(key, {}).get("age_sum", 0.0)
            count2 = result_2.get(key, {}).get("count", 0)
            age_sum2 = result_2.get(key, {}).get("age_sum", 0.0)

            combined[key] = {
                "count": count1 + count2,
                "age_sum": age_sum1 + age_sum2
            }

        # Output the combined result double-encoded
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


# Finalize function
# Computes the final average age per cancer type

def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        final_result = {}

        for cancer_type, data in accumulated.items():
            mean_age = data["age_sum"] / data["count"] if data["count"] else 0
            final_result[cancer_type] = {"mean_age": round(mean_age, 2)}

        # Output the final result double-encoded
        print(json.dumps({"output": json.dumps(final_result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()