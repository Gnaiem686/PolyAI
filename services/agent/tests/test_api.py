import os
from unittest.mock import patch

os.environ.setdefault("MODEL", "google_genai:gemini-2.5-flash")
os.environ.setdefault("GOOGLE_API_KEY", "fake-test-key")
os.environ.setdefault("YOLO_SERVICE_URL", "http://localhost:8080")

from fastapi.testclient import TestClient
from app import app


client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_returns_structured_response():
    fake_agent_response = {
        "response": "Hello from mocked agent",
        "prediction_id": None,
        "annotated_image": None,
        "agent_loop_time_s": 0.0,
        "iterations": 1,
        "tools_called": [],
        "context_limit_exceeded": False,
    }

    with patch("app.run_agent", return_value=fake_agent_response):
        response = client.post(
            "/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": "hi"
                    }
                ]
            },
        )

    assert response.status_code == 200

    data = response.json()
    assert data["response"] == "Hello from mocked agent"
    assert data["prediction_id"] is None
    assert data["annotated_image"] is None
    assert isinstance(data["agent_loop_time_s"], float)
    assert data["iterations"] == 1
    assert data["tools_called"] == []
    assert data["context_limit_exceeded"] is False
