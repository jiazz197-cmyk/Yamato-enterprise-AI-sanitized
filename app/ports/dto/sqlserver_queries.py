"""SQLServer query DTOs (pure dataclass, no Pydantic coupling)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PdmBomCommand:
    """Command for querying PDM BOM data."""

    keywords: Any = None


@dataclass
class U8BomInventoryCommand:
    """Command for querying U8 BOM inventory."""

    parent_inv_codes: str | List[str] = ""
    max_depth: int = 3


@dataclass
class QueryResultDTO:
    """Generic query result DTO."""

    success: bool = True
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
