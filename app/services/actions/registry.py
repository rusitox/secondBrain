"""Executor registry for agent-proposed actions — the whitelist.

An ``action_type`` the agent proposes (via ``propose_action`` in
strands_tools.py) must be registered here or the proposal is rejected
before a ``ProposedAction`` row is even created. Execution only ever
happens through ``POST /interactions/actions/{id}/approve``
(app/api/routers/interactions.py), never from a tool — no function in
this module is reachable from strands_tools.py, which is precisely what
makes "the model proposed it" and "it ran" two structurally separate
events. See tests/unit/test_action_registry.py's import-boundary guard.

Executors register themselves as an import side effect
(``register(SomeExecutor())`` at module scope) when
app.services.actions.executors is imported — which app/main.py does once
at startup, so the registry is populated for every request without
strands_tools.py ever needing to import that package itself.
"""
import uuid
from typing import Any, Dict, List, Optional, Protocol, Type

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class ActionExecutor(Protocol):
    """What every registered executor must provide.

    ``execute`` is the only method — deliberately narrow. No executor gets
    access to anything beyond a validated payload; it cannot see the
    triggering conversation, the LLM's reasoning, or raw agent state.
    """

    action_type: str
    version: str
    payload_model: Type[BaseModel]
    risk: str

    async def execute(
        self, db: AsyncSession, user_id: uuid.UUID, payload: BaseModel,
    ) -> Dict[str, Any]:
        ...


_REGISTRY: Dict[str, ActionExecutor] = {}


def register(executor: ActionExecutor) -> None:
    _REGISTRY[executor.action_type] = executor


def get(action_type: str) -> Optional[ActionExecutor]:
    return _REGISTRY.get(action_type)


def all_action_types() -> List[str]:
    return sorted(_REGISTRY.keys())


def all_executors() -> List[ActionExecutor]:
    """Every registered executor, sorted by action_type — used by
    describe_action_types (strands_tools.py) to let the model discover
    each action_type's exact payload shape instead of guessing it."""
    return [_REGISTRY[key] for key in sorted(_REGISTRY.keys())]
