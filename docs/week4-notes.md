# Week 4 Notes — Solver Development, CI/CD Fixes & Code Quality

**Branch:** `saad/solver-progress`  
**Date:** 7 April 2026  
**Status:** All CI checks passing ✅

---

## Overview

Week 4 focused on three main areas:

1. **Building the cuOpt solver** — a full 6-step pipeline that reads a cutting stock job, runs a First Fit Decreasing (FFD) heuristic baseline, and simulates a cuOpt result for comparison.
2. **Code refactoring** — moved validation logic to a shared module (`validation.py`) so it can be reused across the Azure Function and the solver.
3. **CI/CD fixes** — resolved ruff lint violations, a coverage regression, and 7 merge conflicts that were blocking the PR from merging.

---

## What Was Built

### `src/cuopt-solver/solver.py` — The Solver Pipeline

The solver is the main deliverable of this week. It is a standalone Python module that can be run from the CLI for local testing, and will eventually be triggered by a Service Bus message in the Container Apps Job.

The pipeline has 6 steps:

| Step | Function | Description |
|------|----------|-------------|
| 1 | `parse_message()` | Deserialises the raw JSON string from Service Bus |
| 2 | `expand_orders()` | Expands orders into a flat list of individual piece lengths and computes summary stats (total demand, theoretical minimum bars) |
| 3 | `run_baseline()` | Runs the FFD heuristic and returns patterns showing how pieces fit into bars |
| 4 | `prepare_cuopt_input()` | Builds the payload structure that will be sent to the cuOpt API |
| 5 | `submit_to_cuopt()` | Currently simulated — models cuOpt finding the theoretical optimum |
| 6 | `process_message()` | Orchestrates the full pipeline and returns a structured result dict |

#### First Fit Decreasing (FFD) Algorithm

FFD is a well-known heuristic for 1D bin packing (cutting stock is a form of bin packing). It works like this:

1. Sort all pieces from largest to smallest
2. For each piece, scan existing bars one by one
3. Place the piece into the first bar where it fits
4. If no bar has enough space, open a new bar

FFD gives a good practical solution quickly, and serves as the **baseline** to compare against cuOpt.

#### Simulated cuOpt Result

The real cuOpt API endpoint is not yet configured. Until it is available, `submit_to_cuopt()` returns a simulated result:

- It targets the **theoretical minimum number of bars** — the mathematical lower bound for any cutting stock solver
- This is the best any algorithm could possibly do (e.g., if total demand is 14,400 mm and stock bars are 6,000 mm, the minimum is 3 bars)
- When the real endpoint is ready, only the body of `submit_to_cuopt()` needs to be replaced with an HTTP POST call

#### Execution Timing

Both the baseline and simulated cuOpt steps are wrapped with `time.perf_counter()` to measure runtime in seconds. This sets up the comparison framework — when the real API is called, we will be able to see exactly how long cuOpt takes vs the FFD heuristic.

#### CLI Output — Input Summary and Results Table

When run from the command line, the solver prints:

**Input Summary Block** — before solving:
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

  Unique Piece Sizes  : 3
  Total Pieces        : 15

  Total Demand Length : 27900.0 mm

  Theoretical Minimum Bars : 5 bars

================================================
```

**Results Comparison Table** — after solving:
```
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
  -------------------- -----  ---------- ----------- ----------
  FFD Baseline            6    6300.0        77.5%   0.000123
  cuOpt (simulated)       5     300.0       98.75%   0.000045
