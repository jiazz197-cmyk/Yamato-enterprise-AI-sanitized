"""SQL Server query use cases."""

from __future__ import annotations

from app.ports.domains.sqlserver_queries import PdmBomQueryPort, U8BomInventoryQueryPort
from app.schemas.sqlserver import PdmBomRequest, QueryResponse, U8BomInventoryRequest


class RunU8BomInventoryQueryUseCase:
    def __init__(self, port: U8BomInventoryQueryPort):
        self._port = port

    def execute(self, payload: U8BomInventoryRequest) -> QueryResponse:
        return self._port.run(payload)


class RunPdmBomQueryUseCase:
    def __init__(self, port: PdmBomQueryPort):
        self._port = port

    def execute(self, payload: PdmBomRequest) -> QueryResponse:
        return self._port.run(payload)
