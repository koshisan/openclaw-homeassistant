"""Shared helper: stub homeassistant and load the OpenClaw conversation module.

Used by tests that need to exercise `custom_components/openclaw/conversation.py`
without a real Home Assistant installation.

The `streaming` argument controls the shape of the stubbed `ConversationResult`
/ `StreamingConversationResult` so individual tests can exercise each code path
in `_build_streaming_result`:

- "none":     No streaming support. `_supports_streaming_result()` -> False.
- "primary":  `ConversationResult` accepts `setattr(..., "response_stream", ...)`.
- "fallback": `ConversationResult` rejects that setattr (via __slots__), and a
              separate `StreamingConversationResult` class is exposed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _stub_module(name: str) -> ModuleType:
    module = ModuleType(name)
    sys.modules[name] = module
    return module


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_conversation_module(*, streaming: str = "none") -> ModuleType:
    """Stub homeassistant.* and load the conversation module fresh."""
    _stub_module("homeassistant")
    _stub_module("homeassistant.components")
    conversation_mod = _stub_module("homeassistant.components.conversation")
    config_entries_mod = _stub_module("homeassistant.config_entries")
    core_mod = _stub_module("homeassistant.core")
    intent_mod = _stub_module("homeassistant.helpers.intent")
    _stub_module("homeassistant.helpers")
    entity_platform_mod = _stub_module("homeassistant.helpers.entity_platform")
    er_mod = _stub_module("homeassistant.helpers.entity_registry")
    er_mod.async_get = lambda _hass: None
    er_mod.async_entries_for_device = lambda _registry, _device_id: []
    exceptions_mod = _stub_module("homeassistant.exceptions")
    exceptions_mod.HomeAssistantError = type(
        "HomeAssistantError", (Exception,), {}
    )
    exceptions_mod.TemplateError = type("TemplateError", (Exception,), {})

    # Minimal Template stub: renders literal strings, evaluates trivial
    # `{{ variable }}` references from the local `variables` mapping. Just
    # enough for _prefix_user_message unit tests without pulling in Jinja.
    template_mod = _stub_module("homeassistant.helpers.template")

    class _StubTemplate:
        def __init__(self, template: str, _hass: Any = None) -> None:
            self.template = template

        def async_render(
            self, variables: dict[str, Any], parse_result: bool = True
        ) -> str:
            import re as _re
            out = self.template
            for key, value in (variables or {}).items():
                out = out.replace("{{ " + key + " }}", str(value) if value is not None else "")
                out = out.replace("{{" + key + "}}", str(value) if value is not None else "")
            # Unresolved `{{ ... }}` — behave like Jinja with undefined vars:
            # collapse to empty string so fallback paths are testable.
            out = _re.sub(r"\{\{[^}]*\}\}", "", out)
            return out

    template_mod.Template = _StubTemplate

    class ConversationEntity:
        pass

    class AssistantContent:
        def __init__(self, agent_id: str, content: str) -> None:
            self.agent_id = agent_id
            self.content = content

    class ConversationInput:
        pass

    class ChatLog:
        def async_add_assistant_content_without_tools(self, _content: Any) -> None:
            return None

    if streaming == "modern":
        # Modern (HA 2024.10+) — ChatLog has async_add_delta_content_stream.
        # Consumes the stream, records deltas, and yields None once for each.
        class ChatLog(ChatLog):  # type: ignore[no-redef]
            def __init__(self) -> None:
                self.deltas: list[Any] = []

            async def async_add_delta_content_stream(
                self, _agent_id: str, stream: Any
            ):
                async for delta in stream:
                    self.deltas.append(delta)
                    yield delta

        def _async_get_result_from_chat_log(user_input: Any, chat_log: Any) -> Any:
            return SimpleResult(chat_log=chat_log, user_input=user_input)

        class SimpleResult:
            def __init__(self, chat_log: Any, user_input: Any) -> None:
                self.chat_log = chat_log
                self.user_input = user_input
                self.deltas = getattr(chat_log, "deltas", [])

        conversation_mod.async_get_result_from_chat_log = _async_get_result_from_chat_log

    if streaming == "fallback":
        # __slots__ omits response_stream so setattr raises AttributeError,
        # forcing _build_streaming_result into the StreamingConversationResult branch.
        class ConversationResult:
            __slots__ = ("response", "conversation_id", "continue_conversation")

            def __init__(self, response: Any, conversation_id: Any = None) -> None:
                self.response = response
                self.conversation_id = conversation_id
                self.continue_conversation = False

        class StreamingConversationResult:
            def __init__(
                self,
                response: Any,
                conversation_id: Any = None,
                response_stream: Any = None,
            ) -> None:
                self.response = response
                self.conversation_id = conversation_id
                self.response_stream = response_stream
                self.continue_conversation = False

        conversation_mod.StreamingConversationResult = StreamingConversationResult
    else:
        class ConversationResult:
            # Annotation is what _supports_streaming_result inspects in "primary"
            # mode; harmless when unused in "none" mode.
            __annotations__ = (
                {"response_stream": object} if streaming == "primary" else {}
            )

            def __init__(self, response: Any, conversation_id: Any = None) -> None:
                self.response = response
                self.conversation_id = conversation_id
                self.continue_conversation = False

    class IntentResponse:
        def __init__(self, language: str) -> None:
            self.language = language
            self.speech: str | None = None

        def async_set_speech(self, message: str) -> None:
            self.speech = message

    conversation_mod.ConversationEntity = ConversationEntity
    conversation_mod.AssistantContent = AssistantContent
    conversation_mod.ConversationInput = ConversationInput
    conversation_mod.ChatLog = ChatLog
    conversation_mod.ConversationResult = ConversationResult
    config_entries_mod.ConfigEntry = object
    core_mod.HomeAssistant = object
    intent_mod.IntentResponse = IntentResponse
    entity_platform_mod.AddEntitiesCallback = object

    repo_root = Path(__file__).parent.parent
    base = repo_root / "custom_components" / "openclaw"

    # Register custom_components / custom_components.openclaw as real packages
    # so relative imports inside gateway.py ("from .device_auth import ...") work.
    cc_pkg = ModuleType("custom_components")
    cc_pkg.__path__ = [str(repo_root / "custom_components")]  # type: ignore[attr-defined]
    sys.modules["custom_components"] = cc_pkg

    oc_pkg = ModuleType("custom_components.openclaw")
    oc_pkg.__path__ = [str(base)]  # type: ignore[attr-defined]
    sys.modules["custom_components.openclaw"] = oc_pkg

    _load_module("custom_components.openclaw.const", base / "const.py")
    _load_module("custom_components.openclaw.exceptions", base / "exceptions.py")
    _load_module(
        "custom_components.openclaw.device_auth", base / "device_auth.py"
    )
    _load_module("custom_components.openclaw.gateway", base / "gateway.py")
    _load_module(
        "custom_components.openclaw.gateway_client", base / "gateway_client.py"
    )
    _load_module(
        "custom_components.openclaw.templating", base / "templating.py"
    )
    return _load_module(
        "custom_components.openclaw.conversation", base / "conversation.py"
    )
