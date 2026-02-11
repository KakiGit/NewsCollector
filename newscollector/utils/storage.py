"""JSON storage utilities."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from newscollector.models import CollectionResult

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"


def save_result(
    result: CollectionResult,
    output_dir: Path | str | None = None,
) -> Path:
    """Save a CollectionResult to a JSON file.

    Files are stored as: <output_dir>/<platform>/<YYYY-MM-DD>.json
    If a file already exists for the same platform/date, items are appended.

    Returns:
        Path to the written JSON file.
    """
    base_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    platform_dir = base_dir / result.platform
    platform_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    filepath = platform_dir / f"{date_str}.json"

    # Load existing items if file exists
    existing_items: list[dict] = []
    if filepath.exists():
        try:
            existing_items = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read existing file %s, overwriting", filepath)

    # Append new items
    new_items = [item.model_dump(mode="json") for item in result.items]
    all_items = existing_items + new_items

    filepath.write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    logger.info("Saved %d items to %s (total: %d)", len(new_items), filepath, len(all_items))
    return filepath
