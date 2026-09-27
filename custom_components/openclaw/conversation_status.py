"""Per-entry conversation-status tracker for the diagnostic sensor.

Owns the current state string plus per-run metadata (run id, device,
optional user message, holding phrase, error). Callers on the
conversation entity and its background report task transition the
tracker at semantic points; each mutation dispatches an update the
sensor entity picks up via `async_dispatcher_connect`.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONVERSATION_STATE_ANNOUNCING,
    CONVERSATION_STATE_DELAYED,
    CONVERSATION_STATE_ERROR,
    CONVERSATION_STATE_IDLE,
    CONVERSATION_STATE_PENDING,
    SIGNAL_CONVERSATION_STATUS,
)


class ConversationStatusTracker:
    """State container for the OpenClaw conversation-status sensor.

    Snapshot fields (see `snapshot`) are the exact payload dispatched to
    subscribers; the sensor uses `state` as its native value and the rest
    as extra attributes.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._state: str = CONVERSATION_STATE_IDLE
        self._run_id: str | None = None
        self._device_id: str | None = None
        self._user_message: str | None = None
        self._holding_phrase: str | None = None
        self._error: str | None = None
        self._changed_at: float = time.time()

    @property
    def signal(self) -> str:
        """Dispatcher signal name (entry-scoped)."""
        return f"{SIGNAL_CONVERSATION_STATUS}_{self._entry_id}"

    @property
    def snapshot(self) -> dict[str, Any]:
        """Return the current state as a plain dict for consumers."""
        return {
            "state": self._state,
            "run_id": self._run_id,
            "device_id": self._device_id,
            "user_message": self._user_message,
            "holding_phrase": self._holding_phrase,
            "error": self._error,
            "changed_at": self._changed_at,
        }

    @callback
    def _emit(self, new_state: str, **updates: Any) -> None:
        """Persist a transition and fan the snapshot out to subscribers."""
        if new_state != self._state:
            self._changed_at = time.time()
        self._state = new_state
        for key, value in updates.items():
            setattr(self, f"_{key}", value)
        async_dispatcher_send(self._hass, self.signal, self.snapshot)

    # --- Transition helpers ------------------------------------------------
    # Each helper is a semantic verb the conversation entity calls at the
    # matching code point. Keeping the state-machine here (not spread over
    # the entity) makes new states cheap to add without hunting call sites.

    @callback
    def set_pending(
        self,
        *,
        run_id: str | None = None,
        device_id: str | None = None,
        user_message: str | None = None,
    ) -> None:
        """New user request in flight, still within the grace window."""
        # A fresh request clears prior holding phrase / error so callers
        # can trust the attributes reflect the current run only.
        self._emit(
            CONVERSATION_STATE_PENDING,
            run_id=run_id,
            device_id=device_id,
            user_message=user_message,
            holding_phrase=None,
            error=None,
        )

    @callback
    def set_delayed(
        self, *, holding_phrase: str, run_id: str | None = None
    ) -> None:
        """Grace period elapsed; holding phrase has been returned to HA."""
        updates: dict[str, Any] = {"holding_phrase": holding_phrase}
        if run_id is not None:
            updates["run_id"] = run_id
        self._emit(CONVERSATION_STATE_DELAYED, **updates)

    @callback
    def set_announcing(self, *, run_id: str | None = None) -> None:
        """Background result arrived; about to speak it on the satellite."""
        if run_id is not None:
            self._emit(CONVERSATION_STATE_ANNOUNCING, run_id=run_id)
        else:
            self._emit(CONVERSATION_STATE_ANNOUNCING)

    @callback
    def set_idle(self) -> None:
        """Turn finished (fast reply returned or background announce done)."""
        self._emit(
            CONVERSATION_STATE_IDLE,
            run_id=None,
            device_id=None,
            user_message=None,
            holding_phrase=None,
            error=None,
        )

    @callback
    def set_error(self, *, error: str) -> None:
        """Terminal failure for the current run (auth, connection, timeout, ...)."""
        self._emit(CONVERSATION_STATE_ERROR, error=error)
