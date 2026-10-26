import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend import risk_engine


class RiskEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "risk.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def transaction(
        self,
        transaction_id,
        sender="ACC100",
        receiver="ACC200",
        amount=1000,
        timestamp=None,
        location="Bengaluru",
        channel="mobile",
        timestamp_inferred=False,
    ):
        return {
            "transaction_id": transaction_id,
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
            "location": location,
            "channel": channel,
            "timestamp_inferred": timestamp_inferred,
        }

    def test_account_history_explains_amount_recipient_and_location_changes(self):
        start = datetime.now(timezone.utc) - timedelta(days=30)
        for index in range(8):
            risk_engine.record_transaction(
                self.database,
                self.transaction(
                    f"history-{index}",
                    amount=1000,
                    timestamp=start + timedelta(days=index * 3),
                ),
            )

        assessment = risk_engine.record_transaction(
            self.database,
            self.transaction(
                "outlier",
                receiver="ACC999",
                amount=50000,
                location="Chennai",
                timestamp=datetime.now(timezone.utc),
            ),
        )

        self.assertEqual(assessment["risk_level"], "Medium")
        self.assertGreaterEqual(assessment["risk_score"], 60)
        self.assertGreaterEqual(assessment["confidence"], 75)
        self.assertTrue(any("historical median" in reason for reason in assessment["reasons"]))
        self.assertTrue(any("First observed transfer" in reason for reason in assessment["reasons"]))
        self.assertTrue(any("Location differs" in reason for reason in assessment["reasons"]))
        self.assertEqual(len(risk_engine.get_cases(self.database)), 1)

    def test_missing_location_is_disclosed_without_becoming_a_risk_signal(self):
        assessment = risk_engine.record_transaction(
            self.database,
            self.transaction(
                "incomplete",
                location=None,
                channel=None,
                amount=100,
                timestamp_inferred=True,
            ),
        )

        self.assertEqual(assessment["risk_score"], 0)
        self.assertTrue(any("Location was not supplied" in reason for reason in assessment["reasons"]))
        self.assertTrue(any("Channel was not supplied" in reason for reason in assessment["reasons"]))
        self.assertTrue(any("Timestamp was not supplied" in reason for reason in assessment["reasons"]))
        self.assertEqual(assessment["risk_level"], "Informational")
        self.assertEqual(assessment["confidence"], 35)

    def test_rapid_connected_sequence_creates_linked_case_and_status_persists(self):
        start = datetime.now(timezone.utc) - timedelta(minutes=8)
        for index, (sender, receiver) in enumerate((
            ("A100", "A101"),
            ("A101", "A102"),
            ("A102", "A103"),
        )):
            assessment = risk_engine.record_transaction(
                self.database,
                self.transaction(
                    f"chain-{index}",
                    sender=sender,
                    receiver=receiver,
                    timestamp=start + timedelta(minutes=index * 2),
                ),
            )

        cases = risk_engine.get_cases(self.database)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["transaction_id"], "chain-2")
        self.assertEqual(cases[0]["linked_transaction_ids"], ["chain-0", "chain-1", "chain-2"])

        updated = risk_engine.update_case(
            self.database,
            cases[0]["case_id"],
            "Under Review",
            "Checking linked transfer timing.",
        )
        self.assertEqual(updated["status"], "Under Review")
        self.assertEqual(updated["notes"], "Checking linked transfer timing.")

    def test_duplicate_transaction_id_is_rejected(self):
        transaction = self.transaction("duplicate")
        risk_engine.record_transaction(self.database, transaction)
        with self.assertRaisesRegex(ValueError, "already been imported"):
            risk_engine.record_transaction(self.database, transaction)

    def test_future_transactions_do_not_leak_into_past_behavior_context(self):
        now = datetime.now(timezone.utc)
        risk_engine.record_transaction(
            self.database,
            self.transaction(
                "future",
                amount=1000,
                timestamp=now + timedelta(days=1),
            ),
        )

        assessment = risk_engine.record_transaction(
            self.database,
            self.transaction(
                "past",
                amount=50000,
                timestamp=now,
            ),
        )

        self.assertFalse(any("historical median" in reason for reason in assessment["reasons"]))
        self.assertTrue(any("Limited account history" in reason for reason in assessment["reasons"]))

    def test_snapshot_keeps_monitoring_data_after_database_reopen(self):
        risk_engine.record_transaction(
            self.database,
            self.transaction("saved"),
        )

        snapshot = risk_engine.build_snapshot(self.database)

        self.assertEqual(snapshot["transaction_count"], 1)
        self.assertEqual(snapshot["transactions"][0]["transaction_id"], "saved")
        self.assertEqual(snapshot["transactions"][0]["risk_level"], "Informational")
        self.assertIn("Limited account history", " ".join(snapshot["transactions"][0]["reasons"]))
        self.assertEqual(snapshot["transactions"][0]["source"], "import")
        self.assertEqual(snapshot["edges"][0]["risk_score"], 0)


if __name__ == "__main__":
    unittest.main()
