import logging
import secrets
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.infrastructure.database import init_db, engine
from app.infrastructure.settings import settings
from app.api import infra, workflow, packages
from app.domain.workflow import Workflow
from sqlmodel import Session, select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _cycle_terminal_state(project_id: int) -> str | None:
    try:
        response = httpx.get(
            f"{settings.BRANEHUB_BASE_URL}/api/integration/projects/{project_id}",
            headers={"X-API-Key": settings.BRANE_INTEGRATOR_API_KEY},
            timeout=5,
        )
        if response.status_code == 200:
            return response.json().get("cycle_terminal_state")
    except Exception as e:
        logger.warning("Could not reach BraneHub for project %s: %s", project_id, e)
    return None


def _on_startup():
    logger.info("Starting Brane Integrator...")
    init_db()
    with Session(engine) as db:
        stuck = db.exec(
            select(Workflow).where(Workflow.status.in_(["generating", "executing"]))
        ).all()
        for w in stuck:
            terminal = _cycle_terminal_state(w.project_id)
            if terminal is not None:
                logger.warning("Cycle already ended on BraneHub (%s) — marking workflow %s failed", terminal, w.workflow_id)
                w.status = "failed"
            else:
                logger.info("Cycle still active — resetting workflow %s (%s → pending)", w.workflow_id, w.status)
                w.status = "pending"
            db.add(w)
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _on_startup()
    yield


app = FastAPI(title="Brane Integrator", lifespan=lifespan)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(settings.BRANE_INTEGRATOR_API_KEY, provided):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Missing or invalid X-API-Key"},
        )
    return await call_next(request)


app.include_router(infra.router)
app.include_router(workflow.router)
app.include_router(packages.router)
