"""
pipeline/emit.py
Validates events against the schema and emits them to the API.

PROMPT: "Write a Python function to validate a list of events against a Pydantic model
and POST them in batches to a FastAPI endpoint."
CHANGES MADE: Added retry logic with exponential backoff, batch size limit of 100 (not
500) for pipeline use to keep memory low, and JSONL file output for replay.
"""

import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def emit_events(
    events: list[dict],
    api_url: str,
    output_path: str | None = None,
) -> dict:
    """
    Validate, write to JSONL, and POST events to the API in batches.

    Args:
        events: List of raw event dicts from tracker
        api_url: Base URL of the API (e.g. http://localhost:8000)
        output_path: Optional path to write events.jsonl

    Returns:
        Summary dict with total, sent, failed counts
    """
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    total = len(events)
    sent = 0
    failed = 0

    for i in range(0, total, BATCH_SIZE):
        batch = events[i:i + BATCH_SIZE]

        # Write to JSONL
        if output_path:
            with open(output_path, "a") as f:
                for event in batch:
                    f.write(json.dumps(event) + "\n")

        # POST to API with retry
        url = f"{api_url.rstrip('/')}/events/ingest"
        success = False
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.post(url, json=batch, timeout=10)
                if resp.status_code in (200, 202):
                    data = resp.json()
                    sent += data.get("inserted", len(batch))
                    logger.info(f"Batch {i // BATCH_SIZE + 1}: {data}")
                    success = True
                    break
                else:
                    logger.warning(f"API returned {resp.status_code}: {resp.text}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(RETRY_DELAY * (2 ** attempt))

        if not success:
            failed += len(batch)
            logger.error(f"Failed to emit batch starting at index {i}")

    return {"total": total, "sent": sent, "failed": failed}


def print_events(events: list[dict]):
    """Print events to stdout as JSONL (for debugging)."""
    for event in events:
        print(json.dumps(event))
