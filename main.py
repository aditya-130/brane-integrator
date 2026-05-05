import secrets
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.infrastructure.database import init_db, engine
from app.infrastructure.settings import settings
from app.api import infra, workflow
from app.domain.workflow import Workflow
from sqlmodel import Session, select

app = FastAPI(title="Brane Integrator")

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(settings.BRANE_INTEGRATOR_API_KEY, provided):
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Missing or invalid X-API-Key"},
        )
    return await call_next(request)

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
        print(f"[startup] could not reach BraneHub for project {project_id}: {e}")
    return None

@app.on_event("startup")
def on_startup():
    print("Starting Brane Integrator...")
    init_db()
    with Session(engine) as db:
        stuck = db.exec(
            select(Workflow).where(Workflow.status.in_(["generating", "executing"]))
        ).all()
        for w in stuck:
            terminal = _cycle_terminal_state(w.project_id)
            if terminal is not None:
                print(f"[startup] cycle already ended on BraneHub ({terminal}) — marking workflow {w.workflow_id} failed")
                w.status = "failed"
            else:
                print(f"[startup] cycle still active — resetting workflow {w.workflow_id} ({w.status} → pending)")
                w.status = "pending"
            db.add(w)
        db.commit()

app.include_router(infra.router)
app.include_router(workflow.router)

    