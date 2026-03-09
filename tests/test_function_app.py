"""
Unit tests for function_app.py

Service Bus is fully mocked via unittest.mock so no Azure connection is needed.

Bootstrap order matters:
  1. Set the env vars that function_app.py reads at import time.
  2. Patch DefaultAzureCredential before the module is imported so the
     module-level `_credential = DefaultAzureCredential()` doesn't attempt
     real credential discovery.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE", "test.servicebus.windows.net")
os.environ.setdefault("AZURE_SERVICEBUS_QUEUE_NAME", "test-queue")
  
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "azure-function"))

with patch("azure.identity.DefaultAzureCredential"):
    import function_app  # noqa: E402



def _make_request(body=None):
    """Return a mock HttpRequest whose get_json() returns *body*.

    Pass body=None to simulate a request with an unparseable JSON body
    (get_json raises ValueError, matching function_app's error path).
    """
    mock_req = MagicMock()
    if body is None:
        mock_req.get_json.side_effect = ValueError("no body")
    else:
        mock_req.get_json.return_value = body
    return mock_req


def _mock_service_bus_client():
    """Return a (mock_class_patch_target, mock_sender) pair.

    The mock_class is suitable for use as the *new* value in
    `patch("function_app.ServiceBusClient", mock_class)`.
    """
    mock_sender = MagicMock()

    mock_sb_instance = MagicMock()
    # Context manager protocol for the outer `with ServiceBusClient(...) as sb:`
    mock_sb_instance.__enter__ = MagicMock(return_value=mock_sb_instance)
    mock_sb_instance.__exit__ = MagicMock(return_value=False)
    # Context manager protocol for the inner `with sb.get_queue_sender(...) as sender:`
    sender_ctx = mock_sb_instance.get_queue_sender.return_value
    sender_ctx.__enter__ = MagicMock(return_value=mock_sender)
    sender_ctx.__exit__ = MagicMock(return_value=False)

    mock_sb_class = MagicMock(return_value=mock_sb_instance)
    return mock_sb_class, mock_sender



# 1. Health check endpoint


class TestHealthCheck(unittest.TestCase):

    def test_returns_200(self):
        req = MagicMock()
        resp = function_app.health_check(req)
        self.assertEqual(resp.status_code, 200)

    def test_body_contains_healthy_status(self):
        req = MagicMock()
        resp = function_app.health_check(req)
        body = json.loads(resp.get_body())
        self.assertEqual(body["status"], "healthy")



# 2. Valid job submission


VALID_PAYLOAD = {
    "stock_length_mm": 6000,
    "orders": [
        {"length_mm": 2400, "quantity": 3},
        {"length_mm": 1800, "quantity": 5},
    ],
}


class TestValidJobSubmission(unittest.TestCase):

    def test_returns_202(self):
        req = _make_request(body=VALID_PAYLOAD)
        mock_sb_class, _ = _mock_service_bus_client()

        with patch("function_app.ServiceBusClient", mock_sb_class):
            resp = function_app.submit_job(req)

        self.assertEqual(resp.status_code, 202)

    def test_response_contains_job_id_and_queued_status(self):
        req = _make_request(body=VALID_PAYLOAD)
        mock_sb_class, _ = _mock_service_bus_client()

        with patch("function_app.ServiceBusClient", mock_sb_class):
            resp = function_app.submit_job(req)

        body = json.loads(resp.get_body())
        self.assertIn("job_id", body)
        self.assertEqual(body["status"], "queued")

    def test_send_messages_called_exactly_once(self):
        req = _make_request(body=VALID_PAYLOAD)
        mock_sb_class, mock_sender = _mock_service_bus_client()

        with patch("function_app.ServiceBusClient", mock_sb_class):
            function_app.submit_job(req)

        mock_sender.send_messages.assert_called_once()

    def test_enqueued_message_body_has_expected_fields(self):
        req = _make_request(body=VALID_PAYLOAD)
        mock_sb_class, mock_sender = _mock_service_bus_client()

        with patch("function_app.ServiceBusClient", mock_sb_class), \
             patch("function_app.ServiceBusMessage") as mock_sb_msg:
            function_app.submit_job(req)

        _, kwargs = mock_sb_msg.call_args
        sent = json.loads(kwargs["body"])
        self.assertIn("job_id", sent)
        self.assertIn("submitted_at", sent)
        self.assertEqual(sent["stock_length_mm"], 6000)
        self.assertEqual(len(sent["orders"]), 2)

    def test_default_stock_length_used_when_not_provided(self):
        """When stock_length_mm is omitted, the env default (6000) is used."""
        payload = {"orders": [{"length_mm": 2400, "quantity": 1}]}
        req = _make_request(body=payload)
        mock_sb_class, _ = _mock_service_bus_client()

        with patch("function_app.ServiceBusClient", mock_sb_class), \
             patch("function_app.ServiceBusMessage") as mock_sb_msg, \
             patch.dict(os.environ, {"STOCK_LENGTH_MM": "6000"}):
            function_app.submit_job(req)

        _, kwargs = mock_sb_msg.call_args
        sent = json.loads(kwargs["body"])
        self.assertEqual(sent["stock_length_mm"], 6000)



# 3. Invalid job – negative length


class TestNegativeLength(unittest.TestCase):

    def test_returns_422(self):
        req = _make_request(body={"orders": [{"length_mm": -500, "quantity": 2}]})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)

    def test_error_message_mentions_length_mm(self):
        req = _make_request(body={"orders": [{"length_mm": -500, "quantity": 2}]})
        resp = function_app.submit_job(req)
        body = json.loads(resp.get_body())
        self.assertEqual(body["error"], "Validation failed")
        self.assertTrue(
            any("length_mm" in detail for detail in body["details"]),
            msg=f"Expected 'length_mm' in details, got: {body['details']}",
        )

    def test_zero_length_also_invalid(self):
        req = _make_request(body={"orders": [{"length_mm": 0, "quantity": 1}]})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)

    def test_negative_stock_length_returns_422(self):
        req = _make_request(body={
            "stock_length_mm": -100,
            "orders": [{"length_mm": 500, "quantity": 1}],
        })
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)
        body = json.loads(resp.get_body())
        self.assertTrue(any("stock_length_mm" in d for d in body["details"]))



# 4. Missing fields


class TestMissingFields(unittest.TestCase):

    def test_missing_orders_field_returns_422(self):
        req = _make_request(body={"stock_length_mm": 6000})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)
        body = json.loads(resp.get_body())
        self.assertIn("Missing required field: 'orders'", body["details"])

    def test_empty_orders_list_returns_422(self):
        req = _make_request(body={"orders": []})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)
        body = json.loads(resp.get_body())
        self.assertTrue(any("non-empty" in d for d in body["details"]))

    def test_missing_quantity_in_order_returns_422(self):
        req = _make_request(body={"orders": [{"length_mm": 2400}]})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)
        body = json.loads(resp.get_body())
        self.assertTrue(any("quantity" in d for d in body["details"]))

    def test_missing_length_mm_in_order_returns_422(self):
        req = _make_request(body={"orders": [{"quantity": 3}]})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)
        body = json.loads(resp.get_body())
        self.assertTrue(any("length_mm" in d for d in body["details"]))

    def test_missing_both_fields_reports_both_errors(self):
        req = _make_request(body={"orders": [{}]})
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 422)
        body = json.loads(resp.get_body())
        details = " ".join(body["details"])
        self.assertIn("length_mm", details)
        self.assertIn("quantity", details)

    def test_invalid_json_body_returns_400(self):
        """Simulates a request whose body cannot be parsed as JSON."""
        req = _make_request(body=None)
        resp = function_app.submit_job(req)
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.get_body())
        self.assertIn("JSON", body["error"])



# 5. Service Bus error handling 


class TestServiceBusErrors(unittest.TestCase):

    def test_auth_error_returns_503(self):
        from azure.servicebus.exceptions import ServiceBusAuthenticationError
        req = _make_request(body=VALID_PAYLOAD)

        with patch("function_app.ServiceBusClient") as mock_sb_class:
            mock_sb_class.return_value.__enter__.side_effect = ServiceBusAuthenticationError()
            resp = function_app.submit_job(req)

        self.assertEqual(resp.status_code, 503)
        body = json.loads(resp.get_body())
        self.assertIn("authentication", body["error"].lower())

    def test_connection_error_returns_503(self):
        from azure.servicebus.exceptions import ServiceBusConnectionError
        req = _make_request(body=VALID_PAYLOAD)

        with patch("function_app.ServiceBusClient") as mock_sb_class:
            mock_sb_class.return_value.__enter__.side_effect = ServiceBusConnectionError()
            resp = function_app.submit_job(req)

        self.assertEqual(resp.status_code, 503)

    def test_unexpected_error_returns_500(self):
        req = _make_request(body=VALID_PAYLOAD)

        with patch("function_app.ServiceBusClient") as mock_sb_class:
            mock_sb_class.return_value.__enter__.side_effect = RuntimeError("boom")
            resp = function_app.submit_job(req)

        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
