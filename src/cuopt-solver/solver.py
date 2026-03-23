"""
cuOpt Solver – cuOpt for Metals
Consumes a cutting-stock job message (JSON), validates it, and runs the solver.

Entry points:
  • Service Bus consumer (production): called by the Container Apps Job trigger
    with the message body as a JSON string.
  • CLI (local testing):
      python solver.py --input ../../data/input/example_orders.json

TODO: move validation.py to a shared package (e.g. src/shared/) so both this
module and the Azure Function can import it without sys.path manipulation.
"""

import argparse
import json
import logging
import os
import sys

# ── Shared validation ────────────────────────────────────────────────────────
# Temporarily resolve the sibling azure-function directory so we can reuse the
# shared validate_job helper without duplicating it.
_FUNCTION_DIR = os.path.join(os.path.dirname(__file__), "..", "azure-function")
sys.path.insert(0, os.path.abspath(_FUNCTION_DIR))
from validation import validate_job  # noqa: E402

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ── Core logic ───────────────────────────────────────────────────────────────

def parse_message(raw: str) -> dict:
    """Parse a raw JSON string into a job payload dict."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Message is not valid JSON: {exc}") from exc


def solve(job: dict) -> dict:
    """
    Run the cutting-stock optimisation.

    TODO: replace placeholder logic with real cuOpt solver calls.
    Expected inputs (already validated before this is called):
      - job["stock_length_mm"] : int/float  – raw bar length
      - job["orders"]          : list       – [{"length_mm": ..., "quantity": ...}, ...]

    Returns a result dict that will be written back / logged.
    """
    stock_length = job["stock_length_mm"]
    orders = job["orders"]
    total_pieces = sum(o["quantity"] for o in orders)

    logger.info(
        "Solving job %s: %d order lines, %d total pieces, stock length %s mm",
        job.get("job_id", "unknown"),
        len(orders),
        total_pieces,
        stock_length,
    )

    # ── Placeholder result ───────────────────────────────────────────────────
    # TODO: call cuOpt API / solver here and return real cutting patterns.
    result = {
        "job_id": job.get("job_id"),
        "status": "completed",
        "stock_length_mm": stock_length,
        "patterns": [],          # TODO: populate with optimised cut patterns
        "waste_mm": None,        # TODO: compute total waste
        "bars_used": None,       # TODO: compute number of raw bars consumed
        "metadata": job.get("metadata", {}),
    }
    return result


def process_message(raw: str) -> dict:
    """
    Full pipeline: parse → validate → solve.
    Returns the solver result dict.
    Raises ValueError if the message is unparseable or invalid.
    """
    job = parse_message(raw)

    logger.info("Received job %s – validating…", job.get("job_id", "unknown"))

    errors = validate_job(job)
    if errors:
        raise ValueError(f"Job validation failed: {errors}")

    logger.info("Validation passed for job %s – running solver…", job["job_id"])
    result = solve(job)

    logger.info("Job %s completed – result: %s", job["job_id"], json.dumps(result))
    return result


# ── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the cuOpt cutting-stock solver locally.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSON file containing the job message.",
    )
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        raw = fh.read()

    result = process_message(raw)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
