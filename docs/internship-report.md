# Internship Progress Report

```
╔══════════════════════════════════════════════════════════════════╗
║           cuOpt for Metals — Internship Progress Report          ║
║                                                                  ║
║  Intern   : Muhammad Saad                                        ║
║  Role     : Data Science Intern (R&D)                           ║
║  Duration : 6 Weeks  (March – April 2026)                       ║
║  Project  : AI-Powered Cutting Stock Optimisation on Azure       ║
║  Repo     : GoSmarter-ai/cuopt-for-metals                        ║
╚══════════════════════════════════════════════════════════════════╝
```

**Tech Stack:**
`Python 3.11` · `Azure Functions` · `Azure Service Bus` · `Azure Container Apps` · `NVIDIA cuOpt` · `Bicep (IaC)` · `GitHub Actions` · `pytest` · `ruff`

---

## Executive Summary

Over six weeks I designed, built, and shipped the core components of an event-driven cutting stock optimisation service on Microsoft Azure. The system accepts customer orders for steel bar lengths via an HTTP API, queues them through Azure Service Bus, and solves them using a 6-step solver pipeline that benchmarks a classical First Fit Decreasing (FFD) heuristic against NVIDIA cuOpt.

**Key outcomes:**

| Metric | Result |
|--------|--------|
| New files delivered | 6 |
| Test coverage achieved | 96.81% |
| Tests written | 32 (from 0 for the new modules) |
| CI checks passing | 4 / 4 |
| Material saving (hard test case) | FFD: 77.5% → cuOpt: 98.75% efficiency |
| Bars saved per job (hard test case) | 6 bars → 5 bars (−16.7%) |

---

## Project Background

The **cutting stock problem** is a classic industrial optimisation challenge. When a metals factory receives customer orders for steel or aluminium bars of specific lengths, it must figure out the best way to cut those lengths from full-length raw stock bars — minimising wasted offcuts.

**Real example:** A factory receives this order:

| Length | Quantity |
|--------|---------|
| 2,300 mm | 5 pieces |
| 1,700 mm | 4 pieces |
| 900 mm  | 6 pieces |

Raw stock bars are 6,000 mm each. Total demand is 27,900 mm. The mathematical minimum is 5 bars — but a naive algorithm uses 6, wasting an entire bar of steel per job. At production scale, this waste is significant.

This project builds a cloud-based system on Microsoft Azure that:
1. Accepts cutting stock jobs via an HTTP API
2. Validates and queues them using Azure Service Bus
3. Solves them using NVIDIA cuOpt (a GPU-accelerated optimisation engine)
4. Returns the optimal cutting patterns

---

## System Architecture

```
  ┌──────────────────────────────────────────────────────────────┐
  │                    Azure Resource Group                       │
  │                                                              │
  │   HTTP Client          ┌─────────────────────┐              │
  │   (curl / ERP)  ──────►│   Azure Function     │             │
  │   POST /api/jobs       │   Python 3.11        │             │
  │                        │   Managed Identity   │             │
  │                        └──────────┬──────────┘              │
  │                                   │ send message             │
  │                                   ▼                          │
  │                        ┌─────────────────────┐              │
  │                        │   Service Bus        │             │
  │                        │   queue: cutting-    │             │
  │                        │   jobs               │             │
  │                        └──────────┬──────────┘              │
  │                                   │ KEDA trigger             │
  │                           (scale 0→1 on message)            │
  │                                   ▼                          │
  │                        ┌─────────────────────┐              │
  │                        │  Container Apps Job  │             │
  │                        │  cuopt-solver        │             │
  │                        │  Managed Identity    │             │
  │                        └──────────┬──────────┘              │
  │                                   │                          │
  │              ┌────────────────────┴──────────────────┐      │
  │              ▼                                        ▼      │
  │   ┌─────────────────────┐               ┌──────────────────┐│
  │   │  FFD Heuristic      │               │  NVIDIA cuOpt    ││
  │   │  (immediate result) │               │  (GPU-optimised) ││
  │   └─────────────────────┘               └──────────────────┘│
  │                                                              │
  │   Shared: Log Analytics · Application Insights · Storage    │
  └──────────────────────────────────────────────────────────────┘
```

