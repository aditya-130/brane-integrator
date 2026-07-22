import os, json, csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        category_counts = {}
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = row["category"]
                if category in category_counts:
                    category_counts[category] += 1
                else:
                    category_counts[category] = 1
        # Double-encode the result
        print(json.dumps({"output": json.dumps(category_counts)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        combined_counts = {}
        for category in set(result_1) | set(result_2):
            combined_counts[category] = result_1.get(category, 0) + result_2.get(category, 0)

        # Double-encode the result
        print(json.dumps({"output": json.dumps(combined_counts)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        total_count = sum(accumulated.values())
        rates = {category: count / total_count for category, count in accumulated.items()}
        final_result = {"counts": accumulated, "rates": rates, "total": total_count}

        # Double-encode the result
        print(json.dumps({"output": json.dumps(final_result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()