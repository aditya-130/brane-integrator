from sqlmodel import SQLModel, Field

class ParticipantNodeMap(SQLModel, table=True):
    participant_id: str = Field(primary_key=True)
    brane_node: str

class ProjectConfig(SQLModel, table=True):
    project_id: str = Field(primary_key=True)
    coordinator_node: str
    package: str
    local_function: str
    combine_function: str