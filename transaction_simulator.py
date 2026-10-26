
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import random


def generate_transactions(scenario="suspicious"):
    """Generate synthetic transactions for hackathon demonstrations."""
    rng = random.Random(42)
    start = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
    transactions = []

    def add(tx_id, minute, sender, receiver, amount):
        transactions.append({
            "transaction_id": tx_id,
            "timestamp": (
                start + timedelta(minutes=minute)
            ).isoformat(),
            "sender": sender,
            "receiver": receiver,
            "amount": round(float(amount), 2),
        })

    # Background activity shared by both scenarios
    for i in range(12):
        sender = f"ACC{rng.randint(1, 8):03d}"
        receiver = f"ACC{rng.randint(9, 16):03d}"

        while receiver == sender:
            receiver = f"ACC{rng.randint(9, 16):03d}"

        add(
            f"BG{i + 1:03d}",
            i * 20,
            sender,
            receiver,
            rng.randint(100, 5000),
        )

    if scenario == "suspicious":
        # Controlled example: money moves rapidly across accounts.
        add("CHAIN001", 5, "ACC100", "ACC101", 10000)
        add("CHAIN002", 7, "ACC101", "ACC102", 9700)
        add("CHAIN003", 9, "ACC102", "ACC103", 9400)
        add("CHAIN004", 11, "ACC103", "ACC104", 9000)

    elif scenario == "normal":
        # Transfers are spread over a longer period.
        add("NORM001", 5, "ACC100", "ACC101", 1000)
        add("NORM002", 180, "ACC101", "ACC102", 800)
        add("NORM003", 360, "ACC102", "ACC103", 500)
        add("NORM004", 600, "ACC103", "ACC104", 300)

    else:
        raise ValueError("Scenario must be 'normal' or 'suspicious'")

    return sorted(transactions, key=lambda x: x["timestamp"])


def detect_transaction_chains(transactions, max_gap_minutes=5, min_hops=3):
    """
    Find paths of at least min_hops transfers where each transfer
    follows the previous transfer within max_gap_minutes.

    This is a demonstration heuristic, not proof of fraud.
    """
    parsed = []

    for tx in transactions:
        item = dict(tx)
        item["_time"] = datetime.fromisoformat(
            tx["timestamp"].replace("Z", "+00:00")
        )
        parsed.append(item)

    parsed.sort(key=lambda x: x["_time"])

    outgoing = defaultdict(list)
    for tx in parsed:
        outgoing[tx["sender"]].append(tx)

    findings = []
    seen = set()

    def explore(path):
        last = path[-1]

        if len(path) >= min_hops:
            ids = tuple(tx["transaction_id"] for tx in path)
            if ids not in seen:
                seen.add(ids)
                findings.append({
                    "accounts": [
                        path[0]["sender"]
                    ] + [tx["receiver"] for tx in path],
                    "transaction_ids": list(ids),
                    "transaction_count": len(path),
                    "total_initial_amount": path[0]["amount"],
                    "start_time": path[0]["timestamp"],
                    "end_time": path[-1]["timestamp"],
                    "reason": (
                        "A multi-account transfer chain was found "
                        "with short intervals between consecutive transfers."
                    ),
                    "status": "Requires investigation; not confirmed fraud",
                })

        # Keep paths bounded to avoid runaway exploration.
        if len(path) >= 6:
            return

        for next_tx in outgoing.get(last["receiver"], []):
            if next_tx["_time"] <= last["_time"]:
                continue

            gap = (
                next_tx["_time"] - last["_time"]
            ).total_seconds() / 60

            if gap > max_gap_minutes:
                continue

            if any(
                tx["transaction_id"] == next_tx["transaction_id"]
                for tx in path
            ):
                continue

            explore(path + [next_tx])

    for tx in parsed:
        explore([tx])

    # Consolidate overlapping paths: keep only maximal chains. For example,
    # a 4-transfer chain should not also create two shorter cases from itself.
    maximal = []
    for candidate in findings:
        candidate_ids = candidate["transaction_ids"]
        is_subchain = any(
            len(other["transaction_ids"]) > len(candidate_ids)
            and any(
                other["transaction_ids"][i:i + len(candidate_ids)] == candidate_ids
                for i in range(len(other["transaction_ids"]) - len(candidate_ids) + 1)
            )
            for other in findings
        )
        if not is_subchain:
            maximal.append(candidate)

    for finding in maximal:
        # Transparent heuristic score, not a fraud probability.
        hops = finding["transaction_count"]
        finding["pattern_score"] = min(95, 40 + 10 * hops)

    return maximal


if __name__ == "__main__":
    for scenario in ("normal", "suspicious"):
        transactions = generate_transactions(scenario)
        chains = detect_transaction_chains(transactions)

        print(f"\nScenario: {scenario}")
        print(f"Transactions: {len(transactions)}")
        print(f"Chains found: {len(chains)}")

        for chain in chains:
            print(chain)
