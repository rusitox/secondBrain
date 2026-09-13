"""Importing this package registers every executor as a side effect —
each submodule calls app.services.actions.registry.register(...) at module
scope. Import the submodules here, not lazily inside a request path, so
`from app.services.actions import executors` (app/main.py, at startup) is
the one place that populates the registry.
"""
from app.services.actions.executors import notion  # noqa: F401
from app.services.actions.executors import update_commitment  # noqa: F401
