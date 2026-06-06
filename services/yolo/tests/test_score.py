import os
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

import app as app_module
from app import app, init_db


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

    def test_get_predictions_by_score_no_matches(self):
        self.insert_test_prediction(label="person", score=0.4)

        response = self.client.get("/predictions/score/0.9")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_predictions_by_score_too_low(self):
        response = self.client.get("/predictions/score/-0.1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "min_score must be between 0.0 and 1.0"},
        )

    def test_get_predictions_by_score_too_high(self):
        response = self.client.get("/predictions/score/1.1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "min_score must be between 0.0 and 1.0"},
        )