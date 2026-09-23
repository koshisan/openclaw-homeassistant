"""Tests for template-rendered holding phrase in _defer_to_background."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from tests._conversation_loader import load_conversation_module

_conv = load_conversation_module(streaming="none")

CONF_HOLDING_PHRASE = "holding_phrase"
DEFAULT_HOLDING_PHRASE = "On it — I'll let you know when it's done."


def _make_entity(holding_phrase: str | None):
    entity = _conv.OpenClawConversationEntity.__new__(
        _conv.OpenClawConversationEntity
    )
    entity._config_entry = MagicMock()
    entity._config_entry.data = {}
    entity._config_entry.options = (
        {CONF_HOLDING_PHRASE: holding_phrase}
        if holding_phrase is not None
        else {}
    )
    entity.hass = MagicMock()
    entity._background_tasks = set()
    # _defer_to_background reads self.hass.async_create_background_task
    entity.hass.async_create_background_task = None

    def _fake_create_task(coro, **_):
        coro.close()
        return MagicMock()

    entity.hass.async_create_task = _fake_create_task
    # _build_plain_result requires _finalize_response; MagicMock the whole thing
    entity._build_plain_result = MagicMock(
        side_effect=lambda user_input, chat_log, text: SimpleNamespace(text=text)
    )
    return entity


def _user_input():
    return SimpleNamespace(
        text="Wie sieht mein Kalender aus?",
        device_id="assist-satellite-kitchen",
        language="de",
        conversation_id="c-1",
    )


def _run_defer(entity, config):
    agent_run = MagicMock()
    agent_run.run_id = "run-42"
    chat_log = MagicMock()
    return entity._defer_to_background(
        _user_input(), chat_log, agent_run, config
    )


class TestHoldingPhraseTemplate:
    def test_literal_phrase_used_as_is(self) -> None:
        entity = _make_entity("Moment bitte.")
        result = _run_defer(entity, {CONF_HOLDING_PHRASE: "Moment bitte."})
        assert result.text == "Moment bitte."

    def test_template_rendered_at_defer_time(self) -> None:
        template = "Ich melde mich bei dir auf {{ device_id }}."
        entity = _make_entity(template)
        result = _run_defer(entity, {CONF_HOLDING_PHRASE: template})
        assert result.text == "Ich melde mich bei dir auf assist-satellite-kitchen."

    def test_empty_template_falls_back_to_default(self) -> None:
        # A template that renders to empty (e.g. all vars None) uses the
        # baseline holding phrase so the user still hears something.
        entity = _make_entity("{{ nonexistent }}")
        result = _run_defer(entity, {CONF_HOLDING_PHRASE: "{{ nonexistent }}"})
        assert result.text == DEFAULT_HOLDING_PHRASE

    def test_missing_phrase_uses_default(self) -> None:
        entity = _make_entity(None)
        result = _run_defer(entity, {})
        assert result.text == DEFAULT_HOLDING_PHRASE
