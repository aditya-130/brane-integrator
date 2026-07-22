import os, json, csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        category_counts = {}
        with open(path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
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

        combined = {}
        # Combine the category counts from both results
        for category, count in result_1.items():
            if category in combined:
                combined[category] += count
            else:
                combined[category] = count
        for category, count in result_2.items():
            if category in combined:
                combined[category] += count
            else:
                combined[category] = count

        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))
        total = sum(accumulated.values())

        rates = {category: count / total for category, count in accumulated.items()}

        result = {
            "counts": accumulated,
            "rates": rates,
            "total": total
        }
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
