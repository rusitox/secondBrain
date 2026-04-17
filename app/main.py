import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.routers import health, users, commitments, integrations, ingestion, query, agent, briefing, identity

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(debug=settings.debug)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    yield
    logger.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title="Digital Twin API",
    version="0.1.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(health.router)
app.include_router(users.router)
app.include_router(commitments.router)
app.include_router(integrations.router)
app.include_router(ingestion.router)
app.include_router(query.router)
app.include_router(agent.router)
app.include_router(briefing.router)
app.include_router(identity.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
