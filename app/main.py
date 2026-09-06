import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.routers import health, users, commitments, integrations, ingestion, query, agent, briefing, identity, auth, sync, voice, knowledge

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(debug=settings.debug)
    logger.info("Starting %s (env=%s)", settings.app_name, settings.app_env)
    if settings.is_production:
        logger.warning(
            "Running in production mode. "
            "API key auth not yet configured — all endpoints use X-User-Id header."
        )

    # Start sync scheduler if enabled
    sync_scheduler = None
    if settings.is_production or settings.enable_sync_scheduler:
        from app.services.sync.scheduler import SyncScheduler
        sync_scheduler = SyncScheduler()
        if sync_scheduler.is_available:
            await sync_scheduler.start()
            app.state.sync_scheduler = sync_scheduler  # type: ignore[arg-type]
            logger.info("Server-side sync scheduler started")
        else:
            logger.warning("Sync scheduler requested but APScheduler not installed")

    yield

    # Shutdown sync scheduler
    if sync_scheduler and sync_scheduler.is_running:
        await sync_scheduler.shutdown()

    logger.info("Shutting down %s", settings.app_name)


def _parse_cors_origins(settings_value: str) -> List[str]:
    """Parse comma-separated CORS origins, with sensible defaults."""
    if settings_value:
        return [o.strip() for o in settings_value.split(",") if o.strip()]
    return []


app = FastAPI(
    title="Digital Twin API",
    version="0.1.0",
    lifespan=lifespan,
)


def _configure_cors(application: FastAPI) -> None:
    """Configure CORS middleware based on environment settings."""
    try:
        settings = get_settings()
    except Exception:
        # Settings not available (e.g. tests without .env) — skip CORS setup
        return

    origins = _parse_cors_origins(settings.cors_origins)
    if settings.is_production:
        # Production: only allow explicitly configured origins
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "X-User-Id", "Content-Type"],
        )
    else:
        # Development: allow localhost
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[
            "http://localhost:8000",
            "http://localhost:3000",
            "http://127.0.0.1:8000",
        ] + origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )


_configure_cors(app)

# Register routers
app.include_router(auth.router)
app.include_router(health.router)
app.include_router(users.router)
app.include_router(commitments.router)
app.include_router(integrations.router)
app.include_router(ingestion.router)
app.include_router(query.router)
app.include_router(agent.router)
app.include_router(briefing.router)
app.include_router(identity.router)
app.include_router(sync.router)
app.include_router(voice.router)
app.include_router(knowledge.router)

# Mount static files for voice UI (only if directory exists)
_static_voice_dir = os.path.join(os.path.dirname(__file__), "..", "static", "voice")
if os.path.isdir(_static_voice_dir):
    from fastapi.staticfiles import StaticFiles
    app.mount("/voice-ui", StaticFiles(directory=_static_voice_dir, html=True), name="voice-ui")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
