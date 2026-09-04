print("[LOAD] backend/database/connection.py is being imported")
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # verifies connection liveness before every checkout
    pool_recycle=60,      # recycle connections after 60s to avoid Neon pooler timeouts
    pool_size=5,          # keep pool small for serverless Neon pooler
    max_overflow=10,
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

from utils.resilience import retry_db_operation

Base = declarative_base()


@retry_db_operation(max_retries=3, initial_delay=0.5, backoff_factor=2.0, jitter=True)
def get_db_session():
    """Create database session with automatic retry on transient connection drops."""
    return SessionLocal()


def get_db():
    db = get_db_session()
    try:
        yield db
    finally:
        db.close()