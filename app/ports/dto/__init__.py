"""Pure data transfer objects for port boundaries (no Protocols)."""

from app.ports.dto.chat_summary import ChatSummaryResult
from app.ports.dto.files import FileRecordDTO
from app.ports.dto.quotation import QuotationTaskSnapshot, StoredFile
from app.ports.dto.task_manager import TaskManagerTaskSnapshot

__all__ = [
    "ChatSummaryResult",
    "FileRecordDTO",
    "QuotationTaskSnapshot",
    "StoredFile",
    "TaskManagerTaskSnapshot",
]
