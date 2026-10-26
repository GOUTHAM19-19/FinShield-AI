from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi.middleware.cors import CORSMiddleware
from backend import risk_engine
from backend.individual_risk import assess_transaction
from backend.transaction_simulator import (
    generate_transactions,
    detect_transaction_chains,
)
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parents[1]
app = FastAPI(
    title="FinShield AI",
    description="Financial transaction risk assessment demo API",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Transaction(BaseModel):
    amount: float = Field(gt=0, le=100_000_000)
    transactions_last_hour: int = Field(ge=0, le=10000)
    is_new_payee: bool
    unusual_hour: bool
    account_age_days: int = Field(ge=0, le=100000)
    usual_transaction_amount: float | None = Field(default=None, gt=0, le=100_000_000)
    usual_transactions_per_hour: float | None = Field(default=None, gt=0, le=10000)


@app.get("/")
def home():
    return {
        "message": "FinShield AI API is running",
        "docs": "/docs",
    }


@app.post("/predict")
def predict(transaction: Transaction):
    return assess_transaction(transaction)

@app.get("/simulate")
def simulate(scenario: str = "suspicious"):
    if scenario not in {"normal", "suspicious"}:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Scenario must be 'normal' or 'suspicious'",
        )

    transactions = generate_transactions(scenario)
    chains = detect_transaction_chains(transactions)

    # Remove internal datetime objects, if any, before returning JSON.
    return {
        "scenario": scenario,
        "transaction_count": len(transactions),
        "transactions": transactions,
        "chain_count": len(chains),
        "chains": chains,
        "disclaimer": (
            "Synthetic demonstration data. Detected patterns require "
            "investigation and do not establish fraud."
        ),
    }



@app.get("/transaction-graph")
def transaction_graph(scenario: str = "suspicious"):
    from fastapi import HTTPException

    if scenario not in {"normal", "suspicious"}:
        raise HTTPException(
            status_code=400,
            detail="Scenario must be 'normal' or 'suspicious'",
        )

    transactions = generate_transactions(scenario)
    chains = detect_transaction_chains(transactions)
    suspicious_ids = {
        tx_id
        for chain in chains
        for tx_id in chain.get("transaction_ids", [])
    }

    nodes = {}
    edges = []
    for tx in transactions:
        sender = tx["sender"]
        receiver = tx["receiver"]
        nodes[sender] = {"id": sender, "label": sender}
        nodes[receiver] = {"id": receiver, "label": receiver}
        edges.append({
            "id": tx["transaction_id"],
            "source": sender,
            "target": receiver,
            "amount": tx["amount"],
            "timestamp": tx["timestamp"],
            "suspicious_pattern": tx["transaction_id"] in suspicious_ids,
        })

    return {
        "scenario": scenario,
        "nodes": list(nodes.values()),
        "edges": edges,
        "chain_count": len(chains),
        "chains": chains,
        "location_note": "Transaction locations are not supplied by this demo simulator.",
        "disclaimer": (
            "Synthetic demonstration data. Highlighted transfers require "
            "investigation and are not confirmed fraud."
        ),
    }






def prioritize_investigation_cases(chains):
    """Transparent demo heuristic for sorting investigation leads, not fraud probability."""
    prioritized = []
    for chain in chains:
        hops = int(chain.get("transaction_count", 0))
        pattern_score = float(chain.get("pattern_score", 0))
        amount = float(chain.get("total_initial_amount", 0))
        # Bounded, explainable score: pattern score + capped chain/amount signals.
        chain_bonus = min(10, max(0, hops - 2) * 3)
        amount_bonus = min(10, max(0, amount) / 10000)
        priority_score = int(round(min(100, pattern_score * 0.75 + chain_bonus + amount_bonus)))
        if priority_score >= 70:
            priority = "High"
        elif priority_score >= 40:
            priority = "Medium"
        else:
            priority = "Low"
        item = dict(chain)
        item["priority_score"] = priority_score
        item["priority_level"] = priority
        item["priority_factors"] = [
            f"Pattern score: {pattern_score:g}/100",
            f"Connected transfers: {hops}",
            f"Initial transfer amount signal: ₹{amount:,.2f}",
        ]
        prioritized.append(item)
    return sorted(
        prioritized,
        key=lambda item: (item["priority_score"], item.get("transaction_count", 0)),
        reverse=True,
    )


