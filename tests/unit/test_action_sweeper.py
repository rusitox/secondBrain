"""Unit tests for the ActionSweeper — recovers ProposedAction rows stuck
in EXECUTING after a crash between approve_action's mark_executing()
commit and executor.execute() finishing (see app/services/actions/
sweeper.py's module docstring for the full failure window this closes).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.actions.sweeper import ActionSweeper


def _make_stuck_action() -> MagicMock:
    action = MagicMock()
    action.id = uuid.uuid4()
    action.user_id = uuid.uuid4()
    return action


class TestActionSweeperInit:
    def test_creates_without_apscheduler(self) -> None:
        with patch("app.services.actions.sweeper.HAS_APSCHEDULER", False):
            sweeper = ActionSweeper()
            assert not sweeper.is_available
            assert not sweeper.is_running

    def test_creates_with_apscheduler(self) -> None:
        sweeper = ActionSweeper()
        assert sweeper.is_available
        assert not sweeper.is_running


class TestActionSweeperLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_shutdown(self) -> None:
        sweeper = ActionSweeper()
        await sweeper.start()
        assert sweeper.is_running
        await sweeper.shutdown()
        assert not sweeper.is_running

    @pytest.mark.asyncio
    async def test_start_without_apscheduler_is_noop(self) -> None:
        with patch("app.services.actions.sweeper.HAS_APSCHEDULER", False):
            sweeper = ActionSweeper()
            await sweeper.start()
            assert not sweeper.is_running

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        sweeper = ActionSweeper()
        await sweeper.start()
        await sweeper.start()  # must not raise (e.g. duplicate job id)
        assert sweeper.is_running
        await sweeper.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_without_start_is_noop(self) -> None:
        sweeper = ActionSweeper()
        await sweeper.shutdown()
        assert not sweeper.is_running


class TestSweep:
    @pytest.mark.asyncio
    async def test_marks_stuck_executing_actions_as_failed(self) -> None:
        sweeper = ActionSweeper()
        stuck = _make_stuck_action()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.actions.sweeper.get_session_factory", return_value=mock_factory), \
             patch("app.services.actions.sweeper.actions_store.mark_failed", new=AsyncMock()) as mock_fail, \
             patch("app.services.actions.sweeper.actions_store.write_audit", new=AsyncMock()) as mock_audit:
            await sweeper._sweep()

        mock_fail.assert_awaited_once()
        assert mock_fail.await_args.args[1] == stuck.id
        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs.get("event") == "failed"
        assert mock_audit.await_args.kwargs.get("actor") == "system"
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_stuck_actions_does_not_commit(self) -> None:
        sweeper = ActionSweeper()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.actions.sweeper.get_session_factory", return_value=mock_factory), \
             patch("app.services.actions.sweeper.actions_store.mark_failed", new=AsyncMock()) as mock_fail:
            await sweeper._sweep()

        mock_fail.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweeps_multiple_stuck_actions(self) -> None:
        sweeper = ActionSweeper()
        stuck1, stuck2 = _make_stuck_action(), _make_stuck_action()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stuck1, stuck2]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.actions.sweeper.get_session_factory", return_value=mock_factory), \
             patch("app.services.actions.sweeper.actions_store.mark_failed", new=AsyncMock()) as mock_fail, \
             patch("app.services.actions.sweeper.actions_store.write_audit", new=AsyncMock()):
            await sweeper._sweep()

        assert mock_fail.await_count == 2
        mock_session.commit.assert_awaited_once()
