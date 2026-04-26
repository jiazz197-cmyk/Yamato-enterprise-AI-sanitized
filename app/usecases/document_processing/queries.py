"""Query document processing task status and list."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.orm.platform.user import User, UserRole
from app.ports.contracts.tasking import TaskStatePort
from app.ports.dto.task_manager import TaskManagerTaskSnapshot


@dataclass
class DocumentTaskStatusDTO:
    task_id: str
    status: str
    progress: int
    message: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    result: Optional[dict]
    error: Optional[str]


@dataclass
class GetDocumentTaskStatusQuery:
    task_id: str
    current_user: User


@dataclass
class ListDocumentTasksQuery:
    current_user: User
    status_filter: Optional[str]
    limit: int


@dataclass
class ListDocumentTasksResult:
    tasks: List[DocumentTaskStatusDTO]
    total: int


def _assert_owner(snapshot: TaskManagerTaskSnapshot, current_user: User, *, detail: str) -> None:
    owner_id = str(snapshot.metadata.get("owner_id", "")).strip()
    if current_user.role != UserRole.superuser and owner_id != str(current_user.id):
        raise PermissionDeniedError(detail)


def _to_dto(t: TaskManagerTaskSnapshot) -> DocumentTaskStatusDTO:
    return DocumentTaskStatusDTO(
        task_id=t.task_id,
        status=t.status,
        progress=t.progress,
        message=t.message,
        created_at=t.created_at,
        started_at=t.started_at,
        completed_at=t.completed_at,
        result=t.result,
        error=t.error,
    )


class GetDocumentTaskStatusUseCase:
    def __init__(self, task_state: TaskStatePort):
        self._task_state = task_state

    async def execute(self, query: GetDocumentTaskStatusQuery) -> DocumentTaskStatusDTO:
        snap = await self._task_state.get_task_snapshot(query.task_id)
        if not snap:
            raise NotFoundError(f"任务 {query.task_id} 不存在")
        _assert_owner(snap, query.current_user, detail="无权查看该任务")
        return _to_dto(snap)


class ListDocumentTasksUseCase:
    def __init__(self, task_state: TaskStatePort):
        self._task_state = task_state

    async def execute(self, query: ListDocumentTasksQuery) -> ListDocumentTasksResult:
        tasks = await self._task_state.list_task_snapshots(task_type="doc_process", limit=query.limit)
        if query.status_filter:
            tasks = [t for t in tasks if t.status == query.status_filter]
        if query.current_user.role != UserRole.superuser:
            tasks = [
                t
                for t in tasks
                if str(t.metadata.get("owner_id", "")).strip() == str(query.current_user.id)
            ]
        return ListDocumentTasksResult(tasks=[_to_dto(t) for t in tasks], total=len(tasks))
