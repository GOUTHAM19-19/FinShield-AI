import json
import math
import os
import sqlite3
import statistics
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from backend.transaction_simulator import detect_transaction_chains


def database_path(base_dir):
    configured = os.getenv("FINSHIELD_RISK_DB")
    return Path(configured) if configured else Path(base_dir) / "data" / "risk_monitoring.sqlite3"


def _connect(path):
    database = Path(path)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _initialize(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS monitored_transactions (
            transaction_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            amount REAL NOT NULL,
            timestamp_inferred INTEGER NOT NULL DEFAULT 0,
            location TEXT,
            channel TEXT,
            risk_score INTEGER NOT NULL,
            risk_level TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            reasons_json TEXT NOT NULL,
            source TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_monitored_sender_time
            ON monitored_transactions(sender, timestamp);
        CREATE TABLE IF NOT EXISTS investigation_cases (
            case_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL UNIQUE,
            priority_score INTEGER NOT NULL,
            priority_level TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            notes TEXT NOT NULL DEFAULT '',
            reasons_json TEXT NOT NULL,
            linked_ids_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    transaction_columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(monitored_transactions)"
        )
    }
    if "timestamp_inferred" not in transaction_columns:
        connection.execute(
            "ALTER TABLE monitored_transactions "
            "ADD COLUMN timestamp_inferred INTEGER NOT NULL DEFAULT 0"
        )


def _parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_transaction(row):
    result = dict(row)
    result["reasons"] = json.loads(result.pop("reasons_json"))
    return result


def _classify(score):
    if score >= 70:
        return "High"
    if score >= 45:
        return "Medium"
    if score >= 25:
        return "Low"
    return "Informational"


def _score_transaction(transaction, history, chains):
    timestamp = _parse_time(transaction["timestamp"])
    sender_history = [
        row for row in history
        if row["sender"] == transaction["sender"]
        and _parse_time(row["timestamp"]) < timestamp
    ]
    reasons = []
    score = 0

    if len(sender_history) >= 5:
        median_amount = statistics.median(row["amount"] for row in sender_history)
        if transaction["amount"] >= max(median_amount * 3, median_amount + 10000):
            score += 25
            reasons.append(
                f"Amount is unusually high for this account (historical median ₹{median_amount:,.2f})."
            )

    hour_window_start = timestamp - timedelta(hours=1)
    recent = [
        row for row in sender_history
        if hour_window_start <= _parse_time(row["timestamp"]) <= timestamp
    ]
    if len(recent) >= 4:
        score += 20
        reasons.append(f"High activity: {len(recent) + 1} transfers within one hour.")
    elif len(recent) >= 2:
        score += 12
        reasons.append(f"Elevated activity: {len(recent) + 1} transfers within one hour.")

    if sender_history:
        known_receivers = {row["receiver"] for row in sender_history}
        if transaction["receiver"] not in known_receivers:
            score += 12
            reasons.append("First observed transfer to this recipient for the sender.")

        previous_locations = [
            row["location"] for row in sender_history if row["location"]
        ]
        if transaction.get("location") and previous_locations:
            if transaction["location"] != previous_locations[-1]:
                score += 12
                reasons.append(
                    f"Location differs from the sender's latest recorded location ({previous_locations[-1]})."
                )

        previous_channels = [
            row["channel"] for row in sender_history if row["channel"]
        ]
        if (
            transaction.get("channel")
            and len(previous_channels) >= 5
            and transaction["channel"] not in previous_channels
        ):
            score += 10
            reasons.append(
                f"First observed transaction through the {transaction['channel']} channel for this sender."
            )

        timed_history = [
            row for row in sender_history
            if _parse_time(row["timestamp"]) >= timestamp - timedelta(days=30)
        ]
        if len(timed_history) >= 8:
            usual_hours = {
                _parse_time(row["timestamp"]).hour for row in timed_history
            }
            if timestamp.hour not in usual_hours:
                score += 10
                reasons.append(
                    f"Activity at {timestamp.hour:02d}:00 UTC is outside recorded activity hours."
                )

        recent_spend_start = timestamp - timedelta(days=7)
        recent_spend = sum(
            row["amount"] for row in sender_history
            if recent_spend_start <= _parse_time(row["timestamp"]) <= timestamp
        )
        older_history = [
            row for row in sender_history
            if timestamp - timedelta(days=37)
            <= _parse_time(row["timestamp"])
            < recent_spend_start
        ]
        if len(older_history) >= 5:
            older_daily_average = (
                sum(row["amount"] for row in older_history) / 30
            )
            if older_daily_average and recent_spend + transaction["amount"] > older_daily_average * 7 * 3:
                score += 15
                reasons.append(
                    "Seven-day spending is more than three times the prior daily spending baseline."
                )

    linked_chain = next(
        (
            chain for chain in chains
            if transaction["transaction_id"] in chain["transaction_ids"]
        ),
        None,
    )
    if linked_chain:
        score += 25
        reasons.append(
            f"Part of a rapid connected-transfer sequence ({linked_chain['transaction_count']} transfers)."
        )

    score = min(score, 100)
    completeness = sum((
        not transaction.get("timestamp_inferred", False),
        bool(transaction.get("location")),
        bool(transaction.get("channel")),
    ))
    history_confidence = min(40, len(sender_history) * 5)
    confidence = min(95, 35 + history_confidence + completeness * 5)
    if len(sender_history) < 5:
        reasons.append(
            "Limited account history: behavioral comparisons are less reliable."
        )
    if not transaction.get("location"):
        reasons.append("Location was not supplied; location-based checks were skipped.")
    if not transaction.get("channel"):
        reasons.append("Channel was not supplied; channel-based checks were skipped.")
    if transaction.get("timestamp_inferred"):
        reasons.append(
            "Timestamp was not supplied; an import-order timestamp was assigned and timing checks are approximate."
        )
    if not reasons:
        reasons.append("No configured risk signal was triggered by the available context.")

    return {
        "risk_score": score,
        "risk_level": _classify(score),
        "confidence": confidence,
        "reasons": reasons,
        "linked_transaction_ids": (
            linked_chain["transaction_ids"] if linked_chain else []
        ),
    }


def record_transaction(database, transaction, source="import"):
    timestamp = _parse_time(transaction["timestamp"]).isoformat()
    transaction_id = (transaction.get("transaction_id") or "").strip()
    normalized = {
        **transaction,
        "timestamp": timestamp,
        "transaction_id": transaction_id or f"TX-{uuid4().hex[:12].upper()}",
        "sender": transaction["sender"].strip().upper(),
        "receiver": transaction["receiver"].strip().upper(),
        "location": (transaction.get("location") or "").strip().casefold() or None,
        "channel": (transaction.get("channel") or "").strip().casefold() or None,
        "timestamp_inferred": bool(transaction.get("timestamp_inferred", False)),
        "amount": round(float(transaction["amount"]), 2),
    }
    if normalized["sender"] == normalized["receiver"]:
        raise ValueError("Sender and receiver must be different accounts.")
    if not math.isfinite(normalized["amount"]) or normalized["amount"] <= 0:
        raise ValueError("Transaction amount must be greater than zero.")

    with closing(_connect(database)) as connection, connection:
        _initialize(connection)
        history_rows = connection.execute(
            """
            SELECT transaction_id, timestamp, sender, receiver, amount, location,
                   channel, risk_score, risk_level, confidence, reasons_json, source
            FROM (
                SELECT transaction_id, timestamp, sender, receiver, amount, location,
                       channel, risk_score, risk_level, confidence, reasons_json, source
                FROM monitored_transactions
                ORDER BY timestamp DESC, transaction_id DESC
                LIMIT 1000
            )
            ORDER BY timestamp, transaction_id
            """
        ).fetchall()
        history = [dict(row) for row in history_rows]
        duplicate = connection.execute(
            "SELECT 1 FROM monitored_transactions WHERE transaction_id = ?",
            (normalized["transaction_id"],),
        ).fetchone()
        if duplicate:
            raise ValueError("Transaction ID has already been imported.")

        transaction_stream = [
            {
                **{key: row[key] for key in ("transaction_id", "timestamp", "sender", "receiver", "amount")},
            }
            for row in history
        ] + [{
            key: normalized[key]
            for key in ("transaction_id", "timestamp", "sender", "receiver", "amount")
        }]
        chains = detect_transaction_chains(transaction_stream)
        assessment = _score_transaction(normalized, history, chains)
        connection.execute(
            """
            INSERT INTO monitored_transactions (
                transaction_id, timestamp, sender, receiver, amount, location,
                channel, timestamp_inferred, risk_score, risk_level, confidence,
                reasons_json, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized["transaction_id"], normalized["timestamp"],
                normalized["sender"], normalized["receiver"], normalized["amount"],
                normalized["location"], normalized["channel"],
                int(normalized["timestamp_inferred"]),
                assessment["risk_score"], assessment["risk_level"],
                assessment["confidence"], json.dumps(assessment["reasons"]), source,
            ),
        )

        if assessment["risk_score"] >= 45 or assessment["linked_transaction_ids"]:
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO investigation_cases (
                    case_id, transaction_id, priority_score, priority_level,
                    reasons_json, linked_ids_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id) DO UPDATE SET
                    priority_score = excluded.priority_score,
                    priority_level = excluded.priority_level,
                    reasons_json = excluded.reasons_json,
                    linked_ids_json = excluded.linked_ids_json,
                    updated_at = excluded.updated_at
                """,
                (
                    f"CASE-{uuid4().hex[:10].upper()}",
                    normalized["transaction_id"],
                    assessment["risk_score"],
                    _classify(assessment["risk_score"]),
                    json.dumps(assessment["reasons"]),
                    json.dumps(assessment["linked_transaction_ids"]),
                    now,
                    now,
                ),
            )

        row = connection.execute(
            "SELECT * FROM monitored_transactions WHERE transaction_id = ?",
            (normalized["transaction_id"],),
        ).fetchone()
    result = _serialize_transaction(row)
    result["linked_transaction_ids"] = assessment["linked_transaction_ids"]
    return result


def get_transactions(database, limit=500):
    with closing(_connect(database)) as connection, connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM monitored_transactions ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_serialize_transaction(row) for row in rows]


