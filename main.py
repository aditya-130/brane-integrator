from fastapi import FastAPI
from app.infrastructure.database import init_db
from app.api import infra, workflow

app = FastAPI(title="Brane Integrator")
@app.on_event("startup")
def on_startup():
    print("Starting Brane Integrator...")
    init_db()
app.include_router(infra.router)
app.include_router(workflow.router)

    