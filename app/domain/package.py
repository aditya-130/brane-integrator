from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class PackageSource(SQLModel, table=True):
    project_id: int = Field(primary_key=True)
    source_type: str                        # "generated" | "uploaded"
    study_objective: str = ""
    python_code: str
    container_yml: str
    package_name: str
    package_version: str = "1.0.0"
    build_status: str = "pending"           # "pending" | "built" | "failed"
    built_at: Optional[datetime] = None
    llm_assessment: Optional[str] = None   # JSON-serialised PackageAssessment
    assessment_status: str = "pending"      # "pending" | "approved"
    approved_at: Optional[datetime] = None
    working_dir: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
