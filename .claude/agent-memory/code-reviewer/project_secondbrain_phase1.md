---
name: secondBrain Phase 1 Review Patterns
description: Common issues and conventions found in Phase 1 review of secondBrain FastAPI project -- token storage, type mismatches, dependency pinning
type: project
---

Phase 1 code review completed on 2026-04-16. Key findings:

- OAuth tokens (access_token, refresh_token) in Integration model are stored in plaintext despite fernet_key being available in config. This is a security gap that needs encryption before Phase 2 adds actual integrations.
- UUID FK columns annotated as Mapped[str] instead of Mapped[uuid.UUID] across identity, integration, document, commitment models.
- Dependencies in requirements.txt are completely unpinned. Project uses SQLAlchemy 2.0 ORM style (DeclarativeBase, mapped_column) and Pydantic v2 (model_config, pydantic-settings). These must be pinned.
- alembic.ini has hardcoded credentials checked into VCS.
- debug defaults to True in config.py -- dangerous for production.
- TimestampMixin only has created_at, no updated_at.

**Why:** These are foundational issues that will compound as the project grows. Token encryption especially must be resolved before any real OAuth flows are implemented.

**How to apply:** In future reviews, check for: unpinned deps, plaintext secrets, type annotation mismatches on FK columns, and missing updated_at tracking.