====================================================
```

This output is designed to be presentation-friendly and easy to understand.

---

### `src/azure-function/validation.py` — Shared Validation Module

Previously, the validation logic lived inside `function_app.py` as a private function `_validate_job()`. It was extracted into its own file `validation.py` with the following reasons:

- The solver also needs to validate incoming job messages — duplicating the logic in two places would be bad practice
- A shared module makes it easier to keep validation rules consistent across both modules
- It is the first step towards a proper shared package (the long-term plan is `src/shared/`)

**Current workaround:** Since Python packaging is not yet set up, `solver.py` adds the `azure-function` directory to `sys.path` at runtime so it can import `validate_job`. This is noted with a `TODO` comment in the code.

#### What `validate_job()` checks:

| Rule | Error message if broken |
|------|-------------------------|
| `orders` field must exist | `Missing required field: 'orders'` |
| `orders` list must be non-empty | `'orders' must be a non-empty list` |
| Each order must have `length_mm` | `Order N missing 'length_mm'` |
| `length_mm` must be a positive number | `Order N 'length_mm' must be a positive number` |
| Each order must have `quantity` | `Order N missing 'quantity'` |
| `quantity` must be a positive integer | `Order N 'quantity' must be a positive integer` |
| `stock_length_mm` if present must be positive | `'stock_length_mm' must be a positive number` |

---

## Test Suite Updates

### Coverage Problem and Fix

When `validation.py` was created as a new file, the CI coverage measurement started including it. Since no tests directly tested `validation.py`, the total coverage dropped from ~93% to **72%** — below the 80% gate.

The fix was to add a new test class `TestValidateJob` in `tests/test_function_app.py` with 12 tests that call `validate_job()` directly:

| Test | What it verifies |
|------|-----------------|
| `test_valid_payload_returns_no_errors` | A good job returns an empty error list |
| `test_missing_orders_field` | Missing `orders` key is caught |
| `test_empty_orders_list` | Empty `orders` list is caught |
| `test_missing_length_mm` | Missing `length_mm` in an order is caught |
| `test_invalid_length_mm_zero` | Zero `length_mm` is rejected |
| `test_invalid_length_mm_negative` | Negative `length_mm` is rejected |
| `test_missing_quantity` | Missing `quantity` in an order is caught |
| `test_invalid_quantity_float` | Float `quantity` (e.g. 1.5) is rejected |
| `test_invalid_quantity_zero` | Zero `quantity` is rejected |
| `test_invalid_stock_length_negative` | Negative `stock_length_mm` is rejected |
| `test_invalid_stock_length_zero` | Zero `stock_length_mm` is rejected |
| `test_multiple_errors_reported_together` | Multiple errors in one job are all reported |

After this fix:
- `validation.py` coverage: **100%**
- `function_app.py` coverage: **96%**
- **Total coverage: 96.81%** — well above the 80% gate
- Total tests: **32** (was 20)

---

## CI/CD Issues Encountered and Resolved

### Issue 1 — Ruff Lint Violations in `solver.py`

Three violations were flagged by ruff:

| Code | Location | Problem | Fix |
|------|----------|---------|-----|
| `F401` | `solver.py` | `import math` inside `main()` was unused — `math` was already imported inside `expand_orders()` | Removed the duplicate import |
| `F541` | `solver.py` | `print(f"  cuOpt for Metals — Cutting Stock Results")` — f-string with no `{}` placeholder | Removed the `f` prefix |
| `F541` | `solver.py` | `print(f"  Validation    : PASSED")` — same issue | Removed the `f` prefix |

**Lesson:** Always run `ruff check .` locally before pushing. These were caught because ruff is configured to fail on any violation with zero tolerance.

### Issue 2 — Coverage Below 80% Gate

Described above — fixed by adding `TestValidateJob`.

### Issue 3 — 7 Merge Conflicts in `solver.py`

**Root cause:** The `main` branch had an older, simpler version of `solver.py` (a basic placeholder with a `solve()` stub). Our branch had the full FFD + cuOpt version. When the PR was opened, GitHub detected that both branches had modified the same file starting from different base states — this caused 7 conflict regions.

**Resolution:**
```bash
git fetch origin
git merge origin/main          # conflicts appear in solver.py
git checkout --ours src/cuopt-solver/solver.py   # keep our version entirely
git add src/cuopt-solver/solver.py
git commit -m "Merge origin/main: resolve conflicts in solver.py, keep saad/solver-progress version"
git push origin saad/solver-progress
```

`git checkout --ours` is the key command — it tells Git to discard the incoming (`main`) version and keep our branch's version for the entire file, resolving all 7 conflicts at once.

**Lesson:** Before starting a new branch, always do `git fetch origin && git merge origin/main` first so the branch starts from the latest `main`. This prevents conflicts from building up.

---

## Sample Data Files

Three JSON input files were created under `data/input/` for local testing:

| File | Description | Notable |
|------|-------------|---------|
| `example_orders.json` | Simple 2-order job, stock 6000mm | FFD and cuOpt both use 4 bars |
| `simple_job.json` | 3 pieces, total demand 5500mm | Both methods: 1 bar, 91.67% efficiency |
| `hard_job.json` | 3 order types, 15 pieces total, stock 6000mm | FFD: 6 bars (77.5%), cuOpt: 5 bars (98.75%) |

The `hard_job.json` file is the best demo case — it shows a clear improvement from FFD to cuOpt (1 fewer bar, 6000mm less waste).

---

## Final State of the PR

| Check | Status |
|-------|--------|
| Ruff lint (Python 3.11) | ✅ Passing |
| Tests (Python 3.11) | ✅ Passing |
| Merge conflicts | ✅ Resolved |
| Coverage gate (80%) | ✅ 96.81% |

---

## What Is Still Left To Do

| Item | Details |
|------|---------|
| Real cuOpt API call | Replace `submit_to_cuopt()` body with `requests.post(CUOPT_ENDPOINT, ...)` |
| cuOpt solver config | `prepare_cuopt_input()` has `"solver_config": {}` — fill in real parameters once endpoint is confirmed |
| Move `validation.py` to `src/shared/` | Remove the `sys.path` workaround — set up a proper Python package |
| Service Bus wiring | Connect `process_message()` to the actual Container Apps Job Service Bus trigger |

---

## Key Learnings This Week

- **FFD is a decent heuristic** but leaves measurable waste (e.g. 77.5% vs 98.75% on `hard_job.json`) — this is why cuOpt is worth integrating
- **Coverage gates catch refactoring regressions** — moving code to a new file without updating tests will silently drop coverage
- **`git checkout --ours`** is a powerful conflict resolution tool when you know your entire version is correct
- **`ruff check .` before every push** prevents CI failures from trivial lint issues
- **f-strings without `{}` are a code smell** — ruff catches them with `F541`; always use plain strings if there's no interpolation
