import os, json, csv

# Local function

def compute_local():
    try:
        # Decode the input file path
        path = json.loads(os.environ["LOCAL_DATA"])
        values = []
        
        # Read CSV file and collect values
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                values.append(float(row["value"]))
        
        # Compute sum, count, and mean
        total = sum(values)
        count = len(values)
        mean = round(total / count, 4) if count != 0 else 0
        result = {"sum": total, "count": count, "mean": mean}
        
        # Output the result, double-encoded
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        # Error handling
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# There is no need for combine_results or finalize for this task

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local}[sys.argv[1]]()
