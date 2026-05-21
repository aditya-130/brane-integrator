import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.application.node_provisioner.node_provisioner import NodeProvisioner
from app.domain.infra import ParticipantNodeMap, ProjectConfig
from app.infrastructure.branehub_service import BraneHubService
from app.infrastructure.database import engine, get_db
from app.infrastructure.dtos import (
    DeprovisionRequest,
    ParticipantNodeMappingRequest,
    ProjectConfigRequest,
    ProvisionCoordinatorRequest,
    ProvisionRequest,
    ProvisionResponse,
)

router = APIRouter(prefix="/infra", tags=["infra"])
_provisioner = NodeProvisioner()
_branehub = BraneHubService()


@router.post("/provision", response_model=ProvisionResponse)
async def provision_node(request: ProvisionRequest):
    # Return immediately — provisioning runs in the background and notifies BraneHub
    # via send_participant_ready when done. This avoids BraneHub's 60s HTTP timeout
    # being shorter than the provisioner's worst-case runtime (~180s).
    user_id = request.user_id
    project_id = request.project_id
    brane_node = f"participant-{user_id}"

    def _run():
        with Session(engine) as db:
            result = _provisioner.provision(user_id, project_id, db)
            if result.status == "ready":
                _branehub.send_participant_ready(project_id, user_id, result.brane_node)

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _run)
    return ProvisionResponse(brane_node=brane_node, status="provisioning", error=None)


@router.post("/provision-coordinator", response_model=ProvisionResponse)
async def provision_coordinator(request: ProvisionCoordinatorRequest, db_session: Session = Depends(get_db)):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: _provisioner.provision_coordinator(request.project_id, db_session)
    )
    return ProvisionResponse(brane_node=result.brane_node, status=result.status, error=result.error)


@router.post("/deprovision")
async def deprovision_node(request: DeprovisionRequest, db_session: Session = Depends(get_db)):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, lambda: _provisioner.deprovision(request.user_id, request.project_id, db_session)
    )
    loop.run_in_executor(
        None,
        lambda: _branehub.send_participant_deprovisioned(request.project_id, request.user_id),
    )
    return {"status": "deprovisioned"}


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
        combine_function=request.combine_function,
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
        "combine_function": project_config.combine_function,
    }