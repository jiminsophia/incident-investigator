from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency at runtime
    OpenAI = None


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str = "EMPTY"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "LLMConfig | None":
        base_url = os.getenv("VLLM_API_BASE", "").strip()
        model = os.getenv("VLLM_MODEL", "").strip()
        api_key = os.getenv("VLLM_API_KEY", "EMPTY").strip() or "EMPTY"
        timeout = float(os.getenv("VLLM_TIMEOUT_SECONDS", "30"))
        if not base_url or not model:
            return None
        return cls(
            base_url=base_url.rstrip("/"),
            model=model,
            api_key=api_key,
            timeout_seconds=timeout,
        )


@dataclass
class StreamedChatCompletionAccumulator:
    content_parts: list[str] = field(default_factory=list)
    tool_calls_by_index: dict[int, dict[str, Any]] = field(
        default_factory=lambda: defaultdict(
            lambda: {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
        )
    )

    def append_delta(self, delta: Any) -> list[str]:
        emitted_content: list[str] = []
        if delta is None:
            return emitted_content

        content = getattr(delta, "content", None)
        if content:
            if isinstance(content, str):
                parts = [content]
            else:
                parts = [
                    getattr(part, "text", "")
                    for part in content
                    if getattr(part, "text", "")
                ]
            self.content_parts.extend(parts)
            emitted_content.extend(parts)

        for tool_call in getattr(delta, "tool_calls", None) or []:
            index = getattr(tool_call, "index", 0) or 0
            entry = self.tool_calls_by_index[index]
            if tool_call.id:
                entry["id"] = tool_call.id
            function = getattr(tool_call, "function", None)
            if function is None:
                continue
            if function.name:
                entry["function"]["name"] += function.name
            if function.arguments:
                entry["function"]["arguments"] += function.arguments

        return emitted_content

    def build_response(self) -> dict[str, Any]:
        content = "".join(self.content_parts)
        tool_calls = []
        assistant_tool_calls = []
        for index in sorted(self.tool_calls_by_index):
            tool_call = self.tool_calls_by_index[index]
            arguments = tool_call["function"]["arguments"] or "{}"
            assistant_tool_calls.append(
                {
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {
                        "name": tool_call["function"]["name"],
                        "arguments": arguments,
                    },
                }
            )
            try:
                parsed_arguments = json.loads(arguments)
            except json.JSONDecodeError:
                parsed_arguments = {}
            tool_calls.append(
                {
                    "id": tool_call["id"],
                    "name": tool_call["function"]["name"],
                    "arguments": parsed_arguments,
                }
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls

        return {
            "content": content,
            "tool_calls": tool_calls,
            "assistant_message": assistant_message,
        }


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        if OpenAI is None:
            raise RuntimeError(
                "The openai package is required for vLLM support. Install dependencies from requirements.txt."
            )
        self.config = config
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout_seconds,
        )

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        stream_handler: Callable[[dict[str, Any]], None] | None = None,
        response_label: str = "LLM Response",
    ) -> dict[str, Any]:
        response = self._stream_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            stream_handler=stream_handler,
            response_label=response_label,
        )
        return self._parse_json(response["content"])

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        stream_handler: Callable[[dict[str, Any]], None] | None = None,
        response_label: str = "LLM Response",
    ) -> dict[str, Any]:
        return self._stream_chat_completion(
            messages=messages,
            tools=tools,
            stream_handler=stream_handler,
            response_label=response_label,
            tool_choice="auto",
            temperature=0.2,
        )

    def _stream_chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        stream_handler: Callable[[dict[str, Any]], None] | None = None,
        response_label: str = "LLM Response",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools is not None:
            request["tools"] = tools
        if tool_choice is not None:
            request["tool_choice"] = tool_choice

        stream_id = uuid4().hex
        self._emit_stream_event(
            stream_handler,
            {
                "phase": "start",
                "stream_id": stream_id,
                "label": response_label,
                "category": "llm",
            },
        )

        response = self._client.chat.completions.create(**request)
        accumulator = StreamedChatCompletionAccumulator()
        for chunk in response:
            for choice in getattr(chunk, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                for content_delta in accumulator.append_delta(delta):
                    self._emit_stream_event(
                        stream_handler,
                        {
                            "phase": "delta",
                            "stream_id": stream_id,
                            "label": response_label,
                            "category": "llm",
                            "delta": content_delta,
                        },
                    )

        result = accumulator.build_response()
        content = result["content"]
        self._emit_stream_event(
            stream_handler,
            {
                "phase": "complete",
                "stream_id": stream_id,
                "label": response_label,
                "category": "llm",
                "content": content,
            },
        )

        return result

    def _emit_stream_event(
        self,
        stream_handler: Callable[[dict[str, Any]], None] | None,
        event: dict[str, Any],
    ) -> None:
        if stream_handler is not None:
            stream_handler(event)

    def _parse_json(self, content: str) -> dict[str, Any]:
        normalized = content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3:
                normalized = "\n".join(lines[1:-1]).strip()
        return json.loads(normalized)