# Persistent local transaction-monitoring and case-review store.
RISK_DATABASE_PATH = risk_engine.database_path(BASE_DIR)

class MonitorTransaction(BaseModel):
    transaction_id: str | None = Field(default=None, min_length=1, max_length=100)
    sender: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    receiver: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    amount: float = Field(gt=0, le=100_000_000)
    minutes_after_previous: int = Field(ge=0, le=1440, default=2)
    timestamp: str | None = None
    location: str | None = Field(default=None, max_length=100)
    channel: str | None = Field(default=None, max_length=40)

class MonitorTransactionBatch(BaseModel):
    transactions: list[MonitorTransaction] = Field(min_length=1, max_length=500)

class CaseUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=30)
    notes: str = Field(default="", max_length=2000)

def _monitor_payload(transaction, previous_timestamp=None):
    if transaction.timestamp:
        timestamp = transaction.timestamp
    else:
        base = (
            datetime.fromisoformat(previous_timestamp.replace("Z", "+00:00"))
            if previous_timestamp
            else datetime.now(timezone.utc).replace(second=0, microsecond=0)
        )
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        timestamp = (base + timedelta(minutes=transaction.minutes_after_previous)).isoformat()
    return {
        "transaction_id": transaction.transaction_id,
        "timestamp": timestamp,
        "sender": transaction.sender,
        "receiver": transaction.receiver,
        "amount": transaction.amount,
        "location": transaction.location,
        "channel": transaction.channel,
        "timestamp_inferred": not bool(transaction.timestamp),
    }

@app.post("/monitoring/reset")
def reset_monitoring():
    risk_engine.reset_database(RISK_DATABASE_PATH)
    return {
        "message": "Transaction and investigation data cleared.",
        **risk_engine.build_snapshot(RISK_DATABASE_PATH),
    }

@app.get("/monitoring")
def get_monitoring():
    return risk_engine.build_snapshot(RISK_DATABASE_PATH)

@app.post("/monitoring/transactions")
def add_monitor_transaction(transaction: MonitorTransaction):
    try:
        previous = risk_engine.get_transactions(RISK_DATABASE_PATH, limit=1)
        payload = _monitor_payload(
            transaction,
            previous[0]["timestamp"] if previous else None,
        )
        assessment = risk_engine.record_transaction(
            RISK_DATABASE_PATH,
            payload,
            source="manual",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "message": f"Analysed {assessment['transaction_id']}.",
        "assessment": assessment,
        **risk_engine.build_snapshot(RISK_DATABASE_PATH),
    }

@app.post("/monitoring/import")
def import_monitor_transactions(batch: MonitorTransactionBatch):
    imported = []
    previous = risk_engine.get_transactions(RISK_DATABASE_PATH, limit=1)
    previous_timestamp = previous[0]["timestamp"] if previous else None
    payloads = []
    for transaction in batch.transactions:
        payload = _monitor_payload(transaction, previous_timestamp)
        payloads.append(payload)
        previous_timestamp = payload["timestamp"]

    def import_time(payload):
        value = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    payloads.sort(key=import_time)
    try:
        for payload in payloads:
            assessment = risk_engine.record_transaction(
                RISK_DATABASE_PATH,
                payload,
                source="batch",
            )
            imported.append(assessment)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Import stopped after {len(imported)} transaction(s): {error}",
        ) from error
    return {
        "imported_count": len(imported),
        "assessments": imported,
        **risk_engine.build_snapshot(RISK_DATABASE_PATH),
    }

@app.patch("/monitoring/cases/{case_id}")
def update_investigation_case(case_id: str, update: CaseUpdate):
    try:
        case = risk_engine.update_case(
            RISK_DATABASE_PATH,
            case_id,
            update.status,
            update.notes,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if case is None:
        raise HTTPException(status_code=404, detail="Investigation case not found.")
    return {"case": case}
