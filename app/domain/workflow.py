from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4

class Workflow(SQLModel, table=True):
    workflow_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str
    branescript: str
    traceability_report: str
    status: str = "generated" # generated | approved | executing | completed | failed | invalidated
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  
    executed_at: Optional[datetime] = None