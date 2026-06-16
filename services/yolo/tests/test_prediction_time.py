import os
import unittest
import tempfile
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

import app as app_module
from app import app, init_db

TEST_IMAGE = os.path.join(os.path.dirname(__file__), "data", "beatles.jpeg")


class TestPredictionTime(unittest.TestCase):
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

    @patch("app.Image")
    @patch("app.model")
    def test_predict_includes_processing_time(self, mock_model, mock_image):
        fake_box = MagicMock()

        fake_box.cls = [MagicMock()]
        fake_box.cls[0].item.return_value = 0

        fake_box.conf = [0.91]

        fake_xyxy = MagicMock()
        fake_xyxy.tolist.return_value = [10, 20, 100, 200]
        fake_box.xyxy = [fake_xyxy]

        fake_result = MagicMock()
        fake_result.boxes = [fake_box]
        fake_result.plot.return_value = "fake_frame"

        mock_model.return_value = [fake_result]
        mock_model.names = {0: "person"}

        fake_image = MagicMock()
        mock_image.fromarray.return_value = fake_image

        with open(TEST_IMAGE, "rb") as f:
            response = self.client.post(
                "/predict",
                files={"file": ("beatles.jpeg", f, "image/jpeg")}
            )

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("prediction_uid", data)
        self.assertEqual(data["detection_count"], 1)
        self.assertEqual(data["labels"], ["person"])

        self.assertIn("time_took", data)
        self.assertIsInstance(data["time_took"], (int, float))
        self.assertGreaterEqual(data["time_took"], 0)

        mock_model.assert_called_once()
        fake_image.save.assert_called_once()

    def test_predict_rejects_non_image_file(self):
        response = self.client.post(
            "/predict",
            files={"file": ("document.pdf", b"fake pdf content", "application/pdf")}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Only image files are supported"})