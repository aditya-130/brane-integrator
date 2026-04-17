from fastapi import APIRouter, HTTPException, Depends
from app.domain.config import IntegratorConfig
from app.infrastructure.branehub_service import BraneHubService

router = APIRouter()

@router.get("/config/{project_id}", response_model=IntegratorConfig)
def fetch_config(project_id: str, branehub: BraneHubService = Depends(BraneHubService)):
    config = branehub.get_integrator_config(project_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return config