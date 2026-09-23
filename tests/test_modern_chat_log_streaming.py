"""Tests for the modern HA 2024.10+ chat-log delta streaming path.

Verifies:
- `_supports_modern_chat_stream()` reports True when the loader stubs
  `ChatLog.async_add_delta_content_stream`.
- `_handle_chat_log_streaming` fans OpenClaw chunks into the chat-log
  delta stream as `AssistantContentDeltaDict` entries.
- The first delta declares `role=assistant`, subsequent deltas emit
  `content` fragments in arrival order.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests._conversation_loader import load_conversation_module

_conv = load_conversation_module(streaming="modern")


class _FakeAgentRun:
    """Minimal AgentRun stub that hands out preset chunks."""

    def __init__(self, chunks: list[str], first_chunk_timeout: bool = False) -> None:
        self.run_id = "run-modern"
        self._chunks = list(chunks)
        self._first_chunk_timeout = first_chunk_timeout

    async def get_chunk(self, _timeout: float) -> str | None:
        if self._first_chunk_timeout:
            import asyncio

            raise asyncio.TimeoutError
        if not self._chunks:
            return None
        return self._chunks.pop(0)


class _FakeGatewayClient:
    def __init__(self, agent_run: _FakeAgentRun) -> None:
        self._agent_run = agent_run

    async def begin_agent_run(self, _message: str):
        return self._agent_run

    async def stream_run(self, _agent_run):  # noqa: D401
        # After the grace-race peeks the first chunk, the remaining
        # chunks are drained here in arrival order.
        for chunk in list(_agent_run._chunks):
            _agent_run._chunks.pop(0)
            yield chunk


def _make_entity(gateway_client) -> object:
    entity = _conv.OpenClawConversationEntity.__new__(
        _conv.OpenClawConversationEntity
    )
    entity._config_entry = MagicMock()
    entity._config_entry.data = {}
    entity._config_entry.options = {}
    entity._gateway_client = gateway_client
    entity.hass = MagicMock()
    entity._background_tasks = set()
    entity.entity_id = "conversation.openclaw"
    return entity


def _user_input():
    return SimpleNamespace(
        text="Hallo",
        device_id=None,
        language="de",
        conversation_id="conv-1",
    )


def _make_chat_log():
    chat_log_cls = _conv.conversation.ChatLog
    return chat_log_cls()


class TestModernStreaming:
    def test_supports_modern_chat_stream_true_with_stub(self) -> None:
        assert _conv.OpenClawConversationEntity._supports_modern_chat_stream() is True

    async def test_streams_chunks_as_deltas(self) -> None:
        agent_run = _FakeAgentRun(["Guten ", "Morgen ", "Onii-chan."])
        client = _FakeGatewayClient(agent_run)
        entity = _make_entity(client)
        chat_log = _make_chat_log()

        # Disable background so grace peek is skipped
        config = {"background_enabled": False}
        result = await entity._handle_chat_log_streaming(
            _user_input(), chat_log, "Hallo", config
        )

        # First delta declares the assistant role, remaining deltas hold content
        assert chat_log.deltas[0] == {"role": "assistant"}
        content_chunks = [d.get("content") for d in chat_log.deltas[1:]]
        assert content_chunks == ["Guten ", "Morgen ", "Onii-chan."]

        # Result comes from conversation.async_get_result_from_chat_log
        assert result.chat_log is chat_log

    async def test_first_chunk_peeked_and_forwarded(self) -> None:
        agent_run = _FakeAgentRun(["First. ", "Second."])
        client = _FakeGatewayClient(agent_run)
        entity = _make_entity(client)
        chat_log = _make_chat_log()

        # Enable background — get_chunk should peek "First. "
        config = {
            "background_enabled": True,
            "background_grace": 5,
        }
        await entity._handle_chat_log_streaming(
            _user_input(), chat_log, "Hallo", config
        )

        content_chunks = [
            d.get("content") for d in chat_log.deltas if "content" in d
        ]
        # First chunk peeked before defer race, then rest streamed after
        assert content_chunks == ["First. ", "Second."]
