import os, json, csv

# Local function to compute sum, count, and mean from local data
# This is the only function required for this single-site computation
def compute_local():
    try:
        # Load the local data file path
        path = json.loads(os.environ["LOCAL_DATA"])
        values = []
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Collect numeric values assuming the column is named 'value'
                values.append(float(row["value"]))
        
        # Calculate sum, count, and mean
        total_sum = sum(values)
        count = len(values)
        mean = total_sum / count if count > 0 else 0
        
        # Create result dictionary
        result = {"sum": total_sum, "count": count, "mean": round(mean, 4)}
        # Return result as double-encoded JSON to match Brane framework requirements
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        # Return error message in case of exception
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Dispatch model of execution
if __name__ == "__main__":
    import sys
    {"compute_local": compute_local}[sys.argv[1]]()