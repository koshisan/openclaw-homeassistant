"""Voice streaming: preambles, per-chunk emoji stripping, TTS start, warm-up."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests._conversation_loader import load_conversation_module
from tests.test_gateway_client import AgentRun, OpenClawGatewayClient

_conv = load_conversation_module(streaming="modern")


def _drain(run: AgentRun) -> list[str]:
    chunks = []
    while not run._stream_queue.empty():
        chunk = run._stream_queue.get_nowait()
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def _preamble(run: AgentRun, text: str, phase: str, item: str = "p1") -> None:
    OpenClawGatewayClient._buffer_preamble(
        run,
        {"kind": "preamble", "phase": phase, "progressText": text, "itemId": item},
    )


class TestPreamble:
    def test_preamble_streams_before_answer(self) -> None:
        run = AgentRun("run-1", stream=True)
        _preamble(run, "Guten Morgen, ich schau", "update")
        _preamble(run, "Guten Morgen, ich schau kurz nach.", "end")
        run.add_output("Die Pflanzen", "msg-2")
        run.add_delta(" sind gegossen.", "msg-2")
        run.set_complete("ok")

        assert _drain(run) == [
            "Guten Morgen, ich schau",
            " kurz nach.",
            "\n\n",
            "Die Pflanzen",
            " sind gegossen.",
        ]
        # The answer text stays separate from the spoken preamble.
        assert run.get_response() == "Die Pflanzen sind gegossen."

    def test_preamble_already_streamed_as_answer_is_not_repeated(self) -> None:
        run = AgentRun("run-1", stream=True)
        run.add_output("Moment, ich  schaue nach.", "msg-1")
        _preamble(run, "Moment, ich schaue nach.", "end")
        run.add_output("Fertig.", "msg-2")

        assert _drain(run) == [
            "Moment, ich  schaue nach.",
            "\n\n",
            "Fertig.",
        ]

    def test_rewritten_preamble_is_ignored(self) -> None:
        run = AgentRun("run-1", stream=True)
        _preamble(run, "Ich prüfe", "update")
        _preamble(run, "Ich schaue nach.", "end")

        assert _drain(run) == ["Ich prüfe", "\n\n"]

    def test_summary_still_follows_a_preamble(self) -> None:
        run = AgentRun("run-1", stream=True)
        _preamble(run, "Einen Moment.", "end")
        run.set_complete("ok", "Das Licht ist aus.")

        assert "".join(_drain(run)) == "Einen Moment.\n\nDas Licht ist aus."

    def test_other_item_events_are_ignored(self) -> None:
        run = AgentRun("run-1", stream=True)
        OpenClawGatewayClient._buffer_preamble(
            run, {"kind": "tool", "phase": "end", "progressText": "exec", "itemId": "t"}
        )
        assert _drain(run) == []

    def test_item_event_reaches_preamble_handler(self) -> None:
        client = OpenClawGatewayClient.__new__(OpenClawGatewayClient)
        run = AgentRun("run-1", stream=True)
        client._agent_runs = {"run-1": run}
        client._handle_agent_event(
            {
                "payload": {
                    "runId": "run-1",
                    "stream": "item",
                    "data": {
                        "kind": "preamble",
                        "title": "Preamble",
                        "phase": "end",
                        "progressText": "Ich schaue kurz nach.",
                        "itemId": "p1",
                    },
                }
            }
        )
        assert _drain(run) == ["Ich schaue kurz nach.", "\n\n"]


class _FakeAgentRun:
    run_id = "run-voice"

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = list(chunks)


class _FakeGatewayClient:
    def __init__(self, agent_run: _FakeAgentRun) -> None:
        self._agent_run = agent_run

    async def begin_agent_run(self, _message: str):
        return self._agent_run

    async def stream_run(self, agent_run):
        for chunk in agent_run._chunks:
            yield chunk


def _entity(chunks: list[str]):
    entity = _conv.OpenClawConversationEntity.__new__(_conv.OpenClawConversationEntity)
    entity._config_entry = MagicMock()
    entity._config_entry.data = {}
    entity._config_entry.options = {}
    entity._gateway_client = _FakeGatewayClient(_FakeAgentRun(chunks))
    entity.hass = MagicMock()
    entity._background_tasks = set()
    entity.entity_id = "conversation.openclaw"
    return entity


def _user_input(**extra):
    return SimpleNamespace(
        text="Guten Morgen",
        device_id=None,
        language="de",
        conversation_id="conv-1",
        **extra,
    )


async def _stream(chunks: list[str], config: dict) -> list[str]:
    entity = _entity(chunks)
    chat_log = _conv.conversation.ChatLog()
    await entity._handle_chat_log_streaming(
        _user_input(), chat_log, "Guten Morgen", {"background_enabled": False, **config}
    )
    return [d["content"] for d in chat_log.deltas if "content" in d]


class TestEmojiStripping:
    async def test_streamed_chunks_are_stripped(self) -> None:
        chunks = await _stream(
            ["Soll ich den Ofen ", "anwerfen? ", "🐍", " Bis gleich 👋!"], {}
        )
        assert chunks == ["Soll ich den Ofen ", "anwerfen? ", " Bis gleich !"]

    async def test_stripping_can_be_disabled(self) -> None:
        chunks = await _stream(["Hallo 🐍"], {"strip_emojis": False})
        assert chunks == ["Hallo 🐍"]

    def test_cjk_text_is_kept(self) -> None:
        assert _conv.strip_emojis("小田原城 ✨ おはよう") == "小田原城  おはよう"

    def test_emoji_sequences_are_removed(self) -> None:
        assert _conv.strip_emojis("Familie 👨‍👩‍👧 und 👍🏽 ❤️") == "Familie  und"


class TestTtsStart:
    async def test_short_paragraph_is_padded_past_ha_threshold(self) -> None:
        chunks = await _stream(["Moment.", "\n\n", "Die Antwort."], {})
        assert chunks[0] == "Moment."
        assert chunks[1].startswith("\n\n") and not chunks[1].strip()
        assert len(chunks[0]) + len(chunks[1]) > _conv.HA_STREAM_RESPONSE_CHARS
        assert chunks[2] == "Die Antwort."

    async def test_no_padding_once_streaming_started(self) -> None:
        long = "x" * (_conv.HA_STREAM_RESPONSE_CHARS + 5)
        chunks = await _stream([long, "\n\n", "Mehr."], {})
        assert chunks == [long, "\n\n", "Mehr."]


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def read(self) -> bytes:
        return b"\0\0"


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict):
        self.calls.append((url, json))
        return _FakeResponse()


class TestTtsWarmUp:
    def _config(self, **extra) -> dict:
        return {"tts_warmup_url": "http://tts.local/v1/audio/speech", **extra}

    def test_voice_request_schedules_warm_up(self, monkeypatch) -> None:
        session = _FakeSession()
        monkeypatch.setattr(_conv, "async_get_clientsession", lambda _hass: session)
        entity = _entity([])
        scheduled = []
        entity.hass.async_create_background_task = (
            lambda coro, name: scheduled.append(coro)
        )

        entity._maybe_warm_up_tts(
            _user_input(satellite_id="assist_satellite.klo"),
            self._config(tts_warmup_voice="nadeko"),
        )
        assert len(scheduled) == 1
        asyncio.run(scheduled[0])

        url, payload = session.calls[0]
        assert url == "http://tts.local/v1/audio/speech"
        assert payload["voice"] == "nadeko"
        assert payload["input"] == _conv.TTS_WARMUP_TEXT
        assert isinstance(payload["seed"], int)

    def test_text_request_does_not_warm_up(self) -> None:
        entity = _entity([])
        entity.hass.async_create_background_task = MagicMock()
        entity._maybe_warm_up_tts(_user_input(), self._config())
        entity.hass.async_create_background_task.assert_not_called()

    def test_no_url_does_not_warm_up(self) -> None:
        entity = _entity([])
        entity.hass.async_create_background_task = MagicMock()
        entity._maybe_warm_up_tts(_user_input(satellite_id="assist_satellite.klo"), {})
        entity.hass.async_create_background_task.assert_not_called()

    async def test_failed_warm_up_is_swallowed(self, monkeypatch) -> None:
        def _boom(_hass):
            raise OSError("unreachable")

        monkeypatch.setattr(_conv, "async_get_clientsession", _boom)
        entity = _entity([])
        await entity._async_warm_up_tts("http://tts.local", {"input": "Hm."})
