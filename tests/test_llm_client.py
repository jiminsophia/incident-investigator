from __future__ import annotations

import unittest
from types import SimpleNamespace

from incident_investigator.llm.client import StreamedChatCompletionAccumulator


def make_tool_call(
    index: int,
    *,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def make_delta(
    *,
    content=None,
    tool_calls: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


class StreamedChatCompletionAccumulatorTests(unittest.TestCase):
    def test_accumulates_string_content(self) -> None:
        accumulator = StreamedChatCompletionAccumulator()

        emitted = accumulator.append_delta(make_delta(content="Hello "))
        emitted.extend(accumulator.append_delta(make_delta(content="world")))
        response = accumulator.build_response()

        self.assertEqual(emitted, ["Hello ", "world"])
        self.assertEqual(response["content"], "Hello world")
        self.assertEqual(response["assistant_message"], {"role": "assistant", "content": "Hello world"})
        self.assertEqual(response["tool_calls"], [])

    def test_accumulates_content_parts_and_tool_calls(self) -> None:
        accumulator = StreamedChatCompletionAccumulator()

        emitted = accumulator.append_delta(
            make_delta(
                content=[
                    SimpleNamespace(text="{"),
                    SimpleNamespace(text='"ready": '),
                ],
                tool_calls=[
                    make_tool_call(index=0, call_id="call_1", name="run_", arguments='{"re'),
                ],
            )
        )
        emitted.extend(
            accumulator.append_delta(
                make_delta(
                    content=[SimpleNamespace(text="true}")],
                    tool_calls=[
                        make_tool_call(index=0, name="signal_monitor", arguments='ason":"check"}'),
                    ],
                )
            )
        )
        response = accumulator.build_response()

        self.assertEqual(emitted, ["{", '"ready": ', "true}"])
        self.assertEqual(response["content"], '{"ready": true}')
        self.assertEqual(
            response["tool_calls"],
            [
                {
                    "id": "call_1",
                    "name": "run_signal_monitor",
                    "arguments": {"reason": "check"},
                }
            ],
        )
        self.assertEqual(
            response["assistant_message"]["tool_calls"],
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "run_signal_monitor",
                        "arguments": '{"reason":"check"}',
                    },
                }
            ],
        )

    def test_invalid_tool_call_arguments_fall_back_to_empty_dict(self) -> None:
        accumulator = StreamedChatCompletionAccumulator()
        accumulator.append_delta(
            make_delta(
                tool_calls=[make_tool_call(index=0, call_id="call_bad", name="broken_tool", arguments="{")]
            )
        )

        response = accumulator.build_response()

        self.assertEqual(
            response["tool_calls"],
            [{"id": "call_bad", "name": "broken_tool", "arguments": {}}],
        )


if __name__ == "__main__":
    unittest.main()
