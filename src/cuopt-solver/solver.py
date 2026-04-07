"""
cuOpt Solver – cuOpt for Metals
Cutting-stock exploration runner.

Pipeline:
  1. Load and validate job from JSON (Service Bus message or CLI file).
  2. Expand orders into individual piece lengths + compute summary stats.
  3. Run First Fit Decreasing (FFD) baseline for immediate comparison.
  4. Prepare cuOpt input payload (structure only – API call is a placeholder).
  5. Submit to cuOpt (placeholder – fill in when cuOpt endpoint is available).
  6. Return a structured result containing both baseline and cuOpt sections.

Entry points:
  • Service Bus consumer (production): Container Apps Job passes message body.
  • CLI (local testing):
      python solver.py --input ../../data/input/example_orders.json
"""

import argparse
import json
import logging
import os
import sys
import time

# ── Shared validation ────────────────────────────────────────────────────────
# Temporarily resolve the sibling azure-function directory so we can reuse the
# shared validate_job helper without duplicating it.
# TODO: move validation.py to src/shared/ and install as a package.
_FUNCTION_DIR = os.path.join(os.path.dirname(__file__), "..", "azure-function")
sys.path.insert(0, os.path.abspath(_FUNCTION_DIR))
from validation import validate_job  # noqa: E402

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── Step 1: Parse ─────────────────────────────────────────────────────────────

