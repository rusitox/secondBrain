import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.api.routers import (
    health, users, commitments, integrations, ingestion, query, agent, briefing,
    identity, auth, sync, voice, knowledge, interactions, systems,
)
# Populates app.services.actions.registry as an import side effect, so it's
# ready before any request reaches propose_action (strands_tools.py) or the
# approve endpoint (interactions.py) — neither of which imports this
# package directly; see app/services/actions/registry.py's module docstring.
from app.services.actions import executors as _action_executors  # noqa: F401

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

    # Start knowledge agent scheduler if enabled — explicit opt-in only, NOT tied to
    # is_production like the sync scheduler above (every cycle makes real LLM calls).
    knowledge_scheduler = None
    if settings.enable_knowledge_agents:
        from app.services.agent.knowledge.scheduler import KnowledgeAgentScheduler
        knowledge_scheduler = KnowledgeAgentScheduler()
        if knowledge_scheduler.is_available:
            await knowledge_scheduler.start()
            app.state.knowledge_scheduler = knowledge_scheduler  # type: ignore[arg-type]
            logger.info("Knowledge agent scheduler started")
        else:
            logger.warning("Knowledge agent scheduler requested but APScheduler not installed")

    # Action sweeper — always on when APScheduler is available. Pure DB
    # housekeeping (no external API/LLM calls), recovering ProposedAction
    # rows stuck in EXECUTING after a crash; see app/services/actions/
    # sweeper.py's module docstring.
    from app.services.actions.sweeper import ActionSweeper
    action_sweeper = ActionSweeper()
    if action_sweeper.is_available:
        await action_sweeper.start()
        app.state.action_sweeper = action_sweeper  # type: ignore[arg-type]
        logger.info("Action sweeper started")
    else:
        logger.warning("Action sweeper requested but APScheduler not installed")

    yield

    # Shutdown sync scheduler
    if sync_scheduler and sync_scheduler.is_running:
        await sync_scheduler.shutdown()

    # Shutdown knowledge agent scheduler
    if knowledge_scheduler and knowledge_scheduler.is_running:
        await knowledge_scheduler.shutdown()

    # Shutdown action sweeper
    if action_sweeper.is_running:
        await action_sweeper.shutdown()

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
app.include_router(interactions.router)
app.include_router(systems.router)

# Mount static frontends (only if built — `directory` must exist at mount
# time). Historically this failed silently in production: the Dockerfile
# never COPYed static/ into the image at all, so /voice-ui 404ed with no
# log line explaining why (see Dockerfile's new frontend-builder stage and
# its `COPY --from=frontend-builder /frontend/dist ./static/marea` /
# `COPY static/voice ./static/voice`, which fix that). The warning below
# means a future regression is at least visible in the startup log.
from fastapi.staticfiles import StaticFiles

_static_voice_dir = os.path.join(os.path.dirname(__file__), "..", "static", "voice")
if os.path.isdir(_static_voice_dir):
    app.mount("/voice-ui", StaticFiles(directory=_static_voice_dir, html=True), name="voice-ui")
else:
    logger.warning("static/voice not found — /voice-ui will 404")

# MAREA (Svelte) — coexists with /voice-ui until it reaches feature parity,
# per the redesign plan's Fase 4. Built from frontend/ via `npm run build`
# (frontend/vite.config.ts sets outDir to ../static/marea and base to
# /marea/ so its own asset URLs resolve correctly under this mount).
_static_marea_dir = os.path.join(os.path.dirname(__file__), "..", "static", "marea")
if os.path.isdir(_static_marea_dir):
    app.mount("/marea", StaticFiles(directory=_static_marea_dir, html=True), name="marea")
else:
    logger.warning("static/marea not found — /marea will 404 (run `npm run build` in frontend/)")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
