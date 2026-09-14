"""Unit tests for app.services.actions.registry — the action-gate whitelist.

The import-boundary guard here is the mechanical half of "the model can
propose an action but never execute one": strands_tools.py (where
propose_action lives) must never import app.services.actions.executors,
the package that can actually reach an external system. If it did, a
future edit could wire a tool straight to an executor's .execute(),
collapsing propose -> approve -> execute into propose -> execute with no
human in between.
"""
import inspect
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

import app.services.agent.strands_tools as strands_tools_module
from app.services.actions import executors, registry


class _DummyPayload(BaseModel):
    value: str


class _DummyExecutor:
    action_type = "dummy_action"
    version = "1"
    payload_model = _DummyPayload
    risk = "low"

    async def execute(self, db: Any, user_id: uuid.UUID, payload: BaseModel) -> Dict[str, Any]:
        return {"ok": True}


class TestRegistry:
    def setup_method(self) -> None:
        # Isolate from executors/notion.py's real registration and from
        # other tests in this class — registry state is module-global.
        self._saved = dict(registry._REGISTRY)
        registry._REGISTRY.clear()

    def teardown_method(self) -> None:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(self._saved)

    def test_unregistered_action_type_returns_none(self) -> None:
        assert registry.get("nope") is None

    def test_register_then_get(self) -> None:
        registry.register(_DummyExecutor())
        found = registry.get("dummy_action")
        assert found is not None
        assert found.version == "1"

    def test_all_action_types_lists_registered_names(self) -> None:
        registry.register(_DummyExecutor())
        assert "dummy_action" in registry.all_action_types()

    def test_all_executors_lists_registered_executor_objects(self) -> None:
        registry.register(_DummyExecutor())
        executors_list = registry.all_executors()
        assert len(executors_list) == 1
        assert executors_list[0].action_type == "dummy_action"
        assert executors_list[0].payload_model is _DummyPayload


class TestNotionExecutorIsRegistered:
    def test_importing_executors_package_registers_notion_publish(self) -> None:
        """Guards against executors/__init__.py forgetting to import a
        submodule — without that import, registration never happens even
        though the module exists."""
        assert executors is not None  # the import itself is the side effect under test
        found = registry.get("notion_publish")
        assert found is not None
        assert found.action_type == "notion_publish"
        assert found.risk == "low"


class TestUpdateCommitmentExecutorIsRegistered:
    def test_importing_executors_package_registers_update_commitment(self) -> None:
        assert executors is not None  # the import itself is the side effect under test
        found = registry.get("update_commitment")
        assert found is not None
        assert found.action_type == "update_commitment"
        assert found.risk == "low"


class TestCreateCommitmentExecutorIsRegistered:
    def test_importing_executors_package_registers_create_commitment(self) -> None:
        assert executors is not None  # the import itself is the side effect under test
        found = registry.get("create_commitment")
        assert found is not None
        assert found.action_type == "create_commitment"
        assert found.risk == "low"


class TestImportBoundaryGuard:
    def test_strands_tools_never_imports_the_executors_package(self) -> None:
        source = inspect.getsource(strands_tools_module)
        assert "app.services.actions.executors" not in source
        assert "actions.executors" not in source

    def test_strands_tools_only_imports_the_registry_lookup_functions(self) -> None:
        """propose_action reads the registry, never an executor directly."""
        source = inspect.getsource(strands_tools_module)
        assert "from app.services.actions.registry import" in source
