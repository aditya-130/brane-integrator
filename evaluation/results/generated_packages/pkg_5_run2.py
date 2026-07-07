import os, json, csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        values = []
        with open(path, newline="", encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                values.append(float(row["value"]))
        sum_values = sum(values)
        count_values = len(values)
        mean_values = round(sum_values / count_values, 4) if count_values > 0 else 0
        result = {"sum": sum_values, "count": count_values, "mean": mean_values}
        print(json.dumps({"output": json.dumps(result)}))  # Double-encode result
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    print(json.dumps({"output": json.dumps({"error": "Multi-site combination not applicable for single-site evaluation."})}))


def finalize():
    print(json.dumps({"output": json.dumps({"error": "Finalization not applicable for single-site evaluation."})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
