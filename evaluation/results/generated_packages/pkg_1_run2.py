import os, json, csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        results = {}
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cancer_type = row["cancer_type"]
                age = float(row["age"])
                if cancer_type not in results:
                    results[cancer_type] = {"count": 0, "age_sum": 0}
                results[cancer_type]["count"] += 1
                results[cancer_type]["age_sum"] += age

        # Double-encode the result
        print(json.dumps({"output": json.dumps(results)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        combined = {}
        for r in [result_1, result_2]:
            for cancer_type, stats in r.items():
                if cancer_type not in combined:
                    combined[cancer_type] = {"count": 0, "age_sum": 0}
                combined[cancer_type]["count"] += stats["count"]
                combined[cancer_type]["age_sum"] += stats["age_sum"]

        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        final_result = {}
        for cancer_type, stats in accumulated.items():
            if stats["count"] > 0:
                mean_age = stats["age_sum"] / stats["count"]
            else:
                mean_age = 0  # Avoid division by zero
            final_result[cancer_type] = {"mean_age": round(mean_age, 2)}

        print(json.dumps({"output": json.dumps(final_result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
