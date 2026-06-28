import os
import pytest
import tempfile
import unittest
from fastapi.testclient import TestClient
import db as db_module
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from unittest.mock import patch

os.environ.setdefault("CONFIDENCE_THRESHOLD", "0.5")

from app import app, init_db
from models import DetectionObject, PredictionSession

TEST_IMAGE = os.path.join(os.path.dirname(__file__), "data", "beatles.jpeg")


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Initialize a temporary SQLite database for tests."""
    db_file = tmp_path / "test_predictions.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True
    )
    test_session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine, future=True)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session)

    init_db(custom_engine=test_engine)

    yield

    test_engine.dispose()


@pytest.fixture
def client():
    """Return a TestClient instance for the FastAPI app."""
    return TestClient(app)

class TestPredictionRetrieval(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.predicted_image_path = os.path.join(
            self.temp_dir.name,
            "predicted.jpg"
        )

        with open(self.predicted_image_path, "wb") as f:
            f.write(b"fake image content")

        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def insert_test_prediction(self, uid="abc-123"):
        with db_module.SessionLocal() as session:
            prediction_session = PredictionSession(
                uid=uid,
                original_image="original.jpg",
                predicted_image="chat-1/pred-1/predicted/image.jpg",
            )
            session.add(prediction_session)
            session.add(
                DetectionObject(
                    prediction_uid=uid,
                    label="person",
                    score=0.91,
                    box="[10, 20, 100, 200]",
                )
            )
            session.commit()

    def test_get_prediction_by_uid_found(self):
        self.insert_test_prediction(uid="abc-123")

        response = self.client.get("/prediction/abc-123")

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["uid"], "abc-123")
        self.assertIn("timestamp", data)
        self.assertEqual(data["original_image"], "original.jpg")
        self.assertEqual(data["predicted_image"], "chat-1/pred-1/predicted/image.jpg")

        self.assertEqual(len(data["detection_objects"]), 1)
        self.assertEqual(data["detection_objects"][0]["id"], 1)
        self.assertEqual(data["detection_objects"][0]["label"], "person")
        self.assertEqual(data["detection_objects"][0]["score"], 0.91)
        self.assertEqual(
            data["detection_objects"][0]["box"],
            "[10, 20, 100, 200]"
        )

    def test_get_prediction_by_uid_not_found(self):
        response = self.client.get("/prediction/not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Prediction not found"})

    def test_get_prediction_image_found(self):
        self.insert_test_prediction(uid="abc-123")

        with patch("app.s3_client.get_object") as mock_get_object:
            mock_get_object.return_value = {
                "Body": type("Body", (), {"read": lambda self: b"fake image content"})()
            }

            response = self.client.get("/prediction/abc-123/image")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake image content")

    def test_get_prediction_image_not_found_when_uid_missing(self):
        response = self.client.get("/prediction/not-exist/image")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Image not found"})
    
def test_health(client):
    """Test the health check endpoint returns ok status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_ready_ok(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

def test_ready_during_shutdown(client, monkeypatch):
    import sys

    app_module = sys.modules["app"]
    monkeypatch.setattr(app_module, "is_shutting_down", True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service is shutting down"

class TestLabelEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def insert_test_prediction(self, uid="abc-123", label="person", score=0.91):
        with db_module.SessionLocal() as session:
            prediction_session = PredictionSession(
                uid=uid,
                original_image="original.jpg",
                predicted_image="predicted.jpg",
            )
            session.add(prediction_session)
            session.add(
                DetectionObject(
                    prediction_uid=uid,
                    label=label,
                    score=score,
                    box="[10, 20, 100, 200]",
                )
            )
            session.commit()

    def test_get_predictions_by_label_found(self):
        self.insert_test_prediction(label="person", score=0.91)

        response = self.client.get("/predictions/label/person")

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["uid"], "abc-123")
        self.assertIn("timestamp", data[0])
        self.assertEqual(len(data[0]["detection_objects"]), 1)
        self.assertEqual(data[0]["detection_objects"][0]["label"], "person")
        self.assertEqual(data[0]["detection_objects"][0]["score"], 0.91)
        self.assertEqual(data[0]["detection_objects"][0]["box"], "[10, 20, 100, 200]")

    def test_get_predictions_by_empty_label(self):
        response = self.client.get("/predictions/label/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Label cannot be empty"})

class TestScoreEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def insert_test_prediction(self, uid="abc-123", label="person", score=0.91):
        with db_module.SessionLocal() as session:
            prediction_session = PredictionSession(
                uid=uid,
                original_image="original.jpg",
                predicted_image="predicted.jpg",
            )
            session.add(prediction_session)
            session.add(
                DetectionObject(
                    prediction_uid=uid,
                    label=label,
                    score=score,
                    box="[10, 20, 100, 200]",
                )
            )
            session.commit()

    def test_get_predictions_by_score_found(self):
        self.insert_test_prediction(label="person", score=0.91)

        response = self.client.get("/predictions/score/0.5")

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["prediction_uid"], "abc-123")
        self.assertEqual(data[0]["label"], "person")
        self.assertEqual(data[0]["score"], 0.91)
        self.assertEqual(data[0]["box"], "[10, 20, 100, 200]")

    ## no need to add another one for the higher case
    def test_get_predictions_by_score_too_low(self):
        response = self.client.get("/predictions/score/-0.1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "min_score must be between 0.0 and 1.0"},
        )

    def test_get_predictions_by_empty_score(self):
        response = self.client.get("/predictions/score/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "score cannot be empty"})

def test_predict_with_s3_key(client):
    fake_results = [type("Result", (), {})()]
    fake_box = type("Box", (), {})()

    fake_box.cls = [type("Val", (), {"item": lambda self: 0})()]
    fake_box.conf = [0.91]
    fake_box.xyxy = [type("XY", (), {"tolist": lambda self: [10, 20, 100, 200]})()]

    fake_results[0].boxes = [fake_box]
    fake_results[0].plot = lambda: __import__("numpy").zeros((10, 10, 3), dtype="uint8")

    with patch("app.s3_client.download_file"), \
         patch("app.s3_client.upload_file"), \
         patch("app.model") as mock_model:

        mock_model.return_value = fake_results
        mock_model.names = {0: "person"}

        response = client.post(
            "/predict",
            json={"image_s3_key": "chat-1/pred-1/original/image.jpg"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["detection_count"] == 1
    assert data["labels"] == ["person"]
    assert data["original_image_s3_key"] == "chat-1/pred-1/original/image.jpg"
    assert data["predicted_image_s3_key"] == "chat-1/pred-1/predicted/image.jpg"