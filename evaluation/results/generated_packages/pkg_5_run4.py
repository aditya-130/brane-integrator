import os, json, csv

def compute_local():
    try:
        # Read the local data file path from environment variables, ensuring JSON decoding
        path = json.loads(os.environ["LOCAL_DATA"])
        values = []
        
        # Open the CSV file and read the data
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                values.append(float(row["value"]))

        # Compute the sum, count, and mean of the values
        total_sum = sum(values)
        count = len(values)
        mean = total_sum / count if count > 0 else 0
        
        # Prepare the result dictionary and double encode it
        result = {"sum": total_sum, "count": count, "mean": round(mean, 4)}
        print(json.dumps({"output": json.dumps(result)}))

    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

if __name__ == "__main__":
    import sys
    {"compute_local": compute_local}[sys.argv[1]]()