import csv
import random
import os

random.seed(42)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

CANCER_TYPES = ["Breast", "Lung", "Colorectal", "Prostate", "Leukemia", "Lymphoma", "Melanoma", "Pancreatic"]
CATEGORIES = ["A", "B", "C", "D", "E"]


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows)} rows → {os.path.basename(path)}")


# ---------------------------------------------------------------------------
# pkg_1 and pkg_2 share the same age/cancer_type schema
# pkg_1: federated mean age by cancer type
# pkg_2: federated logistic regression (feature, label)
# pkg_3: federated histogram (category)
# pkg_4: federated variance (value)
# pkg_5: single participant (value)
# ---------------------------------------------------------------------------

def gen_pkg1(participant_id, n=50):
    return [
        {"cancer_type": random.choice(CANCER_TYPES), "age": round(random.gauss(60, 12), 1)}
        for _ in range(n)
    ]

def gen_pkg2(participant_id, n=50):
    return [
        {"feature": round(random.gauss(0, 1), 4), "label": random.randint(0, 1)}
        for _ in range(n)
    ]

def gen_pkg3(participant_id, n=50):
    return [
        {"category": random.choice(CATEGORIES)}
        for _ in range(n)
    ]

def gen_pkg4(participant_id, n=50):
    return [
        {"value": round(random.gauss(50, 10), 4)}
        for _ in range(n)
    ]

def gen_pkg5(participant_id, n=50):
    return [
        {"value": round(random.gauss(100, 20), 4)}
        for _ in range(n)
    ]


generators = {
    "pkg_1": (gen_pkg1, ["cancer_type", "age"]),
    "pkg_2": (gen_pkg2, ["feature", "label"]),
    "pkg_3": (gen_pkg3, ["category"]),
    "pkg_4": (gen_pkg4, ["value"]),
    "pkg_5": (gen_pkg5, ["value"]),
}

print("Generating evaluation datasets...\n")

for pkg, (gen_fn, fields) in generators.items():
    print(f"{pkg}:")
    rows_p1 = gen_fn(1, n=50)
    rows_p3 = gen_fn(3, n=50)
    rows_pooled = rows_p1 + rows_p3

    write_csv(os.path.join(OUTPUT_DIR, f"participant_1_{pkg}.csv"), fields, rows_p1)
    write_csv(os.path.join(OUTPUT_DIR, f"participant_3_{pkg}.csv"), fields, rows_p3)
    write_csv(os.path.join(OUTPUT_DIR, f"pooled_{pkg}.csv"), fields, rows_pooled)
    print()

print("Done.")
print()
print("Next steps — register datasets in Brane:")
print("  For each participant CSV, copy it to the correct node data directory and run:")
print("    brane data build <dataset_name> <path_to_csv>")
print("    brane data push <dataset_name>")
print()
print("  Dataset name convention used in scenario JSONs and fixtures:")
print("    participant-1 nodes: cancer_age_s1_p1, cancer_age_s2_p1, ... (for pkg_1/pkg_2)")
print("    participant-3 nodes: cancer_age_s1_p3, cancer_age_s2_p3, ...")
print("  Use the pooled_*.csv files only for centralized_baseline.py (never pushed to Brane).")
