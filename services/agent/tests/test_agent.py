from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, ToolMessage

from app import run_agent


def test_run_agent_returns_plain_response_without_tools():
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="Hello! How can I help?")

    with patch("app.llm_with_tools", fake_llm):
        result = run_agent([])

    assert result["response"] == "Hello! How can I help?"
    assert result["prediction_id"] is None
    assert result["annotated_image"] is None
    assert result["iterations"] == 1
    assert result["tools_called"] == []
    assert result["context_limit_exceeded"] is False


def test_run_agent_stops_after_max_iterations():
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "detect_objects",
                "args": {},
                "id": "tool-call-1",
            }
        ],
    )

    fake_tool = MagicMock()
    fake_tool.invoke.return_value = ToolMessage(
        content='{"error": "No image was provided by the user."}',
        tool_call_id="tool-call-1",
    )

    with patch("app.llm_with_tools", fake_llm), \
         patch("app.TOOLS", {"detect_objects": fake_tool}):

        result = run_agent([], max_iterations=1)

    assert result["context_limit_exceeded"] is True
    assert result["iterations"] == 1
    assert result["tools_called"] == ["detect_objects"]