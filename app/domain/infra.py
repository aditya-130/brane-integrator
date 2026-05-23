from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import SQLModel, Field


class ParticipantNodeMap(SQLModel, table=True):
    user_id: int = Field(primary_key=True)
    brane_node: str


class ProjectConfig(SQLModel, table=True):
    project_id: int = Field(primary_key=True)
    coordinator_node: str
    package: str
    local_function: str
    combine_function: str
    finalize_function: Optional[str] = None


class ProvisionedNode(SQLModel, table=True):
    node_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: int = Field(index=True)
    project_id: int = Field(index=True)
    brane_node: str
    port_reg: int
    port_job: int
    port_chk_deliberation: int
    port_chk_store: int
    port_prx: int
    working_dir: str
    status: str = "provisioning"   # provisioning | ready | failed | deprovisioned
    provisioned_at: Optional[datetime] = None
    deprovisioned_at: Optional[datetime] = None


class CoordinatorNode(SQLModel, table=True):
    project_id: int = Field(primary_key=True)
    brane_node: str
    port_reg: int
    port_job: int
    port_chk_deliberation: int
    port_chk_store: int
    port_prx: int
    working_dir: str
    status: str = "provisioning"   # provisioning | ready | failed
    provisioned_at: Optional[datetime] = None