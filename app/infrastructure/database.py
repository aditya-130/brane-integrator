from sqlalchemy import text
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

DATABASE_URL = "sqlite:///./integrator.db"

engine = create_engine(DATABASE_URL, echo=True)

def init_db():
    SQLModel.metadata.create_all(engine)
    _migrate()

def _migrate():
    migrations = [
        "ALTER TABLE projectconfig ADD COLUMN invocation_pattern TEXT DEFAULT 'map_reduce'",
        "ALTER TABLE workflow ADD COLUMN validation_result TEXT",
        "ALTER TABLE workflow ADD COLUMN generation_strategy TEXT",
        "ALTER TABLE workflow ADD COLUMN llm_calls_made INTEGER DEFAULT 0",
        "ALTER TABLE workflow ADD COLUMN regeneration_count INTEGER DEFAULT 0",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # column already exists

def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session