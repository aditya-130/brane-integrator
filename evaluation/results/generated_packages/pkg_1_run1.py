import os, json, csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        results = {}
        with open(path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                cancer_type = row["cancer_type"]
                age = float(row["age"])
                if cancer_type not in results:
                    results[cancer_type] = {"count": 0, "age_sum": 0.0}
                results[cancer_type]["count"] += 1
                results[cancer_type]["age_sum"] += age
        print(json.dumps({"output": json.dumps(results)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))
        combined = {}

        # Process first result
        for cancer_type, data in result_1.items():
            if cancer_type not in combined:
                combined[cancer_type] = {"count": 0, "age_sum": 0.0}
            combined[cancer_type]["count"] += data["count"]
            combined[cancer_type]["age_sum"] += data["age_sum"]

        # Process second result
        for cancer_type, data in result_2.items():
            if cancer_type not in combined:
                combined[cancer_type] = {"count": 0, "age_sum": 0.0}
            combined[cancer_type]["count"] += data["count"]
            combined[cancer_type]["age_sum"] += data["age_sum"]

        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        final_result = {}

        for cancer_type, data in accumulated.items():
            if data["count"] > 0:
                mean_age = data["age_sum"] / data["count"]
                final_result[cancer_type] = {"mean_age": mean_age}
            else:
                final_result[cancer_type] = {"mean_age": None}

        print(json.dumps({"output": json.dumps(final_result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
