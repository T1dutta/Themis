import os
from dotenv import load_dotenv
load_dotenv()

import json
import pandas as pd
from flask import Flask, request, jsonify
from flask_cors import CORS
from fairlearn.metrics import demographic_parity_difference, equalized_odds_difference
from google import genai
from firebase_functions import https_fn

app = Flask(__name__)
CORS(app, origins=[
    "https://themis-179.web.app",
    "https://themis-179.firebaseapp.com",
])


def _analyse_logic():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        df = pd.read_csv(request.files["file"])

        protected_cols_str = (
            request.form.get("protected_cols")
            or request.form.get("protected_col")
            or ""
        ).strip()

        if not protected_cols_str:
            return jsonify({"error": "No protected column(s) provided"}), 400

        cols = [c.strip() for c in protected_cols_str.split(",") if c.strip()]

        outcome_col = (request.form.get("outcome_col") or "").strip()
        if not outcome_col:
            return jsonify({"error": "No outcome column provided"}), 400

        for col in cols:
            if col not in df.columns:
                return jsonify({"error": f"Column '{col}' not found in CSV"}), 400

        if outcome_col not in df.columns:
            return jsonify({"error": "Outcome column not found"}), 400

        outcome_series = df[outcome_col]
        if pd.api.types.is_numeric_dtype(outcome_series):
            y = outcome_series.astype(int)
        else:
            unique_vals = sorted(outcome_series.dropna().unique().tolist())
            if len(unique_vals) != 2:
                return jsonify({
                    "error": (
                        f"Outcome column '{outcome_col}' must have exactly 2 unique "
                        f"values. Found: {unique_vals}"
                    )
                }), 400
            mapping = {unique_vals[0]: 0, unique_vals[1]: 1}
            y = outcome_series.map(mapping).astype(int)

        df = df.copy()
        for col in cols:
            if col.lower() == "age" and pd.api.types.is_numeric_dtype(df[col]):
                def age_bucket(val):
                    if pd.isna(val):
                        return None
                    val = float(val)
                    if val <= 25:   return "Under 25"
                    elif val <= 35: return "26-35"
                    elif val <= 45: return "36-45"
                    elif val <= 55: return "46-55"
                    elif val <= 65: return "56-65"
                    else:           return "Over 65"
                df[col] = df[col].apply(age_bucket)

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

            dpd_score = abs(demographic_parity_difference(
                y_true=y_clean, y_pred=y_clean, sensitive_features=col_series
            ))
            eod_score = abs(equalized_odds_difference(
                y_true=y_clean, y_pred=y_clean, sensitive_features=col_series
            ))
            rounded_rates = {k: round(v, 4) for k, v in approval_rates.items()}

            for metric_name, score in [
                ("demographic_parity_difference", dpd_score),
                ("equalized_odds_difference", eod_score),
            ]:
                metrics.append({
                    "attribute": col,
                    "metric_name": metric_name,
                    "score": round(float(score), 4),
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


def _explain_logic():
    try:
        body = request.get_json(force=True)
        metrics = body.get("metrics", [])

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a fairness consultant for Themis, an AI bias detection platform. Write a report for a non-technical HR manager.

Bias metrics detected:
{json.dumps(metrics, indent=2)}

Structure your response exactly as:

SEVERITY: [CRITICAL if any score > 0.2 | WARNING if 0.1-0.2 | COMPLIANT if all below 0.1]

FINDINGS:
One sentence per attribute explaining real-life impact.

RECOMMENDED ACTIONS:
Exactly 3 concrete, specific actions to reduce bias.

Keep under 350 words."""

        models_to_try = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
        last_error = None
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(model=model_name, contents=prompt)
                return jsonify({"explanation": response.text})
            except Exception as model_err:
                last_error = str(model_err)
                continue

        return jsonify({
            "error": "AI explanation unavailable — quota exceeded. Bias metrics above are still accurate."
        }), 503

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Firebase Cloud Functions entry points ─────────────────────────────────────
@https_fn.on_request(cors=https_fn.options.CorsOptions(
    cors_origins=["https://themis-179.web.app", "https://themis-179.firebaseapp.com"],
    cors_methods=["POST", "OPTIONS"],
))
def analyse(req: https_fn.Request) -> https_fn.Response:
    with app.test_request_context(
        path="/analyse",
        method=req.method,
        data=req.form,
        content_type=req.content_type,
        environ_base=req.environ,
    ):
        # Re-route through the app context
        return app.full_dispatch_request()


@https_fn.on_request(cors=https_fn.options.CorsOptions(
    cors_origins=["https://themis-179.web.app", "https://themis-179.firebaseapp.com"],
    cors_methods=["POST", "OPTIONS"],
))
def explain(req: https_fn.Request) -> https_fn.Response:
    with app.test_request_context(
        path="/explain",
        method=req.method,
        data=req.get_data(),
        content_type=req.content_type,
    ):
        return app.full_dispatch_request()


# ── Local dev server ──────────────────────────────────────────────────────────
app.add_url_rule("/analyse", view_func=_analyse_logic, methods=["POST"])
app.add_url_rule("/explain", view_func=_explain_logic, methods=["POST"])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
