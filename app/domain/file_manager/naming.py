"""File naming domain logic."""

from __future__ import annotations

import uuid

from app.core.time_utils import utcnow_naive


def generate_unique_filename(original_filename: str) -> str:
    """Return unique name: timestamp + uuid + original base name."""
    unique_id = uuid.uuid4().hex
    timestamp = utcnow_naive().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{unique_id}{original_filename}"
