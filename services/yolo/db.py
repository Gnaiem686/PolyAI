import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_BACKEND = os.getenv("DB_BACKEND", "sqlite").lower()

if DB_BACKEND == "postgres":
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "postgres")
    DATABASE_URL = (
        f"postgresql+psycopg2://{DB_USER}:{quote_plus(DB_PASSWORD)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
else:
    SQLITE_PATH = os.getenv("DB_NAME", "predictions.db")
    DATABASE_URL = f"sqlite:///{SQLITE_PATH}"

connect_args = {}
if DB_BACKEND != "postgres":
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()

# Import models to ensure metadata includes ORM mappings.
from models import PredictionSession, DetectionObject  # noqa: E402,F401


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(custom_engine=None):
    target_engine = custom_engine or engine
    Base.metadata.create_all(bind=target_engine)
