from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from app.infrastructure.database import get_db
from app.domain.infra import ParticipantNodeMap, ProjectConfig
from app.infrastructure.dtos import ParticipantNodeMappingRequest, ProjectConfigRequest

router = APIRouter(prefix="/infra", tags=["infra"])


@router.post("/participant-nodes")
def set_participant_node(request: ParticipantNodeMappingRequest, db_session: Session = Depends(get_db)):
    existing = db_session.exec(select(ParticipantNodeMap).where(ParticipantNodeMap.user_id == request.user_id)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Node for user_id={request.user_id} already registered")

    participant_node_map = ParticipantNodeMap(user_id=request.user_id, brane_node=request.brane_node)
    db_session.add(participant_node_map)
    db_session.commit()
    db_session.refresh(participant_node_map)

    return {
        "message": "Participant node mapping created successfully",
        "user_id": participant_node_map.user_id,
        "brane_node": participant_node_map.brane_node,
    }


@router.post("/project-config")
def create_project_config(request: ProjectConfigRequest, db_session: Session = Depends(get_db)):
    existing = db_session.exec(select(ProjectConfig).where(ProjectConfig.project_id == request.project_id)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Config for project_id={request.project_id} already registered")

    project_config = ProjectConfig(
        project_id=request.project_id,
        coordinator_node=request.coordinator_node,
        package=request.package,
        local_function=request.local_function,
        combine_function=request.combine_function
    )
    db_session.add(project_config)
    db_session.commit()
    db_session.refresh(project_config)

    return {
        "message": "Project configuration created successfully",
        "project_id": project_config.project_id,
        "coordinator_node": project_config.coordinator_node,
        "package": project_config.package,
        "local_function": project_config.local_function,
        "combine_function": project_config.combine_function
    }