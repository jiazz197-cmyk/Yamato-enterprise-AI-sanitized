"""Re-export for backward compatibility. Moved to app.domain.quotation."""

from app.domain.quotation.keyword_mapping import (
    apply_keyword_mapping,
    detect_product_type,
    expand_keyword_mapping,
)
from app.domain.quotation.keyword_normalizer import normalize_pdm_keywords

__all__ = [
    "apply_keyword_mapping",
    "detect_product_type",
    "expand_keyword_mapping",
    "normalize_pdm_keywords",
]