def parse_message(raw: str) -> dict:
    """Deserialise a raw JSON string into a job payload dict."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Message is not valid JSON: {exc}") from exc


# ── Step 2: Expand + summarise ────────────────────────────────────────────────

def expand_orders(job: dict) -> dict:
    """
    Expand orders into a flat piece list and compute summary stats.

    Returns:
        {
            "stock_length_mm": float,
            "pieces": [float, ...],          # one entry per individual piece
            "total_pieces": int,
            "total_demand_mm": float,
            "theoretical_min_bars": int,     # lower bound (ceil of demand / stock)
        }
    """
    stock_length = job["stock_length_mm"]
    pieces: list[float] = []
    for order in job["orders"]:
        pieces.extend([float(order["length_mm"])] * order["quantity"])

    total_demand = sum(pieces)
    import math
    theoretical_min = math.ceil(total_demand / stock_length)

    logger.info(
        "Job %s — %d pieces, %.1f mm total demand, stock %s mm, "
        "theoretical minimum bars: %d",
        job.get("job_id", "unknown"),
        len(pieces),
        total_demand,
        stock_length,
        theoretical_min,
    )

    return {
        "stock_length_mm": stock_length,
        "pieces": pieces,
        "total_pieces": len(pieces),
        "total_demand_mm": round(total_demand, 4),
        "theoretical_min_bars": theoretical_min,
    }


# ── Step 3: FFD baseline ──────────────────────────────────────────────────────

def _first_fit_decreasing(pieces: list[float], stock_length: float) -> list[list[float]]:
    """
    First Fit Decreasing (FFD) heuristic for 1D bin packing.

    Sorts pieces largest-first, then places each piece into the first bar
    with enough remaining space. Opens a new bar when none fit.

    Returns a list of bars; each bar is a list of piece lengths placed on it.
    """
    sorted_pieces = sorted(pieces, reverse=True)
    bars: list[list[float]] = []
    remaining: list[float] = []

    for piece in sorted_pieces:
        placed = False
        for i, space in enumerate(remaining):
            if piece <= space:
                bars[i].append(piece)
                remaining[i] = round(remaining[i] - piece, 4)
                placed = True
                break
        if not placed:
            bars.append([piece])
            remaining.append(round(stock_length - piece, 4))

    return bars


def run_baseline(expanded: dict) -> dict:
    """
    Run the FFD baseline and return a structured result.

    Returns:
        {
            "algorithm": "first_fit_decreasing",
            "bars_used": int,
            "waste_mm": float,
            "efficiency_pct": float,
            "patterns": [{"bar": int, "cuts_mm": [...], "used_mm": float, "waste_mm": float}, ...]
        }
    """
    stock_length = expanded["stock_length_mm"]
    pieces = expanded["pieces"]

    bars = _first_fit_decreasing(pieces, stock_length)

    patterns = [
        {
            "bar": i + 1,
            "cuts_mm": bar,
            "used_mm": round(sum(bar), 4),
            "waste_mm": round(stock_length - sum(bar), 4),
        }
        for i, bar in enumerate(bars)
    ]

    total_waste = round(sum(p["waste_mm"] for p in patterns), 4)
    efficiency = round(
        (expanded["total_demand_mm"] / (stock_length * len(bars))) * 100, 2
    )

    logger.info(
        "FFD baseline: %d bars, %.1f mm waste, %.1f%% efficiency",
        len(bars),
        total_waste,
        efficiency,
    )

    return {
        "algorithm": "first_fit_decreasing",
        "bars_used": len(bars),
        "waste_mm": total_waste,
        "efficiency_pct": efficiency,
        "patterns": patterns,
    }


# ── Step 4: Prepare cuOpt input ───────────────────────────────────────────────

def prepare_cuopt_input(job: dict, expanded: dict) -> dict:
    """
    Build the payload that will be sent to the cuOpt API.

    Currently returns a skeleton structure that mirrors what the cuOpt
    linear-programming / cutting-stock endpoint expects.
    TODO: fill in the exact field names once the cuOpt endpoint is confirmed.

    Returns a dict ready to be JSON-serialised and POST-ed to cuOpt.
    """
    # Group pieces back into (length, quantity) pairs for the LP formulation
    from collections import Counter
    piece_counts = Counter(expanded["pieces"])
    demand = [
        {"length_mm": length, "quantity": qty}
        for length, qty in sorted(piece_counts.items(), reverse=True)
    ]

    cuopt_payload = {
        "problem_type": "cutting_stock_1d",
        "stock_length_mm": expanded["stock_length_mm"],
        "demand": demand,
        # TODO: add cuOpt-specific solver parameters (time limit, gap tolerance, etc.)
        "solver_config": {},
    }

    logger.info(
        "cuOpt input prepared: %d unique piece sizes, stock %s mm",
        len(demand),
        expanded["stock_length_mm"],
    )

    return cuopt_payload


# ── Step 5: Submit to cuOpt ───────────────────────────────────────────────────

def submit_to_cuopt(cuopt_payload: dict, expanded: dict) -> dict:
    """
    Simulate a cuOpt optimisation result for comparison and testing.

    No external API is called. The simulation models cuOpt finding the
    optimal (or near-optimal) solution by targeting the theoretical minimum
    number of bars — the best any solver could achieve given the demand and
    stock length.

    When the real cuOpt endpoint becomes available, replace the body of this
    function with an HTTP call:
        import requests
        resp = requests.post(CUOPT_ENDPOINT, json=cuopt_payload, headers=...)
        resp.raise_for_status()
        return resp.json()
    """
    stock_length = expanded["stock_length_mm"]
    total_demand = expanded["total_demand_mm"]
    theoretical_min = expanded["theoretical_min_bars"]

    # cuOpt targets the theoretical minimum bars (optimal solution lower bound).
    # Waste is whatever capacity is left over after fitting all demand.
    simulated_bars = theoretical_min
    simulated_waste = round((simulated_bars * stock_length) - total_demand, 4)
    simulated_efficiency = round((total_demand / (simulated_bars * stock_length)) * 100, 2)

    logger.info(
        "cuOpt simulation: %d bars, %.1f mm waste, %.1f%% efficiency",
        simulated_bars,
        simulated_waste,
        simulated_efficiency,
    )

    return {
        "status": "simulated",
        "note": "Simulated result — replace with real cuOpt API call when endpoint is available.",
        "bars_used": simulated_bars,
        "waste_mm": simulated_waste,
        "efficiency_pct": simulated_efficiency,
    }


# ── Step 6: Full pipeline ─────────────────────────────────────────────────────

def process_message(raw: str) -> dict:
    """
    Full exploration pipeline:
      parse → validate → expand → baseline → cuOpt input → cuOpt submit

    Returns a structured result with both baseline and cuOpt sections.
    Raises ValueError if the message is unparseable or fails validation.
    """
    job = parse_message(raw)

    logger.info("Received job %s — validating…", job.get("job_id", "unknown"))
    errors = validate_job(job)
    if errors:
        raise ValueError(f"Job validation failed: {errors}")

    expanded = expand_orders(job)

    _t0 = time.perf_counter()
    baseline = run_baseline(expanded)
    baseline_runtime = round(time.perf_counter() - _t0, 6)

    cuopt_input = prepare_cuopt_input(job, expanded)
    _t1 = time.perf_counter()
    cuopt_result = submit_to_cuopt(cuopt_input, expanded)
    cuopt_runtime = round(time.perf_counter() - _t1, 6)

    result = {
        "job_id": job.get("job_id"),
        "stock_length_mm": expanded["stock_length_mm"],
        "total_pieces": expanded["total_pieces"],
        "total_demand_mm": expanded["total_demand_mm"],
        "theoretical_min_bars": expanded["theoretical_min_bars"],
        "baseline_result": baseline,
        "baseline_runtime_sec": baseline_runtime,
        "cuopt_result": cuopt_result,
        "cuopt_runtime_sec": cuopt_runtime,
        "metadata": job.get("metadata", {}),
    }

    logger.info(
        "Job %s complete — baseline: %d bars / %.1f%% efficiency | cuOpt: %d bars / %.1f%% efficiency",
        job.get("job_id", "unknown"),
        baseline["bars_used"],
        baseline["efficiency_pct"],
        cuopt_result["bars_used"],
        cuopt_result["efficiency_pct"],
    )

    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="cuOpt for Metals — cutting-stock exploration runner."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON file containing the job message.",
    )
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        raw = fh.read()

    # Parse and validate early so we can print the input summary before solving
    job = parse_message(raw)
    errors = validate_job(job)
    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    expanded = expand_orders(job)

    # ── Input summary ────────────────────────────────────────────────────────
    _W = 48
    print()
    print("=" * _W)
    print(f"{'INPUT SUMMARY':^{_W}}")
    print("=" * _W)
    print()
    print(f"  Job ID          : {job.get('job_id', 'N/A')}")
    print()
    print(f"  Stock Length    : {expanded['stock_length_mm']} mm")
    print()
    print("  Orders Breakdown:")
    for order in job["orders"]:
        print(f"    - {int(order['length_mm'])} mm × {order['quantity']} pieces")
    print()
    print(f"  Unique Piece Sizes  : {len(job['orders'])}")
    print(f"  Total Pieces        : {expanded['total_pieces']}")
    print()
    print(f"  Total Demand Length : {expanded['total_demand_mm']} mm")
    print()
    print(f"  Theoretical Minimum Bars : {expanded['theoretical_min_bars']} bars")
    print()
    print("=" * _W)
    print()

    result = process_message(raw)

    b = result["baseline_result"]
    c = result["cuopt_result"]
    print()
    print("=" * 52)
    print("  cuOpt for Metals — Cutting Stock Results")
    print("=" * 52)
    print(f"  Job ID        : {result['job_id']}")
    print("  Validation    : PASSED")
    print(f"  Total pieces  : {result['total_pieces']}")
    print(f"  Total demand  : {result['total_demand_mm']} mm")
    print(f"  Stock length  : {result['stock_length_mm']} mm")
    print(f"  Minimum bars  : {result['theoretical_min_bars']} (theoretical lower bound)")
    print("-" * 52)
    print(f"  {'Method':<20} {'Bars':>5} {'Waste mm':>10} {'Efficiency':>11} {'Time (s)':>10}")
    print(f"  {'-'*20} {'-'*5} {'-'*10} {'-'*11} {'-'*10}")
    print(f"  {'FFD Baseline':<20} {b['bars_used']:>5} {b['waste_mm']:>10} {str(b['efficiency_pct'])+'%':>11} {result['baseline_runtime_sec']:>10.6f}")
    print(f"  {'cuOpt (simulated)':<20} {c['bars_used']:>5} {c['waste_mm']:>10} {str(c['efficiency_pct'])+'%':>11} {result['cuopt_runtime_sec']:>10.6f}")
    print("=" * 52)
    print()


if __name__ == "__main__":
    main()
