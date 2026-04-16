# secondBrain

A personal knowledge management system (Second Brain) based on FastAPI and SQLAlchemy.

## Stack

- **Language**: Python
- **Framework**: FastAPI
- **Package Manager**: pip
- **Linter**: None
- **Testing**: None

## Commands

```bash
python -m uvicorn app.main:app --reload   # Start dev server
echo 'No build configured'               # Production build
echo 'No lint configured'                # Lint
mypy .                                   # Type check
echo 'No tests configured'               # Tests
```

## Architecture

A FastAPI backend with SQLAlchemy for database management, utilizing a modular structure with `api`, `core`, `models`, `services`, and `utils`.

## Conventions

- Follow existing code patterns in the codebase
- All code must pass lint and type checks before commit
- Use structured logging, never console.log in production
- Write tests for new features
- Use Conventional Commits for commit messages

## Key Files

- `app/main.py` - Entry point
- `app/models/` - Database schemas
- `app/api/` - API endpoints
- `requirements.txt` - Dependencies
