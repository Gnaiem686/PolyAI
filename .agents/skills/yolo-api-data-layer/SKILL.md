---
name: yolo-api-data-layer
description: Use this skill when refactoring or modifying the YOLO FastAPI service database/data layer, including SQLAlchemy migration, new database-backed endpoints, schema changes, API tests for database-backed behavior, PostgreSQL support, or replacing raw sqlite3 queries.
---

# YOLO API Data Layer Skill

When modifying the YOLO service data layer:

- Refactor raw SQLite usage to SQLAlchemy ORM.
- Use FastAPI dependency injection with `Depends(get_db)`.
- Preserve all existing endpoints, status codes, and response shapes exactly.
- Do not use raw SQL strings for normal CRUD operations.
- Avoid `import sqlite3` in application code after the refactor.
- Define `PredictionSession` and `DetectionObject` as SQLAlchemy models.
- Use relationships or equivalent ORM queries for session-to-object access.
- Replace manual table creation with `Base.metadata.create_all(bind=engine)`.
- Create `services/yolo/models.py` for SQLAlchemy models.
- Create `services/yolo/db.py` for database engine, session, and backend configuration.
- Support SQLite by default.
- Support PostgreSQL when `DB_BACKEND=postgres`.
- Use environment variables such as `DB_BACKEND`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and `DB_NAME`.
- Update tests to use SQLAlchemy sessions and a temporary SQLite database.
- Tests must not use the real database.
- Tests should remain HTTP-level API tests using FastAPI `TestClient`.
- Override FastAPI `get_db` dependency in tests when needed.
- Update `requirements.txt` if SQLAlchemy or PostgreSQL drivers are missing.
- Run `pytest tests/` before claiming completion.
