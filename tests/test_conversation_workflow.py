"""Tests for RunConversationUseCase with fake ports (no DB / no LLM)."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, Optional

from app.ports.dto.conversation import (
    ConversationListItem,
    ConversationMessage,
    ConversationSnapshot,
    RunConversationCommand,
    WorkflowContext,
)
from app.usecases.conversation.run import RunConversationUseCase


class FakeRepo:
    def __init__(self):
        self.long_memory: List[str] = ["旧摘要"]
        self.recent_dialogs: List[str] = []
        self.conversation_id = "conv-1"
        self.messages: List[ConversationMessage] = []
        self.overridden = False
        self.dialog_lines: List[tuple[str, str]] = []
        self._seq = 0

    async def get_or_create_conversation(self, owner_id, conversation_id, query):
        return ConversationSnapshot(
            conversation_id=self.conversation_id,
            owner_id=owner_id,
            name="n",
            long_memory=list(self.long_memory),
            recent_dialogs=list(self.recent_dialogs),
        )

    async def load_snapshot(self, conversation_id):
        return ConversationSnapshot(
            conversation_id=conversation_id,
            owner_id="u",
            name="n",
            long_memory=list(self.long_memory),
            recent_dialogs=list(self.recent_dialogs),
        )

    async def override_memory(self, conversation_id, background):
        self.overridden = True
        self.long_memory = [background]
        self.recent_dialogs = []
        return ConversationSnapshot(
            conversation_id=conversation_id,
            owner_id="u",
            name="n",
            long_memory=list(self.long_memory),
            recent_dialogs=[],
        )

    async def append_message(self, conversation_id, role, content):
        self._seq += 1
        msg = ConversationMessage(
            id=f"m{self._seq}",
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        self.messages.append(msg)
        return msg

    async def append_dialog_line(self, conversation_id, user_query, assistant_answer):
        self.dialog_lines.append((user_query, assistant_answer))

    async def list_conversations(self, owner_id, page, limit):
        return []

    async def list_messages(self, conversation_id, page, limit):
        return []

    async def rename_conversation(self, conversation_id, name, auto_generate):
        return ConversationListItem(conversation_id=conversation_id, name=name)


class FakeUserProfile:
    def __init__(self, summary: Optional[str] = "用户偏好A"):
        self._summary = summary

    def get_latest_summary(self, user_id):
        return self._summary


class FakeWorkflow:
    """Yields a fixed answer token stream; records the context it received."""

    def __init__(self, tokens: List[str]):
        self._tokens = tokens
        self.received: Optional[WorkflowContext] = None

    async def stream_answer(self, ctx: WorkflowContext) -> AsyncIterator[str]:
        self.received = ctx
        for t in self._tokens:
            yield t


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def _collect(usecase, cmd):
    events = []
    async for ev in usecase.execute(cmd):
        events.append(ev)
    return events


def test_run_streams_tokens_then_done_and_persists():
    repo = FakeRepo()
    workflow = FakeWorkflow(["Hello", " ", "world"])
    uc = RunConversationUseCase(
        repo=repo, user_profile=FakeUserProfile(), workflow=workflow, now_provider=lambda: "2026-06-30"
    )
    cmd = RunConversationCommand(
        user_id="u1", query="你好", search_mode="本地检索", conversation_id=None
    )
    events = _run(_collect(uc, cmd))

    types = [e.type for e in events]
    assert types == ["token", "token", "token", "done"]
    assert "".join(e.token for e in events if e.type == "token") == "Hello world"

    done = events[-1].result
    assert done.conversation_id == "conv-1"
    assert done.answer == "Hello world"

    # User message persisted before stream, assistant after.
    roles = [m.role for m in repo.messages]
    assert roles == ["user", "assistant"]
    assert repo.messages[0].content == "你好"
    assert repo.messages[1].content == "Hello world"
    # Dialog line appended.
    assert repo.dialog_lines == [("你好", "Hello world")]
    # Profile + memories threaded into the workflow context.
    assert workflow.received is not None
    assert "用户偏好A" in workflow.received.user_profile
    assert "当前用户问题：你好" in workflow.received.memories
    assert workflow.received.current_time == "2026-06-30"
    assert not repo.overridden


def test_run_background_override_clears_memory():
    repo = FakeRepo()
    repo.long_memory = ["旧摘要"]
    repo.recent_dialogs = ["用户：旧\n助手：旧答"]
    workflow = FakeWorkflow(["答案"])
    uc = RunConversationUseCase(
        repo=repo, user_profile=FakeUserProfile(None), workflow=workflow, now_provider=lambda: "2026-06-30"
    )
    cmd = RunConversationCommand(
        user_id="u1", query="q", search_mode="本地检索", background="  新背景  "
    )
    events = _run(_collect(uc, cmd))

    assert repo.overridden is True
    # After override, long_memory is the cleaned background; recent cleared.
    assert workflow.received.memories.count("新背景") == 1
    assert "旧摘要" not in workflow.received.memories
    assert events[-1].type == "done"


def test_run_empty_background_does_not_override():
    repo = FakeRepo()
    workflow = FakeWorkflow(["x"])
    uc = RunConversationUseCase(
        repo=repo, user_profile=FakeUserProfile(), workflow=workflow, now_provider=lambda: "2026-06-30"
    )
    cmd = RunConversationCommand(
        user_id="u1", query="q", search_mode="联网搜索", background="   "
    )
    _run(_collect(uc, cmd))
    assert repo.overridden is False
