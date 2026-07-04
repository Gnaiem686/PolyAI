import json
import os
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image
from langchain_core.messages import AIMessage, ToolMessage

os.environ.setdefault("MODEL", "google_genai:gemini-2.5-flash")
os.environ.setdefault("GOOGLE_API_KEY", "fake-test-key")
os.environ.setdefault("YOLO_SERVICE_URL", "http://localhost:8080")

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
        fake_client.__enter__.return_value = fake_client
        fake_client.__exit__.return_value = None
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


def test_parse_yolo_box_and_selection_helpers():
    assert agent_app.parse_yolo_box("(1, 2, 3, 4)") == (1, 2, 3, 4)
    with pytest.raises(ValueError):
        agent_app.parse_yolo_box("(1, 2, 3)")

    detection_objects = [
        {"label": "chair", "box": (0, 0, 10, 10)},
        {"label": "chair", "box": (20, 0, 30, 10)},
        {"label": "table", "box": (5, 0, 15, 10)},
    ]

    selected = agent_app.select_detection(detection_objects, label="chair", position="left")
    assert selected["box"] == (0, 0, 10, 10)

    selected = agent_app.select_detection(detection_objects, label="chair", position="right")
    assert selected["box"] == (20, 0, 30, 10)


def test_select_detection_raises_on_missing_or_unsupported_matches():
    with pytest.raises(ValueError):
        agent_app.select_detection([], label="chair")

    with pytest.raises(ValueError):
        agent_app.select_detection([{"label": "chair", "box": (0, 0, 10, 10)}], label="chair", position="middle")

    with pytest.raises(ValueError):
        agent_app.select_detection([{"label": "chair", "box": (0, 0, 10, 10)}], label="chair", position="second from right")


def test_paste_processed_region_and_clamp_box_to_image():
    original = Image.new("RGB", (10, 10), color="white")
    processed = Image.new("RGB", (2, 2), color="black")

    result = agent_app.paste_processed_region(original, processed, 8, 8, 10, 10)
    assert result.getpixel((8, 8)) == (0, 0, 0)
    assert agent_app.clamp_box_to_image(-5, -5, 20, 20, original) == (0, 0, 10, 10)


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("detect_objects", {}),
        ("flip_image", {"direction": "horizontal"}),
        ("resize_image", {"width": 10, "height": 20}),
        ("crop_image", {"left": 0, "top": 0, "right": 10, "bottom": 10}),
        ("add_noise_image", {"amount": 0.1}),
    ],
)
def test_image_tools_return_error_without_image(tool_name, arguments):
    tool = getattr(agent_app, tool_name)
    result = tool.invoke(arguments)

    assert json.loads(result)["error"] == "No image was provided by the user."


def test_run_agent_handles_list_content():
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content=[{"text": "Hello from list"}])

    with patch("app.llm_with_tools", fake_llm):
        result = run_agent([])

    assert result["response"] == "Hello from list"
    assert result["tools_called"] == []


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_error"),
    [
        ("flip_image", {"direction": "diagonal"}, "direction must be 'horizontal' or 'vertical'"),
        ("resize_image", {"width": 0, "height": 10}, "width and height must be positive integers"),
        ("crop_image", {"left": 10, "top": 5, "right": 5, "bottom": 6}, "Invalid crop box. right must be greater than left, and bottom must be greater than top."),
        ("add_noise_image", {"amount": 1.5}, "amount must be greater than 0 and less than or equal to 1"),
    ],
)
def test_image_tool_validation_errors(tool_name, arguments, expected_error):
    token = agent_app._current_image_b64.set("fake-image")
    try:
        tool = getattr(agent_app, tool_name)
        result = tool.invoke(arguments)
    finally:
        agent_app._current_image_b64.reset(token)

    assert json.loads(result)["error"] == expected_error


def test_build_image_response_formats_html():
    assert agent_app.build_image_response("Done", "https://example.com/img.png") == (
        'Done\n\n<img src="https://example.com/img.png" alt="Processed image">'
    )


def test_chat_sets_image_context_and_appends_instruction():
    from fastapi.testclient import TestClient

    client = TestClient(agent_app.app)

    def fake_run_agent(history):
        assert agent_app._current_image_b64.get() == "image-data"
        assert history[0].content.endswith(
            "[An image was uploaded with this message. Use the available tools to analyze or edit this uploaded image according to the user instructions.]"
        )
        return {
            "response": "ok",
            "prediction_id": None,
            "annotated_image": None,
            "agent_loop_time_s": 0.0,
            "iterations": 1,
            "tools_called": [],
            "context_limit_exceeded": False,
        }

    with patch("app.run_agent", side_effect=fake_run_agent):
        response = client.post(
            "/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "describe this",
                        "image_base64": "image-data",
                    }
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["response"] == "ok"


def test_chat_returns_no_user_message_error():
    from fastapi.testclient import TestClient

    client = TestClient(agent_app.app)
    response = client.post("/chat", json={"messages": []})

    assert response.status_code == 200
    assert response.json()["response"] == "No user message was provided."