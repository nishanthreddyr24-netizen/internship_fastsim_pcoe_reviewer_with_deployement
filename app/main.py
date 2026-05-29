"""FastAPI entrypoint for the EV simulation routing service."""

from fastapi import FastAPI

from app.confidence.endpoints import router as confidence_router
from app.physics.endpoints import router as physics_router
from app.routing.endpoints import router as routing_router

app = FastAPI(title="EV Routing Physics Service", version="0.1.0")
app.include_router(confidence_router, prefix="/api/v1")
app.include_router(physics_router, prefix="/api/v1")
app.include_router(routing_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight process health signal."""
    return {"status": "ok"}
