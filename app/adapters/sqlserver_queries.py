"""SQL Server query adapters."""

from __future__ import annotations

from typing import Any

from app.integrations.sqlserver import run_pdm_bom_query, run_u8_bom_inventory_query
from app.ports.domains.sqlserver_queries import PdmBomQueryPort, U8BomInventoryQueryPort


class U8BomInventoryQueryAdapter(U8BomInventoryQueryPort):
    def run(self, payload: Any) -> Any:
        return run_u8_bom_inventory_query(payload)


class PdmBomQueryAdapter(PdmBomQueryPort):
    def run(self, payload: Any) -> Any:
        return run_pdm_bom_query(payload)
