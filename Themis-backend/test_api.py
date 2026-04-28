import pandas as pd
import json
import requests
import io

print("=== Themis API Test ===\n")

# Load 500 rows for a quick test
df = pd.read_csv("adult_income_clean.csv").head(500)
print(f"CSV columns: {list(df.columns)}")
print(f"CSV shape  : {df.shape}\n")

# --- Test /analyse ---
buf = io.BytesIO()
df.to_csv(buf, index=False)
buf.seek(0)

print("Testing /analyse endpoint...")
resp = requests.post(
    "http://localhost:8080/analyse",
    files={"file": ("test.csv", buf, "text/csv")},
    data={"protected_cols": "gender,race", "outcome_col": "decision"},
)
data = resp.json()

if data.get("error"):
    print("ANALYSE ERROR:", data["error"])
else:
    print(f"SUCCESS - total_rows: {data['total_rows']}")
    for m in data["metrics"]:
        attr  = m["attribute"]
        name  = m["metric_name"]
        score = m["score"]
        print(f"  {attr} | {name} | score={score}")

    # --- Test /explain ---
    print("\nTesting /explain endpoint...")
    exp_resp = requests.post(
        "http://localhost:8080/explain",
        json={"metrics": data["metrics"]},
        headers={"Content-Type": "application/json"},
    )
    exp_data = exp_resp.json()
    if exp_data.get("error"):
        print("EXPLAIN ERROR:", exp_data["error"])
    else:
        print("EXPLAIN SUCCESS - first 300 chars of explanation:")
        print(exp_data["explanation"][:300])

print("\n=== Test Complete ===")
