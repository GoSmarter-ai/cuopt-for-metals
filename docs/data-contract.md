# Data Contract — Cutting Stock Job API

This document defines the request and response schemas for the cuOpt for Metals
HTTP API exposed by the Azure Function. It is the authoritative reference for
clients, the solver container, and integration tests.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Submit a new cutting-stock optimisation job |
| `GET` | `/api/health` | Liveness check |

All endpoints require an Azure Functions **function key** passed as either the
`x-functions-key` header or the `code` query parameter (auth level: `FUNCTION`).

All request and response bodies use `Content-Type: application/json`.

---

## POST /api/jobs

### Request body

```json
{
  "stock_length_mm": 6000,
  "orders": [
    { "length_mm": 2400, "quantity": 3 },
    { "length_mm": 1800, "quantity": 5 }
  ],
  "metadata": { "customer_ref": "ORD-9981" }
}
```

#### Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `orders` | array of [Order](#order-object) | **Yes** | The list of cut pieces to produce. Must contain at least one item. |
| `stock_length_mm` | number | No | Length of the raw stock bar/sheet in millimetres. When omitted, the value of the `STOCK_LENGTH_MM` environment variable is used (default `6000`). |
| `metadata` | object | No | Arbitrary key/value pairs passed through to the solver unchanged. Useful for storing customer reference numbers, order IDs, etc. Not validated. |

#### Order object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `length_mm` | number | **Yes** | Desired cut length in millimetres. Must be a positive number (`> 0`). Accepts integers and floats. |
| `quantity` | integer | **Yes** | Number of pieces of this length required. Must be a positive integer (`>= 1`). Floats are not accepted. |

### Validation rules

The function applies the following checks before enqueueing the job. All
violations are collected and returned together in a single 422 response.

| Rule | Error message |
|------|---------------|
| `orders` field must be present | `"Missing required field: 'orders'"` |
| `orders` must be a non-empty list | `"'orders' must be a non-empty list"` |
| Each order must include `length_mm` | `"orders[N] missing 'length_mm'"` |
| `length_mm` must be a positive number | `"orders[N].length_mm must be a positive number"` |
| Each order must include `quantity` | `"orders[N] missing 'quantity'"` |
| `quantity` must be a positive integer | `"orders[N].quantity must be a positive integer"` |
| If `stock_length_mm` is provided, it must be a positive number | `"'stock_length_mm' must be a positive number if provided"` |

`N` in the messages above is the zero-based index of the offending order.

### Responses

#### 202 Accepted — job queued successfully

```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "queued",
  "message": "Job accepted and queued for processing"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string (UUID v4) | Unique identifier assigned to this job. Use it to correlate logs and results. |
| `status` | string | Always `"queued"` on a 202 response. |
| `message` | string | Human-readable confirmation. |

#### 400 Bad Request — request body is not valid JSON

```json
{
  "error": "Request body must be valid JSON"
}
```

#### 422 Unprocessable Entity — payload fails validation

```json
{
  "error": "Validation failed",
  "details": [
    "orders[0].length_mm must be a positive number",
    "orders[1] missing 'quantity'"
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Always `"Validation failed"`. |
| `details` | array of string | One entry per validation violation. Multiple errors can be present in a single response. |

#### 503 Service Unavailable — Service Bus unreachable or auth failure

```json
{
  "error": "Service Bus authentication failed"
}
```

```json
{
  "error": "Service Bus connection failed – please retry"
}
```

Returned when the function cannot communicate with Azure Service Bus due to
misconfigured managed identity role assignments (authentication) or a transient
network issue (connection). Clients should apply exponential back-off before
retrying.

#### 500 Internal Server Error — unexpected failure

```json
{
  "error": "Failed to enqueue job",
  "detail": "<exception message>"
}
```

---

## GET /api/health

No request body.

### Response

#### 200 OK

```json
{
  "status": "healthy"
}
```

Use this endpoint for readiness/liveness probes and smoke tests after
deployment.

---

## Internal: Service Bus message schema

When a job is accepted, the function places a single message on the Service Bus
queue. The solver container consumes this message. The message body is JSON with
the following structure:

```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "submitted_at": "2026-03-17T09:14:32.456789+00:00",
  "stock_length_mm": 6000,
  "orders": [
    { "length_mm": 2400, "quantity": 3 },
    { "length_mm": 1800, "quantity": 5 }
  ],
  "metadata": { "customer_ref": "ORD-9981" }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string (UUID v4) | Same value returned to the caller in the 202 response. |
| `submitted_at` | string (ISO 8601, UTC) | Timestamp when the function enqueued the message. |
| `stock_length_mm` | number | Resolved stock length: caller-supplied value, or the `STOCK_LENGTH_MM` env default. |
| `orders` | array of Order | Passed through unchanged from the request body. |
| `metadata` | object | Passed through unchanged from the request body. Empty object `{}` if not provided. |

The Service Bus message also carries:

- **`message_id`** — set to the `job_id` UUID, enabling deduplication.
- **`content_type`** — `application/json`.

---

## Full worked examples

### Example 1 — minimal valid request

**Request**

```http
POST /api/jobs HTTP/1.1
Content-Type: application/json
x-functions-key: <your-function-key>

{
  "orders": [
    { "length_mm": 3000, "quantity": 2 }
  ]
}
```

**Response** `202 Accepted`

```json
{
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued",
  "message": "Job accepted and queued for processing"
}
```

`stock_length_mm` defaults to `6000` (from the `STOCK_LENGTH_MM` env var).
`metadata` defaults to `{}`.

---

### Example 2 — full request with all fields

**Request**

```http
POST /api/jobs HTTP/1.1
Content-Type: application/json
x-functions-key: <your-function-key>

{
  "stock_length_mm": 9000,
  "orders": [
    { "length_mm": 4200, "quantity": 4 },
    { "length_mm": 2100, "quantity": 7 },
    { "length_mm": 900,  "quantity": 12 }
  ],
  "metadata": {
    "customer_ref": "ORD-9981",
    "material": "EN10025 S355",
    "requested_by": "alice@example.com"
  }
}
```

**Response** `202 Accepted`

```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued",
  "message": "Job accepted and queued for processing"
}
```

---

### Example 3 — validation failure (multiple errors)

**Request**

```http
POST /api/jobs HTTP/1.1
Content-Type: application/json
x-functions-key: <your-function-key>

{
  "stock_length_mm": -500,
  "orders": [
    { "length_mm": -100, "quantity": 3 },
    { "quantity": 2 }
  ]
}
```

**Response** `422 Unprocessable Entity`

```json
{
  "error": "Validation failed",
  "details": [
    "orders[0].length_mm must be a positive number",
    "orders[1] missing 'length_mm'",
    "'stock_length_mm' must be a positive number if provided"
  ]
}
```

---

### Example 4 — malformed JSON body

**Request**

```http
POST /api/jobs HTTP/1.1
Content-Type: application/json
x-functions-key: <your-function-key>

not-valid-json
```

**Response** `400 Bad Request`

```json
{
  "error": "Request body must be valid JSON"
}
```
