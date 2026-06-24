---
name: yolo-api-tests
description: Use this skill when writing or modifying API tests for the YOLO FastAPI service, especially endpoints like /predict, /health, /predictions/{uid}, /predictions/label/{label}, /predictions/score/{score}, or image retrieval endpoints.
---

# YOLO API Tests Skill

When writing tests for the YOLO service:

- Prefer HTTP-level API tests using FastAPI `TestClient`.
- Use `unittest`to test the HTTP API.
- Never use the real SQLite database.
- Use a temporary SQLite database for every test run.
- Patch or monkeypatch the app database path before initializing the database.
- Mock the YOLO model or prediction logic when testing endpoints that would otherwise load/run the real model.
- Test file name is `test_api.py`.
- Assert the HTTP status code.
- Assert the response body structure, not only that the request succeeded.
- For list endpoints, verify the response is a list and contains the expected fields.
- For error cases, assert the expected error status code and detail message.
- Optionally use Pydantic models or explicit field checks to validate response body shape.
- Keep tests deterministic and independent from existing local files or databases.
