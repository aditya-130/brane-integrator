import os, json, csv

# Local function to compute local frequency counts of categories
def compute_local():
    try:
        # Load the file path
        path = json.loads(os.environ["LOCAL_DATA"])
        
        # Dictionary to store local counts
        local_counts = {}
        
        # Open and read the CSV file
        with open(path, newline="") as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                # Assuming the first (and only) column contains the category
                category = row[0]
                if category in local_counts:
                    local_counts[category] += 1
                else:
                    local_counts[category] = 1
        
        # Prepare the result as a double-encoded string
        print(json.dumps({"output": json.dumps(local_counts)}))
        
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Combine function to aggregate two sets of results
def combine_results():
    try:
        # Load and decode the inputs
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        # Dictionary to store combined counts
        combined_counts = result_1.copy()

        # Aggregate counts for each category
        for category, count in result_2.items():
            if category in combined_counts:
                combined_counts[category] += count
            else:
                combined_counts[category] = count

        # Prepare the combined result as a double-encoded string
        print(json.dumps({"output": json.dumps(combined_counts)}))
        
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Finalize function which computes the final histogram and rates
def finalize():
    try:
        # Load and decode the accumulated results
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))

        # Calculate the total count
        total = sum(accumulated.values())

        # Calculate rates
        rates = {category: count / total for category, count in accumulated.items()}

        # Prepare the final result
        result = {
            "counts": accumulated,
            "rates": rates,
            "total": total
        }

        # Prepare the final result as a double-encoded string
        print(json.dumps({"output": json.dumps(result)}))
        
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))

# Dispatch block
if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()