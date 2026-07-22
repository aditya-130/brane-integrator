import os, json, csv

def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        values = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                values.append(float(row["value"]))
        total_sum = sum(values)
        count = len(values)
        mean = total_sum / count if count > 0 else 0
        result = {"sum": total_sum, "count": count, "mean": round(mean, 4)}
        # Double-encode: inner json.dumps makes a String, outer wraps in {"output": ...}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

def combine_results():
    # This function is intentionally left empty because the combination is not required.
    pass

def finalize():
    # This function is intentionally left empty because the finalization is not required.
    pass

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
