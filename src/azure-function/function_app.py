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
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import ServiceBusAuthenticationError, ServiceBusConnectionError

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

_SB_NAMESPACE = os.environ["AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE"]
_SB_QUEUE_NAME = os.environ["AZURE_SERVICEBUS_QUEUE_NAME"]
# DefaultAzureCredential picks up the Function App's system-assigned managed
# identity automatically when running in Azure; falls back to az CLI / env
# vars for local development.
_credential = DefaultAzureCredential()


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
        with ServiceBusClient(_SB_NAMESPACE, _credential) as sb_client:
            with sb_client.get_queue_sender(_SB_QUEUE_NAME) as sender:
                sb_message = ServiceBusMessage(
                    body=json.dumps(message_body),
                    message_id=job_id,
                    content_type="application/json",
                )
                sender.send_messages(sb_message)
    except ServiceBusAuthenticationError:
        logging.exception("Authentication failure sending job %s – check managed identity role assignments", job_id)
        return func.HttpResponse(
            json.dumps({"error": "Service Bus authentication failed"}),
            status_code=503,
            mimetype="application/json",
        )
    except (ServiceBusConnectionError, ServiceRequestError):
        logging.exception("Connection failure sending job %s", job_id)
        return func.HttpResponse(
            json.dumps({"error": "Service Bus connection failed – please retry"}),
            status_code=503,
            mimetype="application/json",
        )
    except HttpResponseError as exc:
        logging.exception("Service Bus returned an error for job %s: %s", job_id, exc.status_code)
        return func.HttpResponse(
            json.dumps({"error": "Service Bus request error", "detail": str(exc)}),
            status_code=500,
            mimetype="application/json",
        )
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Unexpected failure enqueuing job %s", job_id)
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


@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """GET /api/health – liveness check."""
    return func.HttpResponse(
        json.dumps({"status": "healthy"}),
        status_code=200,
        mimetype="application/json",
    )
