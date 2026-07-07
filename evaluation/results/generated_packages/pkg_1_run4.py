import os, json, csv

def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        # Initialize a dictionary to accumulate results per cancer type
        aggregate = {}
        
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cancer_type = row["cancer_type"]
                age = float(row["age"])

                if cancer_type not in aggregate:
                    aggregate[cancer_type] = {"count": 0, "age_sum": 0.0}

                aggregate[cancer_type]["count"] += 1
                aggregate[cancer_type]["age_sum"] += age

        # Double-encode the result
        print(json.dumps({"output": json.dumps(aggregate)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        combined = {}

        # Merge results 1 and 2
        all_cancer_types = set(result_1.keys()).union(result_2.keys())

        for cancer_type in all_cancer_types:
            count_1 = result_1.get(cancer_type, {"count": 0, "age_sum": 0.0})["count"]
            age_sum_1 = result_1.get(cancer_type, {"count": 0, "age_sum": 0.0})["age_sum"]

            count_2 = result_2.get(cancer_type, {"count": 0, "age_sum": 0.0})["count"]
            age_sum_2 = result_2.get(cancer_type, {"count": 0, "age_sum": 0.0})["age_sum"]

            combined[cancer_type] = {"count": count_1 + count_2, "age_sum": age_sum_1 + age_sum_2}

        # Double-encode the result
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        final_results = {}

        for cancer_type, data in accumulated.items():
            count = data["count"]
            age_sum = data["age_sum"]
            mean_age = age_sum / count if count > 0 else 0
            final_results[cancer_type] = {"mean_age": mean_age}

        # Double-encode the final result
        print(json.dumps({"output": json.dumps(final_results)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()