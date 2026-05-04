import secrets
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.infrastructure.database import init_db
from app.infrastructure.settings import settings
from app.api import infra, workflow

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

@app.on_event("startup")
def on_startup():
    print("Starting Brane Integrator...")
    init_db()

app.include_router(infra.router)
app.include_router(workflow.router)

    