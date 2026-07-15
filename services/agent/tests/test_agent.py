import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

os.environ.setdefault("MODEL", "google_genai:gemini-2.5-flash")
os.environ.setdefault("GOOGLE_API_KEY", "fake-test-key")
os.environ.setdefault("YOLO_SERVICE_URL", "http://localhost:8080")
os.environ.setdefault("AWS_S3_BUCKET", "test-bucket")

import app as agent_app
import asyncio
from langchain_core.messages import AIMessage


@pytest.fixture(autouse=True)
def clear_image_session_state():
    agent_app.LATEST_IMAGE_BY_SESSION.clear()

    image_token = agent_app._current_image_b64.set(None)
    session_token = agent_app._current_session_id.set(None)
    s3_key_token = agent_app._current_image_s3_key.set(None)

    yield

    agent_app._current_image_b64.reset(image_token)
    agent_app._current_session_id.reset(session_token)
    agent_app._current_image_s3_key.reset(s3_key_token)

    agent_app.LATEST_IMAGE_BY_SESSION.clear()


def test_parse_yolo_box_handles_common_formats():
    assert agent_app.parse_yolo_box((1, 2, 3, 4)) == (1, 2, 3, 4)
    assert agent_app.parse_yolo_box([1.2, 2.8, 10.1, 20.9]) == (1, 2, 10, 20)
    assert agent_app.parse_yolo_box("[1.2, 2.8, 10.1, 20.9]") == (1, 2, 10, 20)


def test_parse_yolo_box_rejects_bad_box():
    with pytest.raises(ValueError):
        agent_app.parse_yolo_box("(1, 2, 3)")


def test_clamp_box_to_image():
    img = Image.new("RGB", (100, 80), color="white")

    assert agent_app.clamp_box_to_image(-5, -10, 200, 300, img) == (0, 0, 100, 80)


def test_build_image_response_formats_html():
    assert agent_app.build_image_response("Done", "https://example.com/img.png") == (
        'Done\n\n<img src="https://example.com/img.png" alt="Processed image">'
    )


def test_get_current_image_s3_key_reuses_session_image_without_upload():
    agent_app.LATEST_IMAGE_BY_SESSION["session-1"] = "agent-results/latest.png"

    session_token = agent_app._current_session_id.set("session-1")
    image_token = agent_app._current_image_b64.set(None)
    s3_key_token = agent_app._current_image_s3_key.set(None)

    try:
        assert agent_app.get_current_image_s3_key() == "agent-results/latest.png"
    finally:
        agent_app._current_session_id.reset(session_token)
        agent_app._current_image_b64.reset(image_token)
        agent_app._current_image_s3_key.reset(s3_key_token)


def test_detect_objects_returns_ready_to_use_coordinates():
    agent_app._current_image_s3_key.set("test/original/image.jpg")

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
        "detection_objects": [
            {"label": "person", "box": (-10, -5, 50, 90), "score": 0.9},
            {"label": "person", "box": (60, 5, 120, 95), "score": 0.8},
        ]
    })

    with patch("app.download_image_from_s3", return_value=original_img), \
         patch("app.httpx.Client", return_value=fake_client):

        result = agent_app.detect_objects.invoke({})

    data = json.loads(result)

    assert data["input_s3_key"] == "test/original/image.jpg"
    assert data["prediction_uid"] == "uid-1"
    assert data["detection_count"] == 2

    first = data["objects"][0]
    assert first["label"] == "person"
    assert "leftmost" in first["positions"]
    assert first["left"] == 0
    assert first["top"] == 0
    assert first["right"] == 50
    assert first["bottom"] == 90


def test_chat_returns_no_user_message_error():
    client = TestClient(agent_app.app)

    response = client.post("/chat", json={"messages": []})

    assert response.status_code == 200
    assert response.json()["response"] == "No user message was provided."


def test_chat_sets_image_context_and_calls_run_agent():
    client = TestClient(agent_app.app)

    async def fake_run_agent(history, user_text=None):
        assert user_text == "blur the image"
        assert agent_app._current_image_b64.get() == "image-data"
        assert agent_app._current_image_s3_key.get() == "test/original/image.jpg"

        assert "Current working image S3 key" in history[0].content
        assert "Full image coordinates" in history[0].content

        return {
            "response": "ok",
            "prediction_id": None,
            "annotated_image": None,
            "agent_loop_time_s": 0.0,
            "iterations": 1,
            "tools_called": [],
            "context_limit_exceeded": False,
        }

    with patch("app.upload_image_to_s3", return_value="test/original/image.jpg"), \
         patch("app.download_image_from_s3", return_value=Image.new("RGB", (100, 80))), \
         patch("app.run_agent", side_effect=fake_run_agent):

        response = client.post(
            "/chat",
            json={
                "session_id": "test-session",
                "messages": [
                    {
                        "role": "user",
                        "content": "blur the image",
                        "image_base64": "image-data",
                    }
                ],
            },
        )

    assert response.status_code == 200
    assert response.json()["response"] == "ok"
    assert response.json()["session_id"] == "test-session"

class FakeMCPTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []
        self.args_schema = {"properties": {}}

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.result


class FakeMCPClient:
    def __init__(self, tools):
        self.tools = tools

    async def get_tools(self):
        return self.tools


class FakeBoundLLM:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    async def ainvoke(self, messages):
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


class FakeLLM:
    def __init__(self, bound_llm):
        self.bound_llm = bound_llm
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self.bound_llm

def test_run_agent_returns_plain_response_without_tools_new_flow():
    fake_bound_llm = FakeBoundLLM([
        AIMessage(content="Hello! How can I help?")
    ])

    fake_llm = FakeLLM(fake_bound_llm)

    with patch("app.llm", fake_llm), \
         patch("app.MultiServerMCPClient", return_value=FakeMCPClient([])):

        result = asyncio.run(agent_app.run_agent([]))

    assert result["response"] == "Hello! How can I help?"
    assert result["iterations"] == 1
    assert result["tools_called"] == []
    assert result["context_limit_exceeded"] is False

def test_run_agent_executes_mcp_blur_and_returns_image():
    blur_tool = FakeMCPTool(
        name="blur",
        result=json.dumps({
            "input_s3_key": "test/original/image.jpg",
            "output_s3_key": "processed/blur/result.png",
            "operation": "blur",
        }),
    )

    fake_bound_llm = FakeBoundLLM([
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "blur",
                    "args": {
                        "input_s3_key": "test/original/image.jpg",
                        "left": 0,
                        "top": 0,
                        "right": 100,
                        "bottom": 80,
                        "radius": 2.0,
                    },
                    "id": "tool-call-1",
                }
            ],
        )
    ])

    fake_llm = FakeLLM(fake_bound_llm)

    with patch("app.llm", fake_llm), \
         patch("app.MultiServerMCPClient", return_value=FakeMCPClient([blur_tool])), \
         patch("app.create_presigned_url", return_value="https://example.com/result.png"):

        result = asyncio.run(
            agent_app.run_agent([], user_text="blur the image")
        )

    assert result["response"] == (
        'I blurred the image.\n\n'
        '<img src="https://example.com/result.png" alt="Processed image">'
    )
    assert result["tools_called"] == ["blur"]
    assert blur_tool.calls[0]["left"] == 0
    assert blur_tool.calls[0]["top"] == 0
    assert blur_tool.calls[0]["right"] == 100
    assert blur_tool.calls[0]["bottom"] == 80
