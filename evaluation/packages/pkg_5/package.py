import os
import json
import csv


def compute_local():
    try:
        path = json.loads(os.environ["LOCAL_DATA"])
        total = 0.0
        count = 0
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += float(row["value"])
                count += 1
        result = {"sum": total, "count": count, "mean": round(total / count, 4) if count else 0.0}
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local}[sys.argv[1]]()
