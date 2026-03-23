from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.routes import health, pipeline, decisions, scenarios, patient_status, svg_dashboard
from consultation.routers.consultation import router as consultation_router
from chat_agent.router import router as chat_agent_router

app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(pipeline.router)
app.include_router(decisions.router)
app.include_router(scenarios.router)
app.include_router(patient_status.router)
app.include_router(svg_dashboard.router)
app.include_router(consultation_router)
app.include_router(chat_agent_router)

static_dir = Path(__file__).resolve().parent.parent / "static"
scenarios_dir = Path(__file__).resolve().parent.parent / "scenarios"
app.mount("/static", StaticFiles(directory=str(static_dir), html=True), name="static")
if scenarios_dir.exists():
    app.mount("/scenarios", StaticFiles(directory=str(scenarios_dir)), name="test-scenarios")


@app.get("/")
async def root():
    return {"message": f"{settings.APP_TITLE} API is running"}
