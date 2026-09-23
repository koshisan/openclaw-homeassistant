"""Tests for the CONF_SYSTEM_PROMPT prefix injection."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._conversation_loader import load_conversation_module

_conv = load_conversation_module(streaming="none")

CONF_SYSTEM_PROMPT = "system_prompt"


def _make_entity(prompt: str | None):
    """Build an OpenClawConversationEntity with a mocked config entry."""
    entity = _conv.OpenClawConversationEntity.__new__(
        _conv.OpenClawConversationEntity
    )
    entity._config_entry = MagicMock()
    entity._config_entry.data = {}
    entity._config_entry.options = (
        {CONF_SYSTEM_PROMPT: prompt} if prompt is not None else {}
    )
    entity.hass = MagicMock()
    return entity


def _user_input(text: str, **kwargs):
    return SimpleNamespace(
        text=text,
        device_id=kwargs.get("device_id"),
        language=kwargs.get("language", "en"),
        conversation_id=kwargs.get("conversation_id", "conv-1"),
    )


class TestPrefixUserMessage:
    def test_empty_prompt_leaves_message_unchanged(self) -> None:
        entity = _make_entity(prompt="")
        config = {}
        result = entity._prefix_user_message(_user_input("Hallo"), config)
        assert result == "Hallo"

    def test_missing_prompt_leaves_message_unchanged(self) -> None:
        entity = _make_entity(prompt=None)
        config = {}
        result = entity._prefix_user_message(_user_input("Hallo"), config)
        assert result == "Hallo"

    def test_literal_prompt_prepended(self) -> None:
        entity = _make_entity(prompt="You are Nadeko.")
        config = {CONF_SYSTEM_PROMPT: "You are Nadeko."}
        result = entity._prefix_user_message(_user_input("Hallo"), config)
        assert result == "You are Nadeko.\n\nHallo"

    def test_template_substitutes_variables(self) -> None:
        entity = _make_entity(
            prompt="Voice request from device {{ device_id }}."
        )
        config = {
            CONF_SYSTEM_PROMPT: "Voice request from device {{ device_id }}."
        }
        result = entity._prefix_user_message(
            _user_input("Bist du da?", device_id="kitchen-satellite"),
            config,
        )
        assert result == (
            "Voice request from device kitchen-satellite.\n\nBist du da?"
        )

    def test_template_with_missing_variable_renders_empty(self) -> None:
        entity = _make_entity(prompt="Speaker={{ device_id }}")
        config = {CONF_SYSTEM_PROMPT: "Speaker={{ device_id }}"}
        result = entity._prefix_user_message(
            _user_input("Hi", device_id=None), config
        )
        assert result.startswith("Speaker=")
        assert "Hi" in result

    def test_whitespace_only_prompt_is_ignored(self) -> None:
        entity = _make_entity(prompt="   \n\n  ")
        config = {CONF_SYSTEM_PROMPT: "   \n\n  "}
        result = entity._prefix_user_message(_user_input("Hallo"), config)
        assert result == "Hallo"

    def test_input_speaker_bound_even_when_none(self) -> None:
        # _resolve_input_satellite returns None without a device_id (the
        # entity registry stub in the loader has no entries) — the point
        # is that the template renders without error and doesn't leave
        # the {{ input_speaker }} marker untouched.
        entity = _make_entity(prompt="Speaker: {{ input_speaker }}")
        config = {CONF_SYSTEM_PROMPT: "Speaker: {{ input_speaker }}"}
        result = entity._prefix_user_message(_user_input("hi"), config)
        assert "{{ input_speaker }}" not in result
        assert "hi" in result
