from app.application.config_parser import ConfigParser
from app.domain.config import IntegratorConfig
from app.infrastructure.database import get_db
from app.infrastructure.dtos import GenerateWorkflowRequest
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel

router = APIRouter(prefix="/workflow", tags=["workflow"])

@router.post("")
def generate_workflow(request: GenerateWorkflowRequest, db_session: Session = Depends(get_db)) -> IntegratorConfig:
    return ConfigParser(config=request, db_session=db_session).parse()