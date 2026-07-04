from unittest.mock import MagicMock, patch
from PIL import Image
from langchain_core.messages import AIMessage, ToolMessage

import app as agent_app
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


def test_run_agent_returns_image_tool_result_directly():
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "rotate_image",
                    "args": {},
                    "id": "tool-call-1",
                }
            ],
        ),
        AIMessage(content="This should not be used"),
    ]

    fake_tool = MagicMock()
    fake_tool.invoke.return_value = ToolMessage(
        content='{"message": "I rotated the image.", "image_url": "https://example.com/processed.png"}',
        tool_call_id="tool-call-1",
    )

    with patch("app.llm_with_tools", fake_llm), \
         patch("app.TOOLS", {"rotate_image": fake_tool}):

        result = run_agent([])

    assert fake_llm.invoke.call_count == 1
    assert result["response"] == 'I rotated the image.\n\n<img src="https://example.com/processed.png" alt="Processed image">'
    assert result["tools_called"] == ["rotate_image"]


def test_get_selected_object_crop_clamps_bbox_and_returns_crop():
    token = agent_app._current_image_b64.set("fake-image")
    try:
        original_img = Image.new("RGB", (100, 100), color="red")

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        fake_client = MagicMock()
        fake_client.post.return_value = FakeResponse({"prediction_uid": "uid-1"})
        fake_client.get.return_value = FakeResponse({
            "detection_objects": [{"label": "chair", "box": (-10, -10, 200, 200)}]
        })

        with patch("app.upload_image_to_s3", return_value="s3-key"), \
             patch("app.download_image_from_s3", return_value=original_img), \
             patch("app.httpx.Client", return_value=fake_client):
            _, returned_img, object_crop, bbox, selected_detection = agent_app.get_selected_object_crop(
                label="chair",
                position="first",
            )

        assert returned_img.size == (100, 100)
        assert object_crop.size == (100, 100)
        assert bbox == (0, 0, 100, 100)
        assert selected_detection["box"] == (-10, -10, 200, 200)
    finally:
        agent_app._current_image_b64.reset(token)