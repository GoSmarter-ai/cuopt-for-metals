# CI/CD Pipeline and Linting

This document describes the GitHub Actions CI/CD pipeline and the ruff linting
configuration used in the cuOpt for Metals project.

---

## Overview

Every push and pull request triggers an automated CI pipeline defined in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). The pipeline runs two
independent jobs in parallel:

| Job | Purpose |
|-----|---------|
| **Lint** | Static analysis with ruff — catches style issues and common errors |
| **Test** | Runs the full pytest suite with a minimum 80% code coverage gate |

---

## How the Pipeline Works

### Trigger conditions

```yaml
on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["**"]
```

The pipeline fires on **every branch** for both pushes and pull requests, so
issues are caught early regardless of where the work is happening.

### Job 1 — Lint (`ruff`)

1. Checks out the repository.
2. Installs Python 3.11 with pip cache keyed on `requirements-dev.txt`.
3. Installs `ruff==0.9.10` (pinned to match the dev dependency).
4. Runs `ruff check .` across the entire repository.

The job fails immediately if any ruff violation is found. No auto-fix is applied
in CI; fixes must be committed by the developer.

### Job 2 — Test (`pytest`)

1. Checks out the repository.
2. Installs Python 3.11 with pip cache keyed on both `requirements-dev.txt` and
   `src/azure-function/requirements.txt`.
3. Installs all dev and function-app dependencies.
4. Runs pytest with coverage:

   ```bash
   pytest tests/ -v \
     --cov=src/azure-function \
     --cov-report=term-missing \
     --cov-report=xml:coverage.xml \
     --cov-fail-under=80
   ```

   - `--cov-fail-under=80` enforces an 80% minimum line-coverage threshold.
     The job fails if coverage drops below this.
   - A `coverage.xml` report is uploaded as a GitHub Actions artifact
     (`coverage-report`) after every run, even if the job fails, so developers
     can inspect which lines are uncovered.

---

## Linting Configuration

The project uses [ruff](https://docs.astral.sh/ruff/) for linting, pinned at
version `0.9.10` in [`requirements-dev.txt`](requirements-dev.txt).

ruff is an extremely fast Python linter that replaces Flake8, isort, pyupgrade,
and several other tools in a single binary.

### Running ruff locally

```bash
# Check for violations (mirrors what CI runs)
ruff check .

# Check a specific file or directory
ruff check src/azure-function/

# Auto-fix safe violations
ruff check --fix .

# Show which rules would be applied
ruff check --show-rules
```

### Configuration

There is no project-level `pyproject.toml` or `ruff.toml` at this time, so
ruff uses its built-in defaults. To customise rules, add a `[tool.ruff]` section
to `pyproject.toml` or create a `ruff.toml` at the repository root. For
example:

```toml
# pyproject.toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP"]
ignore = ["E501"]
```

### Other dev tools

`requirements-dev.txt` also includes:

| Tool | Version | Purpose |
|------|---------|---------|
| `black` | 24.10.0 | Opinionated code formatter (run locally, not in CI) |
| `pylint` | 3.3.3 | Additional deep static analysis (run locally, not in CI) |

---

## Running Tests Locally

### Prerequisites

Make sure you have a virtual environment with all dev dependencies installed:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
pip install -r src/azure-function/requirements.txt
```

### Run the full test suite

```bash
# From the repository root
pytest tests/ -v
```

### Run with coverage (mirrors CI)

```bash
pytest tests/ -v \
  --cov=src/azure-function \
  --cov-report=term-missing \
  --cov-fail-under=80
```

`--cov-report=term-missing` prints a line-by-line breakdown of which lines are
not covered directly in the terminal output.

### Run a single test file or test

```bash
# Run one file
pytest tests/test_function_app.py -v

# Run a single test by name
pytest tests/test_function_app.py::TestSubmitJob::test_valid_payload -v
```

### No Azure connection required

The test suite mocks the Azure Service Bus client and `DefaultAzureCredential`
entirely via `unittest.mock`, so tests run offline without any Azure
subscription or credentials.

---

## Unit Tests for the Azure Function

All tests live in [`tests/test_function_app.py`](tests/test_function_app.py)
and target [`src/azure-function/function_app.py`](src/azure-function/function_app.py).
The suite is organised into five test classes, each covering a distinct
behaviour of the HTTP-trigger function.

### What is tested

| Class | Scenarios covered |
|-------|-------------------|
| `TestHealthCheck` | `GET /api/health` returns HTTP 200 with `{"status": "healthy"}` |
| `TestValidJobSubmission` | Happy-path `POST /api/jobs`: returns 202, body contains `job_id` and `status: queued`, `ServiceBusClient.send_messages` is called exactly once, the enqueued message body contains all expected fields, and the env-default `STOCK_LENGTH_MM` is used when the caller omits `stock_length_mm` |
| `TestNegativeLength` | Negative and zero `length_mm`; negative `stock_length_mm` — all return 422 with a `details` array that names the offending field |
| `TestMissingFields` | Missing `orders` field, empty `orders` list, missing `length_mm` or `quantity` in an order item, both fields missing at once (both errors reported), and an unparseable JSON body (returns 400) |
| `TestServiceBusErrors` | `ServiceBusAuthenticationError` → 503 with "authentication" in the error message; `ServiceBusConnectionError` → 503; any unexpected `RuntimeError` → 500 |

### Why the Service Bus is mocked

The function communicates with Azure Service Bus through the
`azure-servicebus` SDK, which requires a live namespace, network access, and
valid credentials. Relying on a real Service Bus in unit tests would:

- make tests slow and flaky (network latency, throttling, transient errors),
- require every developer and every CI run to have an active Azure subscription
  and correctly configured credentials, and
- introduce test pollution (real messages sent to a shared queue).

Instead, `unittest.mock.patch` replaces `function_app.ServiceBusClient` with a
`MagicMock` that honours the nested context-manager protocol used by the SDK
(`with ServiceBusClient(...) as sb: / with sb.get_queue_sender(...) as sender:`).
This lets tests assert that `sender.send_messages` was called correctly — and
inject `ServiceBusAuthenticationError` or `ServiceBusConnectionError` to
exercise the error-handling paths — without any Azure dependency.

### Import-time bootstrap order

`function_app.py` executes two side-effects at module import time:

1. Reads `AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE` and
   `AZURE_SERVICEBUS_QUEUE_NAME` from `os.environ`.
2. Calls `DefaultAzureCredential()` to build the module-level `_credential`
   object.

The test module handles this carefully:

```python
# 1. Set required env vars before the import
os.environ.setdefault("AZURE_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE", "test.servicebus.windows.net")
os.environ.setdefault("AZURE_SERVICEBUS_QUEUE_NAME", "test-queue")

# 2. Patch DefaultAzureCredential at import time so no real credential
#    discovery is attempted (no az login / managed identity needed)
with patch("azure.identity.DefaultAzureCredential"):
    import function_app
```

If these steps were performed in the wrong order, the import would either raise
a `KeyError` (missing env var) or attempt real Azure credential resolution
before any mock was in place.

---

## Adding New Tests

- Place test files under `tests/` following the `test_*.py` naming convention.
- Mock all external Azure SDK calls using `unittest.mock.patch` so tests remain
  fast and offline-safe.
- Ensure any new code paths are covered to keep the 80% coverage gate green.
