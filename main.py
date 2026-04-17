from fastapi import FastAPI
from app.api.config import router as config_router

app = FastAPI(title="Brane Integrator")
app.include_router(config_router)