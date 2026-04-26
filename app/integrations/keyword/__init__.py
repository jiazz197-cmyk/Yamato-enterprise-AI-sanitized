"""PDM keyword mapping and normalization (domain logic)."""

from app.integrations.keyword.mapping import (
    apply_keyword_mapping,
    detect_product_type,
    expand_keyword_mapping,
)
from app.integrations.keyword.normalizer import normalize_pdm_keywords

__all__ = [
    "apply_keyword_mapping",
    "detect_product_type",
    "expand_keyword_mapping",
    "normalize_pdm_keywords",
]
