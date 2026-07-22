import os
import json
import csv


def compute_local():
    try:
        # Get the path of the local data file
        path = json.loads(os.environ["LOCAL_DATA"])
        counts = {}

        # Open and read the CSV file
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = row['category']
                # Count occurrences of each category
                if category in counts:
                    counts[category] += 1
                else:
                    counts[category] = 1

        # Double-encode the result
        print(json.dumps({"output": json.dumps(counts)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def combine_results():
    try:
        # Decode the accumulated results (double-decoding)
        result_1 = json.loads(json.loads(os.environ["RESULT_1"]))
        result_2 = json.loads(json.loads(os.environ["RESULT_2"]))

        # Combine the results from two sources
        combined = result_1.copy()

        # Sum counts from both results
        for category, count in result_2.items():
            if category in combined:
                combined[category] += count
            else:
                combined[category] = count

        # Double-encode the combined result
        print(json.dumps({"output": json.dumps(combined)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


def finalize():
    try:
        # Decode the final accumulated result
        accumulated = json.loads(json.loads(os.environ["ACCUMULATOR"]))

        # Calculate total count
        total_count = sum(accumulated.values())
        if total_count > 0:
            rates = {k: v / total_count for k, v in accumulated.items()}
        else:
            rates = {k: 0 for k in accumulated.keys()}

        # Prepare the final results
        result = {
            "counts": accumulated,
            "rates": rates,
            "total": total_count
        }

        # Double-encode the final result
        print(json.dumps({"output": json.dumps(result)}))
    except Exception as e:
        print(json.dumps({"output": json.dumps({"error": str(e)})}))


if __name__ == "__main__":
    import sys
    {"compute_local": compute_local, "combine_results": combine_results, "finalize": finalize}[sys.argv[1]]()
