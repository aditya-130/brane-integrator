import os, json, csv


def compute_local():
    try:
        # Load the local data file path
        path = json.loads(os.environ["LOCAL_DATA"])
        
        # Dictionary to store age sums and counts per cancer type
        cancer_ages = {}
        
        # Read the CSV file
        with open(path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                cancer_type = row["cancer_type"]
                age = float(row["age"])
                if cancer_type not in cancer_ages:
                    cancer_ages[cancer_type] = {"count": 0, "age_sum": 0.0}
                cancer_ages[cancer_type]["count"] += 1
                cancer_ages[cancer_type]["age_sum"] += age

        # Prepare the result as double-encoded JSON
        result = json.dumps(cancer_ages)  # Double-encode here
        print(json.dumps({"output": result}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        # Load the two JSON-encoded intermediate results
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        # Dictionary to store combined results
        combined = {}

        # Helper function to merge results
        def merge_results(res1, res2):
            for cancer_type, data in res2.items():
                if cancer_type in res1:
                    res1[cancer_type]["count"] += data["count"]
                    res1[cancer_type]["age_sum"] += data["age_sum"]
                else:
                    res1[cancer_type] = data

        # Combine the results
        merge_results(combined, result_1)
        merge_results(combined, result_2)

        # Prepare the result as double-encoded JSON
        result = json.dumps(combined)  # Double-encode here
        print(json.dumps({"output": result}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        # Load the accumulated result
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))

        # Calculate the average age per cancer type
        result = {
            cancer_type: {"mean_age": data["age_sum"] / data["count"] if data["count"] > 0 else 0}
            for cancer_type, data in accumulated.items()
        }
        
        # Prepare the final result as double-encoded JSON
        final_result = json.dumps(result)  # Double-encode here
        print(json.dumps({"output": final_result}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()