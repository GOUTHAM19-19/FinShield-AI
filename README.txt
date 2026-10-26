FINSHIELD AI — RUNNABLE HACKATHON DEMO
======================================

EASY START (Windows)
1. Extract this ZIP file completely.
2. Open the extracted finshield2 folder.
3. Double-click START_BACKEND.bat and wait for the API to start.
   The first run installs Python packages and may take a few minutes.
4. Double-click START_FRONTEND.bat in the same folder.
5. Open http://127.0.0.1:5500 in your browser.
6. Click Run Normal Scenario or Run Suspicious Scenario.
7. Scroll to Live Transaction Monitoring Lab and choose "Build sample account history" to seed a synthetic profile.
8. Submit the prefilled ₹50,000 transfer to a new recipient from Chennai to see combined amount, recipient, and location signals; review the case and save its status/notes.
9. Or import your own authorized CSV data using the supported headers listed below.
10. API documentation: http://127.0.0.1:8001/docs

REQUIREMENTS
- Windows 10/11
- Python 3.10 or newer installed and available as `py`
- Internet access for the first package installation

PROJECT STRUCTURE
backend/     FastAPI endpoints, explainable risk engine, SQLite case store, and chain detector
frontend/    Dashboard, transaction graph, and live monitoring lab
ml/          Demo model and training script
requirements.txt
START_BACKEND.bat
START_FRONTEND.bat

TRANSACTION ANALYSIS PROTOTYPE
- The monitoring lab accepts individual transactions and CSV batches; records and investigation cases persist in `data/risk_monitoring.sqlite3`. Set `FINSHIELD_RISK_DB` before startup to choose another SQLite path. Use "Clear analysis data" to remove all demo monitoring records and cases.
- CSV is limited to 5 MB and 500 rows per import and requires `sender`, `receiver`, and `amount`. Optional headers: `transaction_id`, `timestamp`, `location`, and `channel`. Aliases supported: `account_id` for sender, `counterparty_id` for receiver, `id` for transaction_id, `transaction_time` for timestamp, `city` for location, and `transaction_channel` for channel. Amounts are numeric rupee amounts. Timestamps may be ISO-8601 with timezone; when omitted, an ordered timestamp is assigned during import.
- Explainable risk indicators include an amount compared to the sender's observed median (with at least five prior events), elevated one-hour activity, first observed recipients, changed recorded locations/channels, rare observed UTC activity hours, spending shifts vs a 30-day baseline, and rapid linked transfer chains.
- Rule weights are additive and capped at 100: high amount +25; 3+ transfers/hour +12 or 5+ +20; new recipient +12; changed location +12; new channel +10; rare activity hour +10; spending shift +15; rapid sequence +25. A case is created at score 45 or for any linked rapid sequence; High is 70+. These thresholds are illustrative and configurable in `backend/risk_engine.py`, not empirically calibrated.
- Missing timestamps, location, and channel are disclosed and lower context completeness; missing fields are not directly treated as suspicious. When timestamp is absent, import order supplies a timestamp and timing checks are marked approximate. Context confidence is a completeness/history indicator, not a probability that a risk score is correct.
- Cases at or above the review threshold, and transactions in a rapid linked chain, are prioritized with reasons, supporting linked transaction IDs, status, and analyst notes. Case workflow status/notes are stored in the backend SQLite database.
- The Live Transaction Monitoring Lab includes a searchable, risk-filterable history of the 500 most recent transactions returned by the monitoring API. Expand any row to inspect its assessment reasons, heuristic score, context confidence, available location/channel, source, and connected transfer sequence.
- "Build sample account history" creates synthetic account history to demonstrate behavior comparisons. "Inject 3-transfer demo" appends a synthetic linked sequence. Only "Clear analysis data" removes the database contents.

INDIVIDUAL TRANSACTION ANALYSIS
- `/predict` uses an explainable additive rule scorer, not the bundled legacy synthetic random-forest artifact. Score components are amount +0–30, transaction frequency +0–25, new recipient +12, unusual hour +8, account age +0–8, amount/frequency interaction +8, and new-recipient/unusual-hour interaction +5; the total is capped at 100.
- Optional usual-amount and usual-transactions-per-hour baselines personalize the amount and frequency signals. When a baseline is supplied, that signal uses the observed-to-usual ratio instead of broad absolute activity bands; when absent, the scorer uses broad thresholds and explicitly says so. Both baselines give 100% context completeness, one gives 90%, and neither gives 80%. These values describe provided context, not model accuracy.
- Concern levels are Informational (0–19), Low (20–39), Medium (40–69), and High (70–100). The response lists every signal, its actual point contribution and explanation, plus input-context completeness. Completeness is not model accuracy and the score is not a probability.
- `ml/train_model.py` and `ml/fraud_model.joblib` are retained as a synthetic training experiment; the running prediction endpoint does not load or depend on them.

IMPORTANT LIMITATIONS
This is an academic prototype, not a production financial crime decision system. It does not connect to banks, verify real payment events, establish a user's identity, or automatically block payments. Risk scores are deterministic, rule-based heuristics and have not been calibrated or validated on representative labelled transactions. False-positive/false-negative performance is unknown. Location is a supplied category and is not geolocated; comparisons can reflect legitimate travel. The behavior profile is limited to transactions imported into this local prototype. Use synthetic data for demos; only use real data where authorized and protected, and use pseudonymous account IDs rather than direct identifiers or personal data. Protect the API, apply access controls, retention, audit and deployment policies before any real-data use.

TROUBLESHOOTING
- If `py` is not recognized, install Python and enable "Add Python to PATH".
- Keep both black terminal windows open while using the dashboard.
- The API uses port 8001 so another local service on port 8000 will not interfere. If port 8001 or 5500 is already in use, close the conflicting server first.

CASE PRIORITIZATION
Case priority uses the risk engine's transparent rule score and the sequence context; it is not a validated fraud probability. See tests/MANUAL_VALIDATION.txt for checks.


INDIVIDUAL TRANSACTION EXPLANATION
- After Check Transaction, the dashboard displays the exact points and explanations returned by the scoring rules (amount, transaction frequency, new recipient, unusual hour, account age, and cross-signal interactions).
- Download analysis report exports the current inputs and API result as JSON.
- Investigation case statuses (Open, Under Review, Escalated, Resolved) and notes are persisted in the backend SQLite database.
- An optional usual transaction amount enables an account-relative amount comparison. The score and thresholds remain illustrative, are not SHAP values or validated real-world fraud probabilities, and must not be used for automated financial decisions.
- The legacy XAI dashboard text elsewhere refers to the synthetic model/scenario demo; `/predict` now uses the additive rule scorer described above.

LOGIN PAGE
- Users can register a demo profile and sign in with its saved email and password. Profile data is stored in this browser's local storage; passwords are not protected by a server-side identity system.
- This is a frontend-only demo flow, not real authentication or access control. Do not use real credentials or sensitive personal information.
