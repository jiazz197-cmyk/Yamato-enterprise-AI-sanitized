"""Shared helpers for quotation use-cases."""

from __future__ import annotations

from typing import Any, Dict


def response_to_dict(response: Any) -> Dict[str, Any]:
    """Serialize a pydantic response-like object to a dict (v2 model_dump / v1 dict)."""
    dumper = getattr(response, "model_dump", None)
    if callable(dumper):
        return dumper()
    return response.dict()  # type: ignore[attr-defined]
