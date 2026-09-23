"""Tests for template-rendered proactive_satellite in _resolve_configured_satellite."""
from __future__ import annotations

from unittest.mock import MagicMock

from tests._conversation_loader import load_conversation_module

_conv = load_conversation_module(streaming="none")

CONF_PROACTIVE_SATELLITE = "proactive_satellite"


def _make_entity(satellite: str | None):
    entity = _conv.OpenClawConversationEntity.__new__(
        _conv.OpenClawConversationEntity
    )
    entity._config_entry = MagicMock()
    entity._config_entry.data = {}
    entity._config_entry.options = (
        {CONF_PROACTIVE_SATELLITE: satellite}
        if satellite is not None
        else {}
    )
    entity.hass = MagicMock()
    return entity


class TestResolveConfiguredSatellite:
    def test_literal_entity_id_returned_unchanged(self) -> None:
        entity = _make_entity("assist_satellite.kitchen")
        assert entity._resolve_configured_satellite() == "assist_satellite.kitchen"

    def test_missing_config_returns_none(self) -> None:
        entity = _make_entity(None)
        assert entity._resolve_configured_satellite() is None

    def test_empty_string_returns_none(self) -> None:
        entity = _make_entity("")
        assert entity._resolve_configured_satellite() is None

    def test_template_rendered_at_call_time(self) -> None:
        # The stub Template substitutes the provided `device_id` variable.
        entity = _make_entity("assist_satellite.{{ device_id }}")
        assert entity._resolve_configured_satellite("kitchen") == "assist_satellite.kitchen"

    def test_template_with_missing_var_returns_none_if_empty(self) -> None:
        entity = _make_entity("{{ device_id }}")
        # No device_id passed -> renders empty -> returns None (fall-through)
        assert entity._resolve_configured_satellite() is None

    def test_whitespace_only_returns_none(self) -> None:
        entity = _make_entity("   ")
        assert entity._resolve_configured_satellite() is None
