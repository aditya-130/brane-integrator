from sqlalchemy import text
from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

from app.domain import workflow, infra, package  # noqa: F401 — registers all tables
from app.infrastructure.settings import settings

engine = create_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO)


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
        "ALTER TABLE packagesource ADD COLUMN study_objective TEXT DEFAULT ''",
        "ALTER TABLE packagesource ADD COLUMN local_function TEXT",
        "ALTER TABLE packagesource ADD COLUMN combine_function TEXT",
        "ALTER TABLE workflow ADD COLUMN note TEXT",
        "ALTER TABLE workflow ADD COLUMN execution_result TEXT",
        "ALTER TABLE packagesource ADD COLUMN finalize_function TEXT",
        "ALTER TABLE projectconfig ADD COLUMN finalize_function TEXT",
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
