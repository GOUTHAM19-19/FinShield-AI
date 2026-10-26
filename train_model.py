
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

# Project paths
BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = BASE_DIR / "ml"
MODEL_PATH = MODEL_DIR / "fraud_model.joblib"

# Reproducible synthetic demonstration data
rng = np.random.default_rng(42)
n_samples = 5000

amount = rng.lognormal(mean=5, sigma=1.2, size=n_samples)
transactions_last_hour = rng.poisson(1.5, size=n_samples)
is_new_payee = rng.binomial(1, 0.25, size=n_samples)
unusual_hour = rng.binomial(1, 0.15, size=n_samples)
account_age_days = rng.integers(1, 2500, size=n_samples)

# Synthetic labels for demonstration only.
# These rules create a learnable example, not real-world fraud evidence.
risk_signal = (
    (amount > 30000).astype(int)
    + (transactions_last_hour >= 5).astype(int) * 2
    + is_new_payee
    + unusual_hour
    + (account_age_days < 7).astype(int)
)

fraud_probability = np.where(risk_signal >= 3, 0.75, 0.02)
fraud_probability = np.clip(
    fraud_probability + rng.normal(0, 0.01, n_samples),
    0.01,
    0.90,
)
labels = rng.binomial(1, fraud_probability)

feature_names = [
    "amount",
    "transactions_last_hour",
    "is_new_payee",
    "unusual_hour",
    "account_age_days",
]

X = np.column_stack([
    amount,
    transactions_last_hour,
    is_new_payee,
    unusual_hour,
    account_age_days,
])
y = labels

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y,
)

model = RandomForestClassifier(
    n_estimators=150,
    class_weight="balanced",
    random_state=42,
)
model.fit(X_train, y_train)

predictions = model.predict(X_test)

print("Model training completed!")
print(f"Training samples: {len(X_train)}")
print(f"Test samples: {len(X_test)}")
print("\nEvaluation on synthetic test data:")
print(classification_report(y_test, predictions, zero_division=0))
print("Confusion matrix:")
print(confusion_matrix(y_test, predictions))

joblib.dump(
    {"model": model, "feature_names": feature_names},
    MODEL_PATH,
)
print(f"\nModel saved to: {MODEL_PATH}")
print("NOTE: This is a synthetic demo model, not a validated fraud detector.")
