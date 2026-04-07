"""
Validation helpers for the cuOpt for Metals Azure Function.
"""


def validate_job(payload: dict) -> list[str]:
    """Return a list of validation errors, or an empty list if payload is valid."""
    errors: list[str] = []

    if "orders" not in payload:
        errors.append("Missing required field: 'orders'")
        return errors

    orders = payload["orders"]
    if not isinstance(orders, list) or len(orders) == 0:
        errors.append("'orders' must be a non-empty list")
        return errors

    for i, order in enumerate(orders):
        if "length_mm" not in order:
            errors.append(f"orders[{i}] missing 'length_mm'")
        elif not isinstance(order["length_mm"], (int, float)) or order["length_mm"] <= 0:
            errors.append(f"orders[{i}].length_mm must be a positive number")

        if "quantity" not in order:
            errors.append(f"orders[{i}] missing 'quantity'")
        elif not isinstance(order["quantity"], int) or order["quantity"] <= 0:
            errors.append(f"orders[{i}].quantity must be a positive integer")

    stock_length = payload.get("stock_length_mm")
    if stock_length is not None:
        if not isinstance(stock_length, (int, float)) or stock_length <= 0:
            errors.append("'stock_length_mm' must be a positive number if provided")

    return errors
