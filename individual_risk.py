from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class RiskSignal:
    key: str
    label: str
    triggered: bool
    points: int
    explanation: str


def _classify(score):
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    if score >= 20:
        return "Low"
    return "Informational"


def assess_transaction(transaction):
    signals = []

    def add_signal(key, label, points, explanation):
        signals.append(RiskSignal(
            key=key,
            label=label,
            triggered=points > 0,
            points=points,
            explanation=explanation,
        ))

    amount = transaction.amount
    usual_amount = transaction.usual_transaction_amount
    if usual_amount is not None:
        ratio = amount / usual_amount
        if ratio >= 8:
            amount_points = 30
        elif ratio >= 4:
            amount_points = 25
        elif ratio >= 2.5:
            amount_points = 18
        elif ratio >= 1.5:
            amount_points = 10
        else:
            amount_points = 0
        explanation = (
            f"₹{amount:,.2f} is {ratio:.1f}× the supplied usual amount "
            f"of ₹{usual_amount:,.2f}."
        )
    else:
        if amount >= 50000:
            amount_points = 22
        elif amount >= 30000:
            amount_points = 16
        elif amount >= 10000:
            amount_points = 8
        else:
            amount_points = 0
        explanation = (
            f"₹{amount:,.2f}; no usual-amount baseline was provided, so "
            "only broad amount bands were considered."
        )
    add_signal("amount", "Amount compared with usual activity", amount_points, explanation)

    frequency = transaction.transactions_last_hour
    usual_frequency = transaction.usual_transactions_per_hour
    if usual_frequency is not None:
        frequency_ratio = frequency / usual_frequency
        if frequency_ratio >= 4:
            frequency_points = 25
        elif frequency_ratio >= 2.5:
            frequency_points = 18
        elif frequency_ratio >= 1.5:
            frequency_points = 8
        else:
            frequency_points = 0
        frequency_explanation = (
            f"{frequency} transaction(s) in the last hour versus a usual "
            f"{usual_frequency:g} per hour ({frequency_ratio:.1f}× baseline)."
        )
    else:
        if frequency >= 8:
            frequency_points = 25
        elif frequency >= 5:
            frequency_points = 18
        elif frequency >= 3:
            frequency_points = 8
        else:
            frequency_points = 0
        frequency_explanation = (
            f"{frequency} transaction(s) reported in the last hour; "
            "no personal frequency baseline was provided."
        )
    add_signal(
        "frequency",
        "Recent transaction frequency",
        frequency_points,
        frequency_explanation,
    )

    add_signal(
        "new_payee",
        "Recipient history",
        12 if transaction.is_new_payee else 0,
        "Recipient is marked as new." if transaction.is_new_payee
        else "Recipient is marked as previously used.",
    )
    add_signal(
        "unusual_hour",
        "Transaction timing",
        8 if transaction.unusual_hour else 0,
        "Transaction is marked as outside the usual activity hours."
        if transaction.unusual_hour
        else "Transaction is marked as within the usual activity hours.",
    )

    if transaction.account_age_days <= 7:
        age_points = 8
    elif transaction.account_age_days <= 30:
        age_points = 4
    else:
        age_points = 0
    add_signal(
        "account_age",
        "Account history length",
        age_points,
        f"Account age is {transaction.account_age_days} day(s).",
    )

    interactions = []
    if amount_points >= 18 and frequency_points >= 18:
        interactions.append((
            "amount_frequency",
            "Elevated amount combined with frequent activity",
            8,
            "Both amount deviation and one-hour frequency are elevated.",
        ))
    if transaction.is_new_payee and transaction.unusual_hour:
        interactions.append((
            "new_payee_unusual_hour",
            "New recipient combined with unusual timing",
            5,
            "The recipient is new and the transaction is outside usual hours.",
        ))
    for key, label, points, explanation in interactions:
        add_signal(key, label, points, explanation)

    raw_score = sum(signal.points for signal in signals)
    score = min(100, raw_score)
    supplied_baselines = sum(
        baseline is not None
        for baseline in (usual_amount, usual_frequency)
    )
    confidence = 80 + supplied_baselines * 10
    missing_baselines = []
    if usual_amount is None:
        missing_baselines.append("usual amount")
    if usual_frequency is None:
        missing_baselines.append("usual frequency")
    if missing_baselines:
        confidence_reason = (
            f"No {' and '.join(missing_baselines)} history was supplied; "
            "the corresponding signal uses broad activity thresholds. "
            "This is input completeness, not model accuracy."
        )
    else:
        confidence_reason = "Both usual-amount and usual-frequency baselines were supplied."

    triggered = [signal for signal in signals if signal.triggered]
    reasons = [
        f"{signal.label}: {signal.explanation}"
        for signal in triggered
    ]
    if not reasons:
        reasons.append("No configured risk signals were triggered by the supplied inputs.")

    return {
        "risk_score": score,
        "risk_level": _classify(score),
        "signals": [asdict(signal) for signal in signals],
        "reasons": reasons,
        "context_confidence": confidence,
        "confidence_explanation": confidence_reason,
        "disclaimer": (
            "Rule-based demonstration score, not a calibrated probability of fraud. "
            "Review the reasons and supporting evidence; do not use this score to make "
            "an automated financial decision."
        ),
    }
