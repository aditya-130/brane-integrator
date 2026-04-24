from sqlmodel import SQLModel, create_engine, Session
from typing import Generator

DATABASE_URL = "sqlite:///./integrator.db"

engine = create_engine(DATABASE_URL, echo=True)

def init_db():
    SQLModel.metadata.create_all(engine)

def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session