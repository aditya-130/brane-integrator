import logging
import os
import secrets
import subprocess
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.infrastructure.database import init_db, engine
from app.infrastructure.settings import settings
from app.api import infra, workflow, packages, admin
from app.domain.workflow import Workflow
from sqlmodel import Session, select

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_WSL_DOCKER_PATH = "/mnt/wsl/docker-desktop/cli-tools/usr/bin"
_CMD_ENV = {**os.environ, "PATH": f"{_WSL_DOCKER_PATH}:{os.environ.get('PATH', '')}"}
_BRANE_RESTART_SCRIPT = os.path.expanduser("~/brane-restart.sh")


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


def _ensure_brane_fwd() -> None:
    """Run brane-restart.sh if brane-fwd container is not running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", "brane-fwd"],
        capture_output=True, text=True, env=_CMD_ENV,
    )
    if result.stdout.strip() == "true":
        logger.info("brane-fwd is running — skipping brane-restart.sh")
        return
    if not os.path.exists(_BRANE_RESTART_SCRIPT):
        logger.warning("brane-fwd is down but %s not found — skipping", _BRANE_RESTART_SCRIPT)
        return
    logger.info("brane-fwd is down — running brane-restart.sh")
    try:
        proc = subprocess.run(
            ["bash", _BRANE_RESTART_SCRIPT],
            capture_output=True, text=True, timeout=120, env=_CMD_ENV,
        )
        if proc.returncode == 0:
            logger.info("brane-restart.sh completed successfully")
        else:
            logger.error("brane-restart.sh failed (rc=%d): %s", proc.returncode, proc.stderr)
    except Exception as exc:
        logger.error("brane-restart.sh error: %s", exc)


def _on_startup():
    logger.info("Starting Brane Integrator...")
    init_db()

    # 1. Ensure brane networking is healthy (runs brane-restart.sh if brane-fwd is down)
    _ensure_brane_fwd()

    # 2. Reset stuck workflows
    with Session(engine) as db:
        stuck = db.exec(
            select(Workflow).where(Workflow.status.in_(["generating", "executing"]))
        ).all()
        for w in stuck:
            terminal = _cycle_terminal_state(w.project_id)
            if terminal is not None:
                logger.warning("Cycle already ended on BraneHub (%s) — marking workflow %s failed",
                               terminal, w.workflow_id)
                w.status = "failed"
            else:
                logger.info("Cycle still active — resetting workflow %s (%s → pending)",
                            w.workflow_id, w.status)
                w.status = "pending"
            db.add(w)
        db.commit()

        # 3. Reconcile all provisioned nodes (restart down ones + refresh brane-fwd socat rules)
        from app.application.node_provisioner.node_provisioner import NodeProvisioner
        try:
            NodeProvisioner().reconcile(db)
        except Exception as exc:
            logger.error("Node reconciliation failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _on_startup()
    yield


app = FastAPI(title="Brane Integrator", lifespan=lifespan)


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path.startswith("/admin"):
        return await call_next(request)
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
app.include_router(admin.router)
