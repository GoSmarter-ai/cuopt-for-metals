"""
Azure Function App – cuOpt for Metals
HTTP trigger: accepts a cutting-stock job payload and enqueues it on Service Bus.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_SB_CONNECTION_STRING = os.environ["AZURE_SERVICEBUS_CONNECTION_STRING"]
_SB_QUEUE_NAME = os.environ["AZURE_SERVICEBUS_QUEUE_NAME"]


# ---------------------------------------------------------------------------
# Helper – validate payload
# ---------------------------------------------------------------------------
def _validate_job(payload: dict) -> list[str]:
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


# ---------------------------------------------------------------------------
# HTTP trigger – submit a cutting job
# ---------------------------------------------------------------------------
@app.route(route="jobs", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """
    POST /api/jobs

    Body (JSON):
    {
        "stock_length_mm": 6000,          # optional, overrides env default
        "orders": [
            {"length_mm": 2400, "quantity": 3},
            {"length_mm": 1800, "quantity": 5}
        ],
        "metadata": {}                    # optional pass-through metadata
    }

    Returns 202 Accepted with a job_id on success.
    """
    logging.info("submit_job triggered")

    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Request body must be valid JSON"}),
            status_code=400,
            mimetype="application/json",
        )

    errors = _validate_job(payload)
    if errors:
        return func.HttpResponse(
            json.dumps({"error": "Validation failed", "details": errors}),
            status_code=422,
            mimetype="application/json",
        )

    job_id = str(uuid.uuid4())
    message_body = {
        "job_id": job_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "stock_length_mm": payload.get("stock_length_mm", int(os.environ.get("STOCK_LENGTH_MM", "6000"))),
        "orders": payload["orders"],
        "metadata": payload.get("metadata", {}),
    }

    try:
        with ServiceBusClient.from_connection_string(_SB_CONNECTION_STRING) as sb_client:
            with sb_client.get_queue_sender(_SB_QUEUE_NAME) as sender:
                sb_message = ServiceBusMessage(
                    body=json.dumps(message_body),
                    message_id=job_id,
                    content_type="application/json",
                )
                sender.send_messages(sb_message)
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Failed to enqueue job %s", job_id)
        return func.HttpResponse(
            json.dumps({"error": "Failed to enqueue job", "detail": str(exc)}),
            status_code=500,
            mimetype="application/json",
        )

    logging.info("Enqueued job %s with %d order lines", job_id, len(payload["orders"]))

    return func.HttpResponse(
        json.dumps(
            {
                "job_id": job_id,
                "status": "queued",
                "message": "Job accepted and queued for processing",
            }
        ),
        status_code=202,
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# HTTP trigger – health check
# ---------------------------------------------------------------------------
@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """GET /api/health – liveness check."""
    return func.HttpResponse(
        json.dumps({"status": "healthy"}),
        status_code=200,
        mimetype="application/json",
    )
