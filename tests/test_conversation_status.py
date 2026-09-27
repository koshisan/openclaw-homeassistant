"""Unit tests for the ConversationStatusTracker state machine.

Exercises each transition helper in isolation and asserts that the
snapshot payload the dispatcher receives matches expectations. No HA
runtime; the dispatcher is stubbed via `_conversation_loader` so we can
capture the emitted payloads directly.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from ._conversation_loader import load_conversation_module


@pytest.fixture(autouse=True)
def _load_modules() -> None:
    """Reload the shimmed conversation stack for each test.

    Other test files load different `streaming` variants of the loader,
    which replaces `custom_components.openclaw.conversation_status` in
    sys.modules. Reloading here guarantees each test sees a matched
    tracker class + dispatcher-shim pair.
    """
    load_conversation_module()


def _cs_module():
    return sys.modules["custom_components.openclaw.conversation_status"]


def _tracker_class():
    return _cs_module().ConversationStatusTracker


def _const_module():
    return sys.modules["custom_components.openclaw.const"]


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture every dispatcher payload."""
    seen: list[dict[str, Any]] = []

    def _record(_hass: Any, _signal: str, payload: dict[str, Any]) -> None:
        seen.append(dict(payload))

    monkeypatch.setattr(_cs_module(), "async_dispatcher_send", _record)
    return seen


@pytest.fixture
def tracker(captured: list[dict[str, Any]]):
    """Fresh tracker; dispatcher already captures into `captured`."""
    return _tracker_class()(hass=object(), entry_id="entry-1")


class TestConversationStatusTracker:
    def test_initial_state_is_idle(self, tracker: Any) -> None:
        c = _const_module()
        snap = tracker.snapshot
        assert snap["state"] == c.CONVERSATION_STATE_IDLE
        assert snap["run_id"] is None
        assert snap["holding_phrase"] is None
        assert snap["error"] is None

    def test_signal_is_entry_scoped(self, tracker: Any) -> None:
        assert tracker.signal.endswith("_entry-1")

    def test_pending_dispatches_snapshot(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        c = _const_module()
        tracker.set_pending(
            device_id="dev-42", user_message="hello", run_id="r-1"
        )
        assert len(captured) == 1
        snap = captured[0]
        assert snap["state"] == c.CONVERSATION_STATE_PENDING
        assert snap["device_id"] == "dev-42"
        assert snap["user_message"] == "hello"
        assert snap["run_id"] == "r-1"
        assert snap["holding_phrase"] is None
        assert snap["error"] is None

    def test_pending_clears_prior_error(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        c = _const_module()
        tracker.set_error(error="prev failure")
        assert captured[-1]["error"] == "prev failure"
        tracker.set_pending(device_id=None, user_message=None)
        assert captured[-1]["state"] == c.CONVERSATION_STATE_PENDING
        assert captured[-1]["error"] is None

    def test_delayed_carries_holding_phrase_and_run_id(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        c = _const_module()
        tracker.set_delayed(holding_phrase="Moment...", run_id="r-99")
        snap = captured[-1]
        assert snap["state"] == c.CONVERSATION_STATE_DELAYED
        assert snap["holding_phrase"] == "Moment..."
        assert snap["run_id"] == "r-99"

    def test_announcing_optionally_updates_run_id(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        c = _const_module()
        tracker.set_delayed(holding_phrase="wait", run_id="r-77")
        tracker.set_announcing()
        assert captured[-1]["state"] == c.CONVERSATION_STATE_ANNOUNCING
        assert captured[-1]["run_id"] == "r-77"

        tracker.set_announcing(run_id="r-different")
        assert captured[-1]["run_id"] == "r-different"

    def test_idle_wipes_run_metadata(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        c = _const_module()
        tracker.set_delayed(holding_phrase="wait", run_id="r-1")
        tracker.set_idle()
        snap = captured[-1]
        assert snap["state"] == c.CONVERSATION_STATE_IDLE
        assert snap["run_id"] is None
        assert snap["holding_phrase"] is None

    def test_error_transition_records_message(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        c = _const_module()
        tracker.set_error(error="auth: token missing")
        snap = captured[-1]
        assert snap["state"] == c.CONVERSATION_STATE_ERROR
        assert snap["error"] == "auth: token missing"

    def test_changed_at_advances_on_state_change(
        self,
        tracker: Any,
        captured: list[dict[str, Any]],
    ) -> None:
        tracker.set_pending(device_id=None, user_message=None)
        first_ts = captured[-1]["changed_at"]
        tracker.set_pending(device_id=None, user_message=None)
        assert captured[-1]["changed_at"] == first_ts
        tracker.set_idle()
        assert captured[-1]["changed_at"] >= first_ts