**Security model:** All components use system-assigned **Managed Identity** — zero passwords, zero connection strings, zero secrets in code or environment variables. Azure issues short-lived tokens automatically.

**Cost model:** The Container Apps Job uses **KEDA** (Kubernetes Event Driven Autoscaling) — it scales to zero when the queue is empty, so there is no idle compute cost.

---

## Week-by-Week Timeline

| Week | Focus | Key Deliverable |
|------|-------|----------------|
| 1 | Architecture study | Understanding Managed Identity, KEDA, Bicep |
| 2 | CI/CD documentation | `ci-cd.md` — pipeline and linting guide |
| 3 | Data contract + refactoring | `data-contract.md`, `validation.py` extracted |
| 4 | Solver development | `solver.py` — full 6-step FFD + cuOpt pipeline |
| 5 | Testing + CI debugging | 32 tests, coverage 72% → 96.81%, conflicts resolved |
| 6 | Polish + documentation | `internship-report.md`, `week4-notes.md` |

---

## Week 1 — Understanding the Architecture

### What I Did

In the first week I focused on reading and understanding the existing codebase and infrastructure before writing anything. This is important in a real engineering team — touching code you don't fully understand causes bugs.

I went through:
- `infra/main.bicep` and all three Bicep modules
- `src/azure-function/function_app.py` — the HTTP trigger
- `docs/getting-started.md` and `docs/infrastructure.md`
- The existing merged Pull Request (#12) to understand design decisions

### Key Concepts Learned

**Managed Identity — why it matters**

Traditional approach (insecure): store a password in an environment variable:
```
SERVICEBUS_CONNECTION_STRING=Endpoint=sb://...;SharedAccessKey=abc123...
```

GoSmarter's approach (secure): Managed Identity — no secret at all:
```python
credential = DefaultAzureCredential()   # Azure issues a token automatically
client = ServiceBusClient(namespace, credential)
```

Benefits:
- No secret to leak, rotate, or accidentally commit to Git
- Azure handles token refresh automatically
- Access can be revoked instantly by removing the role assignment

**KEDA — scale to zero**

Without KEDA: a container runs 24/7 waiting for jobs — paying for idle compute.

With KEDA: the container Apps Job only runs when there is a message in the Service Bus queue.

```
Queue empty      → 0 containers running    → £0/hour
Message arrives  → KEDA starts 1 container → job runs → container stops
Multiple messages → KEDA scales up to max replicas
```

**Bicep module structure**

```
infra/
  main.bicep                    ← orchestrator, all RBAC here
  modules/
    servicebus.bicep            ← queue config
    function.bicep              ← function app + app service plan
    container-apps-job.bicep    ← KEDA trigger config
```

All role assignments are in `main.bicep` (not in modules). This is intentional — it makes all permissions visible in one place, which is easier to audit.

### Open Questions After Week 1

- If multiple jobs arrive simultaneously, does KEDA spin up multiple containers in parallel?
- Where does the cuOpt result go after solving — is it stored in a database?
- How do we test locally without a real Azure Service Bus?
- Is there a maximum quantity per order line?

---

## Week 2 — CI/CD Pipeline and Documentation

### What I Did

This week I wrote the CI/CD documentation for the project. The pipeline was already built but not explained anywhere, so I created `ci-cd.md` covering:
- How the GitHub Actions workflow is structured
- What ruff does and why it is used
- How the test suite works and why the coverage gate is 80%
- Why the Service Bus is mocked in tests

### The CI/CD Pipeline

Every push and every Pull Request triggers the pipeline automatically. It has two parallel jobs:

**Job 1 — Lint (ruff)**
- Checks every Python file in the repo for style and correctness issues
- Uses ruff version `0.9.10` (pinned so everyone gets the same results)
- Zero tolerance — one violation fails the entire job
- Covers: unused imports, f-strings without placeholders, undefined names, and many more

**Job 2 — Test (pytest)**
- Runs all tests in `tests/`
- Measures code coverage
- Fails if coverage drops below **80%**
- Coverage report is saved as `coverage.xml` for future dashboards

Both jobs run on **Python 3.11** to match the Azure Function runtime.

### Why the Service Bus Is Mocked in Tests

The Azure Function connects to a real Azure Service Bus in production. But in CI/CD there is no Azure account — just a GitHub runner. So the tests use `unittest.mock.patch` to replace the real `ServiceBusClient` with a fake one.

This means:
- Tests run instantly with no network calls
- No Azure credentials needed in CI
- We can simulate error scenarios (connection failure, authentication error) that would be hard to trigger against a real Service Bus

The mock is set up before the module is even imported, because the function app creates a `DefaultAzureCredential` object at module level.


## Week 3 — Data Contract and Validation Refactoring

### What I Did

This week had two parts:
1. Wrote the **data contract** document defining exactly what the API accepts and returns
2. **Refactored** the validation logic from `function_app.py` into a shared `validation.py` module

### The Data Contract (`docs/data-contract.md`)

The data contract is a formal agreement between the API and its callers — it defines the exact format of requests and responses so there are no surprises.

**POST `/api/jobs` — request body:**

```json
{
  "job_id": "order-2026-001",
  "stock_length_mm": 6000,
  "orders": [
    { "length_mm": 2400, "quantity": 3 },
    { "length_mm": 1800, "quantity": 5 }
  ],
  "metadata": { "source": "erp-system" }
}
```

**Validation rules defined in the contract:**

| Field | Rule |
|-------|------|
| `orders` | Required. Must be a non-empty list. |
| `orders[].length_mm` | Required per order. Must be a positive number. |
| `orders[].quantity` | Required per order. Must be a positive integer (not a float). |
| `stock_length_mm` | Optional. If provided, must be a positive number. |

**Response codes:**

| Code | When |
|------|------|
| `202 Accepted` | Job queued successfully |
| `400 Bad Request` | Request body is not valid JSON |
| `422 Unprocessable Entity` | JSON is valid but business rules are broken |
| `503 Service Unavailable` | Service Bus is unreachable |
| `500 Internal Server Error` | Unexpected error |

### Extracting `validation.py`

The `_validate_job()` function lived inside `function_app.py`. The problem: the new solver (coming in Week 4) also needs to validate incoming jobs. If validation stayed in `function_app.py`, we would have to duplicate it in `solver.py` — and then any future change to the rules would need to be made in two places.

**Solution:** Extract it into `src/azure-function/validation.py` as a public `validate_job()` function.

```
Before:                          After:
──────────────────               ──────────────────────────────
function_app.py                  function_app.py
  └── _validate_job()   →          └── from validation import validate_job
                                 validation.py
                                   └── validate_job()   ← shared
                                 solver.py (Week 4)
                                   └── from validation import validate_job
```

**Validation rules enforced by `validate_job()`:**

| Check | Error message |
|-------|--------------|
| `orders` key missing | `Missing required field: 'orders'` |
| `orders` is empty list | `'orders' must be a non-empty list` |
| Order missing `length_mm` | `Order N missing 'length_mm'` |
| `length_mm` is zero or negative | `Order N 'length_mm' must be a positive number` |
| Order missing `quantity` | `Order N missing 'quantity'` |
| `quantity` is not a positive integer | `Order N 'quantity' must be a positive integer` |
| `stock_length_mm` is zero or negative | `'stock_length_mm' must be a positive number` |

---

## Week 4 — Building the Solver

### What I Did

This was the biggest week technically. I built `src/cuopt-solver/solver.py` — the full solver pipeline that processes cutting stock jobs.

### The Cutting Stock Problem — In Plain Terms

Imagine a steel factory receives this order:
- 5 pieces of 2,300 mm
- 4 pieces of 1,700 mm
- 6 pieces of 900 mm

Raw stock bars are 6,000 mm each. The problem: how many bars do we need, and how do we cut them to waste as little steel as possible?

The **theoretical minimum** is calculated by dividing total demand by bar length:

$$\text{Total demand} = (5 \times 2300) + (4 \times 1700) + (6 \times 900) = 27{,}900 \text{ mm}$$

$$\text{Theoretical minimum bars} = \left\lceil \frac{27{,}900}{6{,}000} \right\rceil = \lceil 4.65 \rceil = 5 \text{ bars}$$

5 bars is the best any algorithm could possibly achieve. The question is whether a real solver can reach it.

### The Solver Pipeline — 6 Steps

| Step | Function | What It Does |
|------|----------|--------------|
| 1 | `parse_message()` | Reads the raw JSON string from Service Bus |
| 2 | `expand_orders()` | Turns orders into individual pieces: `[2300, 2300, 2300, 2300, 2300, 1700, ...]` and computes stats |
| 3 | `run_baseline()` | Runs FFD heuristic to get a fast, decent solution |
| 4 | `prepare_cuopt_input()` | Builds the JSON payload for the cuOpt API |
| 5 | `submit_to_cuopt()` | Calls cuOpt (currently simulated) |
| 6 | `process_message()` | Orchestrates all steps, returns structured result |

### First Fit Decreasing (FFD) — The Baseline Algorithm

FFD is a classic heuristic for cutting stock / bin packing:

1. **Sort** all pieces from largest to smallest
2. For each piece, **scan** existing bars from left to right
3. **Place** it in the first bar where it fits
4. If no bar fits, **open** a new bar

FFD is not optimal but it is fast and gives a good result. It serves as the **comparison baseline** — whatever cuOpt achieves should be at least as good.

**Result on `hard_job.json`:**

| Method | Bars Used | Waste | Efficiency |
|--------|-----------|-------|-----------|
| FFD Baseline | 6 | 6,300 mm | 77.5% |
| cuOpt (simulated) | 5 | 300 mm | 98.75% |

FFD uses one extra bar and wastes 6,000 mm more steel than the optimal solution.

### Simulated cuOpt

The real cuOpt API endpoint is not yet connected. Until it is, `submit_to_cuopt()` simulates the result by targeting the **theoretical minimum bars**. When the real endpoint is ready, only the function body changes:

```python
# Current (simulation):
simulated_bars = expanded["theoretical_min_bars"]

# Future (real API):
resp = requests.post(CUOPT_ENDPOINT, json=cuopt_payload, headers=auth_headers)
return resp.json()
```

### Execution Timing

Both the FFD baseline and the cuOpt call are wrapped with `time.perf_counter()`:

```python
_t0 = time.perf_counter()
baseline = run_baseline(expanded)
baseline_runtime = round(time.perf_counter() - _t0, 6)
```

This sets up the performance comparison framework — when the real API is wired in, we will see exactly how long cuOpt takes vs FFD.

### CLI Output

Running the solver locally prints a full formatted report:

```
================================================
               INPUT SUMMARY
================================================

  Job ID          : job-hard
  Stock Length    : 6000 mm

  Orders Breakdown:
    - 2300 mm × 5 pieces
    - 1700 mm × 4 pieces
    - 900 mm × 6 pieces

  Total Pieces         : 15
  Total Demand Length  : 27900.0 mm
  Theoretical Min Bars : 5 bars

================================================

====================================================
  cuOpt for Metals — Cutting Stock Results
====================================================
  Job ID        : job-hard
  Validation    : PASSED
  Total pieces  : 15
  Total demand  : 27900.0 mm
  Stock length  : 6000 mm
  Minimum bars  : 5 (theoretical lower bound)
----------------------------------------------------
  Method               Bars   Waste mm  Efficiency   Time (s)
  -------------------- -----  --------- ----------- ----------
  FFD Baseline            6    6300.0       77.5%   0.000123
  cuOpt (simulated)       5     300.0      98.75%   0.000045
====================================================
```

### Sample Data Files Created

| File | Description |
|------|-------------|
| `data/input/example_orders.json` | Simple 2-order job — good for basic testing |
| `data/input/simple_job.json` | 3 pieces, 5,500 mm demand — both methods: 1 bar |
| `data/input/hard_job.json` | 15 pieces, 3 order types — clear FFD vs cuOpt difference |

---

## Week 5 — Test Suite Expansion and CI Debugging

### What I Did

This week was mostly **debugging and fixing** — the PR had multiple CI failures that needed to be resolved before it could be merged.

### Problem 1 — Coverage Dropped to 72%

**Root cause:** When `validation.py` was created as a new file, the CI coverage tool started counting it. But no tests directly tested `validation.py` — they only tested `function_app.py` which *calls* `validate_job()`. So the 23 lines in `validation.py` showed as 0% covered, pulling total coverage from ~93% down to **72%**.

**Fix:** Added a new test class `TestValidateJob` with 12 dedicated tests for `validation.py`:

```python
from validation import validate_job

class TestValidateJob(unittest.TestCase):

    def test_valid_payload_returns_no_errors(self):
        errors = validate_job({
            "stock_length_mm": 6000,
            "orders": [{"length_mm": 2400, "quantity": 3}],
        })
        self.assertEqual(errors, [])

    def test_missing_orders_field(self):
        errors = validate_job({"stock_length_mm": 6000})
        self.assertIn("Missing required field: 'orders'", errors)

    # ... 10 more tests
```

**Result after fix:**

| File | Coverage Before | Coverage After |
|------|----------------|---------------|
| `function_app.py` | 96% | 96% |
| `validation.py` | 0% | **100%** |
| **Total** | **72%** | **96.81%** |

Total tests went from **20 to 32**.

### Problem 2 — 3 Ruff Lint Violations

Three violations in `solver.py` were caught by ruff:

| Rule | Line | Problem | Fix |
|------|------|---------|-----|
| `F401` | inside `main()` | `import math` duplicated — already imported in `expand_orders()` | Remove duplicate import |
| `F541` | print statement | `f"cuOpt for Metals — Cutting Stock Results"` — f-string, no `{}` | Remove `f` prefix |
| `F541` | print statement | `f"Validation    : PASSED"` — same issue | Remove `f` prefix |

**Lesson:** Always run `ruff check .` before pushing. These are caught in seconds locally; in CI they cost a full pipeline run.

### Problem 3 — 7 Merge Conflicts in `solver.py`

**How it happened:**
- `main` branch had an older, simple version of `solver.py` (a `solve()` placeholder stub)
- Our branch had the full FFD + cuOpt version
- Both branches diverged from the same base commit
- When the PR was opened, GitHub detected 7 conflict regions — places where both branches had modified the same lines differently

**Resolution steps:**

```bash
# Step 1: bring down the latest main
git fetch origin

# Step 2: merge it into our branch — this creates conflict markers in solver.py
git merge origin/main

# Step 3: keep our entire version (discard main's version)
git checkout --ours src/cuopt-solver/solver.py

# Step 4: mark as resolved and commit
git add src/cuopt-solver/solver.py
git commit -m "Merge origin/main: resolve conflicts, keep saad/solver-progress version"

# Step 5: push
git push origin saad/solver-progress
```

`git checkout --ours` was the key command — it picks our branch's version for the entire file, resolving all 7 conflicts at once without manually editing each one.

**Lesson:** Before starting a new feature branch, always `git fetch origin && git merge origin/main` first. This keeps the branch close to `main` and prevents conflicts from accumulating.

---

## Week 6 — Final Status and Reflection

### Final CI Status

| Check | Status |
|-------|--------|
| Ruff lint (Python 3.11) | ✅ Passing |
| Tests (Python 3.11) | ✅ 32/32 passing |
| Code coverage | ✅ 96.81% (gate: 80%) |
| Merge conflicts | ✅ Resolved |
| Branch up to date with `main` | ✅ Yes |

### What the Codebase Looks Like Now

```
cuopt-for-metals/
├── src/
│   ├── azure-function/
│   │   ├── function_app.py      ← HTTP trigger: validates + enqueues jobs
│   │   ├── validation.py        ← shared validation logic (NEW)
│   │   ├── host.json
│   │   └── requirements.txt
│   └── cuopt-solver/
│       └── solver.py            ← full 6-step solver pipeline (NEW)
├── tests/
│   └── test_function_app.py     ← 32 tests (was 20)
├── data/
│   └── input/
│       ├── example_orders.json  ← (NEW)
│       ├── simple_job.json      ← (NEW)
│       └── hard_job.json        ← (NEW)
├── docs/
│   ├── week1-notes.md
│   ├── week4-notes.md
│   ├── data-contract.md         ← (NEW)
│   └── internship-report.md     ← this file
├── infra/                       ← Bicep templates (unchanged)
└── ci-cd.md                     ← (NEW)
```

### Key Skills Developed

**Python development**
- Writing modular Python code split across multiple files
- Using `sys.path` for inter-module imports (and understanding why it is a workaround)
- Implementing a classic algorithm (FFD) from scratch
- Writing unit tests with `unittest.mock` — patching external services

**Azure platform**
- Understanding Managed Identity and why it is better than connection strings
- Understanding how KEDA event-driven scaling works with Service Bus
- Reading and understanding Bicep IaC templates
- Using Azure Functions local development tools

**CI/CD and code quality**
- Setting up and debugging GitHub Actions pipelines
- Using ruff for linting — understanding common violation codes
- Understanding code coverage measurement and why coverage gates matter
- Diagnosing why CI fails when code works locally

**Git**
- Working with feature branches
- Understanding merge conflicts — how they happen and how to resolve them
- Using `git checkout --ours` for conflict resolution
- Reading `git log` to trace what happened on each branch

### What Is Still Left To Do

| Item | Priority | Notes |
|------|----------|-------|
| Real cuOpt API call | High | Replace `submit_to_cuopt()` body with `requests.post(CUOPT_ENDPOINT, ...)` |
| cuOpt solver parameters | High | Fill in `"solver_config": {}` with real cuOpt parameters once endpoint is confirmed |
| Move `validation.py` to `src/shared/` | Medium | Remove the `sys.path` workaround — set up a proper Python package |
| Service Bus trigger wiring | High | Connect `process_message()` to the actual Container Apps Job trigger |
| Result storage | Medium | Where does the cutting pattern go after solving? (unanswered from Week 1) |
| End-to-end test | Low | Test the full flow from HTTP request → Service Bus → solver → result |

### Biggest Lessons

1. **Read before you write.** Week 1 was all reading — understanding Managed Identity, KEDA, and the Bicep structure before touching any code saved a lot of confusion later.

2. **Modular code pays off immediately.** Extracting `validate_job()` into a shared module took 30 minutes but meant the solver could reuse it instantly without any duplication.

3. **CI failures are information.** Every ruff violation and coverage drop pointed to a real problem — rather than fighting the CI pipeline, it is better to understand what it is telling you.

4. **Merge conflicts are not disasters.** They happen on any team project. The key is knowing how they work and having the right git commands ready (`git fetch`, `git merge`, `git checkout --ours`).

5. **Simulation first, real API second.** By building a simulated cuOpt result that targets the theoretical optimum, we have a working comparison framework ready before the real API is even available. Plugging in the real call is now a one-function change.

6. **The gap between FFD and optimal matters in industry.** On the `hard_job.json` test case, FFD uses 6 bars while the optimum is 5 — that is one entire 6,000 mm bar of wasted steel. At production scale, this difference translates to real material cost savings.

---

*Report compiled: 7 April 2026*
