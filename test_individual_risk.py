import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.individual_risk import assess_transaction
from backend.main import app


class IndividualRiskTests(unittest.TestCase):
    @staticmethod
    def _transaction(**values):
        values.setdefault("usual_transactions_per_hour", None)
        return SimpleNamespace(**values)

    def test_usual_amount_baseline_changes_amount_signal(self):
        transaction = {
            "amount": 12000,
            "transactions_last_hour": 0,
            "is_new_payee": False,
            "unusual_hour": False,
            "account_age_days": 365,
            "usual_transaction_amount": 1000,
        }
        with_baseline = assess_transaction(self._transaction(**transaction))
        without_baseline = assess_transaction(self._transaction(**{
            **transaction,
            "usual_transaction_amount": None,
        }))

        amount_signal = next(
            signal for signal in with_baseline["signals"]
            if signal["key"] == "amount"
        )
        self.assertEqual(amount_signal["points"], 30)
        self.assertEqual(with_baseline["risk_score"], 30)
        self.assertEqual(without_baseline["risk_score"], 8)
        self.assertEqual(with_baseline["context_confidence"], 90)
        self.assertEqual(without_baseline["context_confidence"], 80)

    def test_personal_amount_baseline_replaces_broad_amount_bands(self):
        transaction = self._transaction(
            amount=95000,
            transactions_last_hour=0,
            is_new_payee=False,
            unusual_hour=False,
            account_age_days=365,
            usual_transaction_amount=95000,
        )
        personalized = assess_transaction(transaction)
        without_baseline = assess_transaction(self._transaction(
            amount=95000,
            transactions_last_hour=0,
            is_new_payee=False,
            unusual_hour=False,
            account_age_days=365,
            usual_transaction_amount=None,
        ))

        self.assertEqual(personalized["risk_score"], 0)
        self.assertEqual(without_baseline["risk_score"], 22)

    def test_personal_frequency_baseline_replaces_broad_frequency_bands(self):
        transaction = {
            "amount": 1000,
            "transactions_last_hour": 6,
            "is_new_payee": False,
            "unusual_hour": False,
            "account_age_days": 365,
            "usual_transaction_amount": None,
            "usual_transactions_per_hour": 6,
        }
        personalized = assess_transaction(self._transaction(**transaction))
        without_baseline = assess_transaction(self._transaction(**{
            **transaction,
            "usual_transactions_per_hour": None,
        }))
        frequency_signal = next(
            signal for signal in personalized["signals"]
            if signal["key"] == "frequency"
        )

        self.assertEqual(frequency_signal["points"], 0)
        self.assertIn("1.0× baseline", frequency_signal["explanation"])
        self.assertEqual(personalized["risk_score"], 0)
        self.assertEqual(without_baseline["risk_score"], 18)
        self.assertEqual(personalized["context_confidence"], 90)

    def test_combined_indicators_are_additive_and_explained(self):
        result = assess_transaction(self._transaction(
            amount=60000,
            transactions_last_hour=6,
            is_new_payee=True,
            unusual_hour=True,
            account_age_days=5,
            usual_transaction_amount=1000,
            usual_transactions_per_hour=1.5,
        ))

        self.assertEqual(result["risk_score"], 96)
        self.assertEqual(result["risk_level"], "High")
        self.assertEqual(
            result["risk_score"],
            min(100, sum(signal["points"] for signal in result["signals"])),
        )
        self.assertTrue(any(
            signal["key"] == "amount_frequency" and signal["points"] == 8
            for signal in result["signals"]
        ))
        self.assertGreaterEqual(len(result["reasons"]), 5)

    def test_low_risk_is_not_described_as_safe_or_as_probability(self):
        result = assess_transaction(self._transaction(
            amount=100,
            transactions_last_hour=0,
            is_new_payee=False,
            unusual_hour=False,
            account_age_days=1000,
            usual_transaction_amount=500,
        ))

        self.assertEqual(result["risk_level"], "Informational")
        self.assertEqual(result["risk_score"], 0)
        self.assertFalse(any(signal["triggered"] for signal in result["signals"]))
        self.assertNotIn("probability", result)
        self.assertIn("not a calibrated probability", result["disclaimer"])

    def test_prediction_api_accepts_optional_personal_baseline(self):
        client = TestClient(app)
        response = client.post("/predict", json={
            "amount": 12000,
            "transactions_last_hour": 3,
            "is_new_payee": True,
            "unusual_hour": False,
            "account_age_days": 90,
            "usual_transaction_amount": 1500,
            "usual_transactions_per_hour": 2,
        })

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertIn("signals", result)
        self.assertIn("context_confidence", result)
        self.assertEqual(result["context_confidence"], 100)
        self.assertEqual(result["risk_score"], 50)

    def test_prediction_api_rejects_non_positive_baseline(self):
        client = TestClient(app)
        response = client.post("/predict", json={
            "amount": 1000,
            "transactions_last_hour": 0,
            "is_new_payee": False,
            "unusual_hour": False,
            "account_age_days": 90,
            "usual_transaction_amount": 0,
        })

        self.assertEqual(response.status_code, 422)

    def test_prediction_api_rejects_non_positive_frequency_baseline(self):
        client = TestClient(app)
        response = client.post("/predict", json={
            "amount": 1000,
            "transactions_last_hour": 0,
            "is_new_payee": False,
            "unusual_hour": False,
            "account_age_days": 90,
            "usual_transactions_per_hour": 0,
        })

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
