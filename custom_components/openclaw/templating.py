"""Small wrapper around Home Assistant's Jinja templating.

Config fields such as `system_prompt` accept either a literal string or a
Jinja template. Callers render the value at the moment they need it, so state
changes between request-start and result-time are picked up correctly.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import template as ha_template

_LOGGER = logging.getLogger(__name__)


def looks_like_template(text: str | None) -> bool:
    """Cheap heuristic: does the string contain Jinja markers?"""
    if not text:
        return False
    return "{{" in text or "{%" in text


def render(
    hass: HomeAssistant,
    value: str | None,
    variables: Mapping[str, Any] | None = None,
    *,
    fallback: str = "",
) -> str:
    """Render `value` as a Jinja template against Home Assistant state.

    Returns the value unchanged when it doesn't contain Jinja markers.
    On template errors returns `fallback` and logs the error — a bad
    template should not brick the voice pipeline.
    """
    if not value:
        return fallback
    if not looks_like_template(value):
        return value
    try:
        tpl = ha_template.Template(value, hass)
        rendered = tpl.async_render(variables or {}, parse_result=False)
        return "" if rendered is None else str(rendered)
    except TemplateError as err:
        _LOGGER.warning(
            "Template render failed (%s) — using fallback for: %r",
            err,
            value[:120],
        )
        return fallback
