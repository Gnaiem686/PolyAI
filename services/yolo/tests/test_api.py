import os
import pytest
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
import app as app_module

from unittest.mock import patch

os.environ.setdefault("CONFIDENCE_THRESHOLD", "0.5")

from app import app, init_db

TEST_IMAGE = os.path.join(os.path.dirname(__file__), "data", "beatles.jpeg")


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Initialize a temporary database for tests."""
    db_file = str(tmp_path / "test_predictions.db")
    monkeypatch.setattr("app.DB_PATH", db_file)
    init_db()


@pytest.fixture
def client():
    """Return a TestClient instance for the FastAPI app."""
    return TestClient(app)

class TestPredictionRetrieval(unittest.TestCase):
    def setUp(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.db_path = db_path
        app_module.DB_PATH = db_path

        self.temp_dir = tempfile.TemporaryDirectory()
        self.predicted_image_path = os.path.join(
            self.temp_dir.name,
            "predicted.jpg"
        )

        with open(self.predicted_image_path, "wb") as f:
            f.write(b"fake image content")

        init_db()
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        self.temp_dir.cleanup()

    def insert_test_prediction(self, uid="abc-123"):
        with sqlite3.connect(app_module.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO prediction_sessions (uid, original_image, predicted_image)
                VALUES (?, ?, ?)
                """,
                (uid, "original.jpg", self.predicted_image_path),
            )

            conn.execute(
                """
                INSERT INTO detection_objects (prediction_uid, label, score, box)
                VALUES (?, ?, ?, ?)
                """,
                (uid, "person", 0.91, "[10, 20, 100, 200]"),
            )

    def test_get_prediction_by_uid_found(self):
        self.insert_test_prediction(uid="abc-123")

        response = self.client.get("/prediction/abc-123")

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["uid"], "abc-123")
        self.assertIn("timestamp", data)
        self.assertEqual(data["original_image"], "original.jpg")
        self.assertEqual(data["predicted_image"], self.predicted_image_path)

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
    response = client.get("/ready") ###

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

def test_ready_during_shutdown(client, monkeypatch):

    monkeypatch.setattr(app, "is_shutting_down", True)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service is shutting down"

class TestLabelEndpoint(unittest.TestCase):
    def setUp(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.db_path = db_path
        app_module.DB_PATH = db_path

        init_db()
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def insert_test_prediction(self, uid="abc-123", label="person", score=0.91):
        with sqlite3.connect(app_module.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO prediction_sessions (uid, original_image, predicted_image)
                VALUES (?, ?, ?)
                """,
                (uid, "original.jpg", "predicted.jpg"),
            )

            conn.execute(
                """
                INSERT INTO detection_objects (prediction_uid, label, score, box)
                VALUES (?, ?, ?, ?)
                """,
                (uid, label, score, "[10, 20, 100, 200]"),
            )

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
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        self.db_path = db_path
        app_module.DB_PATH = db_path

        init_db()
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def insert_test_prediction(self, uid="abc-123", label="person", score=0.91):
        with sqlite3.connect(app_module.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO prediction_sessions (uid, original_image, predicted_image)
                VALUES (?, ?, ?)
                """,
                (uid, "original.jpg", "predicted.jpg"),
            )

            conn.execute(
                """
                INSERT INTO detection_objects (prediction_uid, label, score, box)
                VALUES (?, ?, ?, ?)
                """,
                (uid, label, score, "[10, 20, 100, 200]"),
            )

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