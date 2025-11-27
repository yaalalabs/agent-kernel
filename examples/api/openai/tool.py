from typing import Dict, List

from agents import function_tool


@function_tool
def fetch_customer_activity(name: str, operations: List[str] | None = None) -> Dict[str, object]:
    """
    Returns recent banking activities for a given customer name.

    Use this tool to ground your conversation with the customer by referencing
    the exact operations they recently performed. If "operations" are provided,
    the tool will filter to those operation types

    :param name: The full name of the customer.
    :param operations: Optional list of operation types to include, e.g.,
        ["deposit", "withdrawal", "transfer", "bill_payment"].
    :return: A JSON object containing the customer's name and a list of activity
        records. Each record contains: type, amount, currency, and a short note.
    """
    sample: List[Dict[str, object]] = [
        {"type": "deposit", "amount": 250.00, "currency": "USD", "note": "Deposited over the counter"},
        {"type": "bill_payment", "amount": 89.99, "currency": "USD", "note": "Utility bill"},
        {"type": "transfer", "amount": 150.00, "currency": "USD", "note": "To Savings"},
        {"type": "withdrawal", "amount": 60.00, "currency": "USD", "note": "ATM cash"},
    ]

    if operations:
        ops_lower = {op.lower() for op in operations}
        filtered = [item for item in sample if str(item.get("type", "")).lower() in ops_lower]
    else:
        filtered = sample[:3]

    return {
        "customer": name,
        "activities": filtered,
    }
