from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import UniqueConstraint

class Workflow(SQLModel, table=True):
    workflow_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: int
    cycle_id: int
    triggered_at: str
    script_version: Optional[int] = None
    branescript: Optional[str] = None
    traceability_report: Optional[str] = None
    status: str = "pending" # pending | generating | generated | approved | executing | completed | failed | invalidated
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    executed_at: Optional[datetime] = None

    __table_args__ = (
        UniqueConstraint("project_id", "cycle_id", name="unique_project_cycle"),
    )