def get_cases(database):
    with closing(_connect(database)) as connection, connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT c.*, t.timestamp, t.sender, t.receiver, t.amount,
                   t.location, t.channel, t.confidence
            FROM investigation_cases c
            JOIN monitored_transactions t USING (transaction_id)
            ORDER BY c.priority_score DESC, c.updated_at DESC
            """
        ).fetchall()
    cases = []
    for row in rows:
        case = dict(row)
        case["reasons"] = json.loads(case.pop("reasons_json"))
        case["linked_transaction_ids"] = json.loads(case.pop("linked_ids_json"))
        cases.append(case)
    return cases


def update_case(database, case_id, status, notes):
    if status not in {"Open", "Under Review", "Escalated", "Resolved"}:
        raise ValueError("Unsupported investigation status.")
    with closing(_connect(database)) as connection, connection:
        _initialize(connection)
        cursor = connection.execute(
            """
            UPDATE investigation_cases
            SET status = ?, notes = ?, updated_at = ?
            WHERE case_id = ?
            """,
            (status, notes.strip()[:2000], datetime.now(timezone.utc).isoformat(), case_id),
        )
        if cursor.rowcount != 1:
            return None
    return next((case for case in get_cases(database) if case["case_id"] == case_id), None)


def build_snapshot(database):
    transactions = list(reversed(get_transactions(database)))
    chains = detect_transaction_chains(transactions) if transactions else []
    for chain in chains:
        scores = [
            next(
                (tx["risk_score"] for tx in transactions if tx["transaction_id"] == tx_id),
                0,
            )
            for tx_id in chain["transaction_ids"]
        ]
        chain["priority_score"] = max(scores, default=0)
        chain["priority_level"] = _classify(chain["priority_score"])
        chain["priority_factors"] = [
            f"Risk score: {chain['priority_score']}/100 (heuristic, not probability)",
            f"Connected transfers: {chain['transaction_count']}",
            f"Initial transfer amount: ₹{chain['total_initial_amount']:,.2f}",
        ]
        chain["reasons"] = [
            "Rapid connected transfers were observed.",
            "Review the linked events and context before taking action.",
        ]
    nodes = {}
    edges = []
    chain_ids = {
        tx_id for chain in chains for tx_id in chain["transaction_ids"]
    }
    for tx in transactions:
        nodes[tx["sender"]] = {"id": tx["sender"], "label": tx["sender"]}
        nodes[tx["receiver"]] = {"id": tx["receiver"], "label": tx["receiver"]}
        edges.append({
            "id": tx["transaction_id"],
            "source": tx["sender"],
            "target": tx["receiver"],
            "amount": tx["amount"],
            "timestamp": tx["timestamp"],
            "suspicious_pattern": tx["transaction_id"] in chain_ids,
            "risk_score": tx["risk_score"],
        })
    return {
        "transaction_count": len(transactions),
        "transactions": transactions,
        "chain_count": len(chains),
        "chains": chains,
        "nodes": list(nodes.values()),
        "edges": edges,
        "cases": get_cases(database),
        "disclaimer": (
            "Risk scores are explainable heuristics, not calibrated fraud probabilities. "
            "Alerts require human investigation."
        ),
    }


def reset_database(database):
    with closing(_connect(database)) as connection, connection:
        _initialize(connection)
        connection.execute("DELETE FROM investigation_cases")
        connection.execute("DELETE FROM monitored_transactions")
