"""FastAPI entrypoint for the EV simulation routing service."""

from fastapi import FastAPI

from app.confidence.endpoints import router as confidence_router
from app.physics.endpoints import router as physics_router
from app.physics.simulator import fsim
from app.routing.endpoints import router as routing_router

app = FastAPI(title="EV Routing Physics Service", version="0.1.0")
app.include_router(confidence_router, prefix="/api/v1")
app.include_router(physics_router, prefix="/api/v1")
app.include_router(routing_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight process health signal."""
    return {"status": "ok"}


@app.get("/diagnostics/runtime")
def runtime_diagnostics() -> dict[str, str]:
    """Expose the active simulation engine so production smoke checks can assert it."""
    return {
        "status": "ok",
        "simulation_engine": "fastsim" if fsim is not None else "synthetic_fallback",
    }
