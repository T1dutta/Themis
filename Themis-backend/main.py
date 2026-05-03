import os
from dotenv import load_dotenv
load_dotenv()

import json
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
from fairlearn.metrics import demographic_parity_difference, equalized_odds_difference
from google import genai

app = Flask(__name__)

# ── CORS — restrict to Firebase Hosting domain in production ──────────────────
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "https://themis-179.web.app,https://themis-179.firebaseapp.com,http://localhost:5173"
).split(",")

CORS(app, origins=ALLOWED_ORIGINS)


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "Themis API running"})


@app.route("/analyse", methods=["POST"])
def analyse():
    try:
        # ── 1. Read file ──────────────────────────────────────────────────────
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        df = pd.read_csv(request.files["file"])

        # ── 2. Parse protected columns ────────────────────────────────────────
        protected_cols_str = (
            request.form.get("protected_cols")
            or request.form.get("protected_col")
            or ""
        ).strip()

        if not protected_cols_str:
            return jsonify({"error": "No protected column(s) provided"}), 400

        cols = [c.strip() for c in protected_cols_str.split(",") if c.strip()]

        # ── 3. Parse outcome column ───────────────────────────────────────────
        outcome_col = (request.form.get("outcome_col") or "").strip()
        if not outcome_col:
            return jsonify({"error": "No outcome column provided"}), 400

        # ── 4. Validate columns exist ─────────────────────────────────────────
        for col in cols:
            if col not in df.columns:
                return jsonify({"error": f"Column '{col}' not found in CSV"}), 400

        if outcome_col not in df.columns:
            return jsonify({"error": "Outcome column not found"}), 400

        # ── 5. Convert outcome to binary 0/1 ─────────────────────────────────
        outcome_series = df[outcome_col]

        if pd.api.types.is_numeric_dtype(outcome_series):
            y = outcome_series.astype(int)
        else:
            unique_vals = sorted(outcome_series.dropna().unique().tolist())
            if len(unique_vals) != 2:
                return jsonify({
                    "error": (
                        f"Outcome column '{outcome_col}' must have exactly 2 unique "
                        f"values for binary classification. Found: {unique_vals}"
                    )
                }), 400
            mapping = {unique_vals[0]: 0, unique_vals[1]: 1}
            y = outcome_series.map(mapping).astype(int)

        # ── 6. Age bucketing — convert numeric "age" column into range labels ─
        df = df.copy()
        for col in cols:
            if col.lower() == "age" and pd.api.types.is_numeric_dtype(df[col]):
                def age_bucket(val):
                    if pd.isna(val):
                        return None
                    val = float(val)
                    if val <= 25:
                        return "Under 25"
                    elif val <= 35:
                        return "26-35"
                    elif val <= 45:
                        return "36-45"
                    elif val <= 55:
                        return "46-55"
                    elif val <= 65:
                        return "56-65"
                    else:
                        return "Over 65"
                df[col] = df[col].apply(age_bucket)

        # ── 7. Compute fairness metrics per protected column ──────────────────
        metrics = []

        for col in cols:
            valid_mask = df[col].notna() & y.notna()
            col_series = df.loc[valid_mask, col]
            y_clean = y[valid_mask]

            approval_rates = {}
            for group_val in col_series.unique():
                mask = col_series == group_val
                approval_rates[str(group_val)] = float(y_clean[mask].mean())

            favored_group = max(approval_rates, key=approval_rates.get)
            disadvantaged_group = min(approval_rates, key=approval_rates.get)

            dpd_score = abs(
                demographic_parity_difference(
                    y_true=y_clean,
                    y_pred=y_clean,
                    sensitive_features=col_series
                )
            )

            eod_score = abs(
                equalized_odds_difference(
                    y_true=y_clean,
                    y_pred=y_clean,
                    sensitive_features=col_series
                )
            )

            rounded_rates = {k: round(v, 4) for k, v in approval_rates.items()}

            metrics.append({
                "attribute": col,
                "metric_name": "demographic_parity_difference",
                "score": round(float(dpd_score), 4),
                "favored_group": favored_group,
                "disadvantaged_group": disadvantaged_group,
                "approval_rates": rounded_rates,
            })

            metrics.append({
                "attribute": col,
                "metric_name": "equalized_odds_difference",
                "score": round(float(eod_score), 4),
                "favored_group": favored_group,
                "disadvantaged_group": disadvantaged_group,
                "approval_rates": rounded_rates,
            })

        return jsonify({
            "metrics": metrics,
            "target_column": outcome_col,
            "protected_columns_analysed": cols,
            "total_rows": len(df),
            "error": None,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/explain", methods=["POST"])
def explain():
    try:
        body = request.get_json(force=True)
        metrics = body.get("metrics", [])

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY environment variable not set"}), 500

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a fairness consultant for Themis, an AI bias detection platform. You are writing a report for a non-technical HR manager or business executive.

Here are the bias metrics detected in their dataset:
{json.dumps(metrics, indent=2)}

Write your response in exactly this structure:

SEVERITY: [write CRITICAL if any score > 0.2 | WARNING if any score is 0.1 to 0.2 | COMPLIANT if all scores below 0.1]

FINDINGS:
For each unique attribute found in the metrics, write one plain English sentence explaining what the bias means in real life. Example: "Women are 34% less likely to receive a positive outcome than equally qualified men."

RECOMMENDED ACTIONS:
Write exactly 3 specific actionable steps this organisation can take to reduce the detected bias. Be concrete, not generic.

Keep the entire response under 350 words."""

        models_to_try = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
        last_error = None

        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                return jsonify({"explanation": response.text})
            except Exception as model_err:
                last_error = str(model_err)
                continue

        print(f"Explain models failed. Last error: {last_error}")
        return jsonify({
            "error": "AI explanation unavailable — API quota exceeded or models unavailable. "
                     "Your bias analysis above is still accurate. "
                     "Please try again later."
        }), 503

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
