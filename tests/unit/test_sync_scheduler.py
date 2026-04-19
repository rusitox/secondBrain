"""Unit tests for the server-side sync scheduler."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sync.scheduler import SyncScheduler


def _make_integration(
    is_active: bool = True,
    sync_enabled: bool = True,
    sync_interval_minutes: int = 30,
    platform: str = "outlook",
) -> MagicMock:
    """Create a mock integration object."""
    mock = MagicMock()
    mock.id = uuid.uuid4()
    mock.user_id = uuid.uuid4()
    mock.platform.value = platform
    mock.sync_interval_minutes = sync_interval_minutes
    mock.is_active = is_active
    mock.sync_enabled = sync_enabled
    mock.last_sync_at = None
    mock.last_sync_status = None
    mock.last_sync_error = None
    return mock


class TestSyncSchedulerInit:
    def test_scheduler_creates_without_apscheduler(self) -> None:
        with patch("app.services.sync.scheduler.HAS_APSCHEDULER", False):
            scheduler = SyncScheduler()
            assert not scheduler.is_available
            assert not scheduler.is_running

    def test_scheduler_creates_with_apscheduler(self) -> None:
        scheduler = SyncScheduler()
        assert scheduler.is_available
        assert not scheduler.is_running


class TestSyncSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_shutdown(self) -> None:
        scheduler = SyncScheduler()

        with patch.object(scheduler, "_load_jobs", new_callable=AsyncMock):
            await scheduler.start()
            assert scheduler.is_running

            await scheduler.shutdown()
            assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_start_without_apscheduler(self) -> None:
        with patch("app.services.sync.scheduler.HAS_APSCHEDULER", False):
            scheduler = SyncScheduler()
            await scheduler.start()
            assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self) -> None:
        scheduler = SyncScheduler()
        with patch.object(scheduler, "_load_jobs", new_callable=AsyncMock) as mock_load:
            await scheduler.start()
            await scheduler.start()  # second call should be a no-op
            # _load_jobs called only once (from first start)
            mock_load.assert_called_once()
            await scheduler.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_without_start_is_noop(self) -> None:
        scheduler = SyncScheduler()
        await scheduler.shutdown()  # should not raise
        assert not scheduler.is_running


class TestSyncSchedulerJobs:
    def test_schedule_job(self) -> None:
        scheduler = SyncScheduler()
        mock_integration = _make_integration()
        # Should not raise even without scheduler started
        scheduler._schedule_job(mock_integration)

    def test_remove_job(self) -> None:
        scheduler = SyncScheduler()
        # Should not raise even with no jobs
        scheduler.remove_job(str(uuid.uuid4()))

    def test_get_job_info_empty(self) -> None:
        scheduler = SyncScheduler()
        assert scheduler.get_job_info() == []

    def test_minimum_interval_enforced(self) -> None:
        """Intervals below 5 minutes are clamped to 5."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(sync_interval_minutes=1, platform="slack")

        with patch.object(scheduler, "_scheduler") as mock_sched:
            mock_sched.add_job = MagicMock()
            scheduler._schedule_job(mock_integration)
            mock_sched.add_job.assert_called_once()
            # Verify the trigger has a 5-minute interval (clamped from 1)
            call_kwargs = mock_sched.add_job.call_args
            trigger = call_kwargs.kwargs.get("trigger") or call_kwargs[1].get("trigger")
            if trigger is None:
                trigger = call_kwargs[0][1]  # positional
            assert trigger.interval.total_seconds() == 300  # 5 minutes

    def test_none_interval_defaults_to_30(self) -> None:
        """None sync_interval_minutes defaults to 30."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration()
        mock_integration.sync_interval_minutes = None

        with patch.object(scheduler, "_scheduler") as mock_sched:
            mock_sched.add_job = MagicMock()
            scheduler._schedule_job(mock_integration)
            mock_sched.add_job.assert_called_once()
            call_kwargs = mock_sched.add_job.call_args
            trigger = call_kwargs.kwargs.get("trigger") or call_kwargs[1].get("trigger")
            if trigger is None:
                trigger = call_kwargs[0][1]
            assert trigger.interval.total_seconds() == 1800  # 30 minutes

    def test_reschedule_job_enabled(self) -> None:
        """Reschedule removes old job and adds new one when enabled."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration()

        with patch.object(scheduler, "remove_job") as mock_remove, \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            scheduler.reschedule_job(mock_integration)
            mock_remove.assert_called_once_with(str(mock_integration.id))
            mock_schedule.assert_called_once_with(mock_integration)

    def test_reschedule_job_disabled(self) -> None:
        """Reschedule removes job but doesn't re-add when sync_enabled=False."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(sync_enabled=False)

        with patch.object(scheduler, "remove_job") as mock_remove, \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            scheduler.reschedule_job(mock_integration)
            mock_remove.assert_called_once()
            mock_schedule.assert_not_called()

    def test_reschedule_job_inactive(self) -> None:
        """Reschedule removes job but doesn't re-add when is_active=False."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(is_active=False)

        with patch.object(scheduler, "remove_job") as mock_remove, \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            scheduler.reschedule_job(mock_integration)
            mock_remove.assert_called_once()
            mock_schedule.assert_not_called()

    def test_get_job_info_with_jobs(self) -> None:
        """get_job_info returns job details when jobs exist."""
        scheduler = SyncScheduler()
        mock_job = MagicMock()
        mock_job.id = "sync_abc123"
        mock_job.next_run_time = MagicMock()
        mock_job.next_run_time.isoformat.return_value = "2026-04-19T10:00:00+00:00"

        with patch.object(scheduler, "_scheduler") as mock_sched:
            mock_sched.get_jobs.return_value = [mock_job]
            info = scheduler.get_job_info()
            assert len(info) == 1
            assert info[0]["job_id"] == "sync_abc123"
            assert info[0]["next_run"] == "2026-04-19T10:00:00+00:00"

    def test_get_job_info_with_no_next_run(self) -> None:
        """get_job_info handles jobs with no next_run_time."""
        scheduler = SyncScheduler()
        mock_job = MagicMock()
        mock_job.id = "sync_paused"
        mock_job.next_run_time = None

        with patch.object(scheduler, "_scheduler") as mock_sched:
            mock_sched.get_jobs.return_value = [mock_job]
            info = scheduler.get_job_info()
            assert info[0]["next_run"] is None


class TestLoadJobs:
    @pytest.mark.asyncio
    async def test_load_jobs_schedules_active_integrations(self) -> None:
        """_load_jobs queries DB and schedules jobs for active integrations."""
        scheduler = SyncScheduler()
        integ1 = _make_integration(platform="outlook")
        integ2 = _make_integration(platform="slack")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [integ1, integ2]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory), \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            await scheduler._load_jobs()
            assert mock_schedule.call_count == 2

    @pytest.mark.asyncio
    async def test_load_jobs_empty(self) -> None:
        """_load_jobs with no active integrations schedules nothing."""
        scheduler = SyncScheduler()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory), \
             patch.object(scheduler, "_schedule_job") as mock_schedule:
            await scheduler._load_jobs()
            mock_schedule.assert_not_called()


class TestRunSync:
    @pytest.mark.asyncio
    async def test_run_sync_success(self) -> None:
        """_run_sync fetches items and runs pipeline."""
        scheduler = SyncScheduler()
        integration_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        mock_integration = _make_integration()
        mock_integration.platform.value = "outlook"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_integration

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        mock_connector = MagicMock()
        mock_connector.fetch_items = AsyncMock(return_value=[])

        mock_pipeline_result = MagicMock()
        mock_pipeline_result.documents_created = 3
        mock_pipeline_result.documents_updated = 1

        mock_pipeline = MagicMock()
        mock_pipeline.ingest_batch = AsyncMock(return_value=mock_pipeline_result)

        mock_embedder = MagicMock()

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.api.routers.ingestion._CONNECTORS", {"outlook": lambda: mock_connector}), \
             patch("app.services.integration_service.get_decrypted_token", return_value="tok"), \
             patch("app.services.ingestion.pipeline.IngestionPipeline", return_value=mock_pipeline), \
             patch("app.services.ingestion.embedder.Embedder", return_value=mock_embedder):
            await scheduler._run_sync(integration_id, user_id)

        assert mock_integration.last_sync_status == "success"
        assert mock_integration.last_sync_error is None
        assert mock_integration.last_sync_at is not None
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_sync_integration_not_found(self) -> None:
        """_run_sync returns early if integration is not in DB."""
        scheduler = SyncScheduler()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory):
            # Should not raise
            await scheduler._run_sync(str(uuid.uuid4()), str(uuid.uuid4()))
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_sync_inactive_integration(self) -> None:
        """_run_sync skips inactive integrations."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(is_active=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_integration

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory):
            await scheduler._run_sync(str(mock_integration.id), str(mock_integration.user_id))
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_sync_disabled_integration(self) -> None:
        """_run_sync skips sync-disabled integrations."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(sync_enabled=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_integration

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory):
            await scheduler._run_sync(str(mock_integration.id), str(mock_integration.user_id))
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_sync_unknown_platform(self) -> None:
        """_run_sync records error for unknown platform."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(platform="unknown")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_integration

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.api.routers.ingestion._CONNECTORS", {}), \
             patch("app.services.integration_service.get_decrypted_token", return_value="tok"):
            await scheduler._run_sync(str(mock_integration.id), str(mock_integration.user_id))

        assert mock_integration.last_sync_status == "error"
        assert "Unknown platform" in mock_integration.last_sync_error
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_run_sync_connector_error(self) -> None:
        """_run_sync records error when connector raises."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(platform="outlook")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_integration

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        mock_connector = MagicMock()
        mock_connector.fetch_items = AsyncMock(side_effect=RuntimeError("API timeout"))

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.api.routers.ingestion._CONNECTORS", {"outlook": lambda: mock_connector}), \
             patch("app.services.integration_service.get_decrypted_token", return_value="tok"):
            await scheduler._run_sync(str(mock_integration.id), str(mock_integration.user_id))

        assert mock_integration.last_sync_status == "error"
        assert "API timeout" in mock_integration.last_sync_error
        assert mock_integration.last_sync_at is not None
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_run_sync_error_truncated(self) -> None:
        """_run_sync truncates error messages to 500 chars."""
        scheduler = SyncScheduler()
        mock_integration = _make_integration(platform="outlook")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_integration

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        mock_connector = MagicMock()
        mock_connector.fetch_items = AsyncMock(side_effect=RuntimeError("x" * 1000))

        with patch("app.services.sync.scheduler.get_session_factory", return_value=mock_factory), \
             patch("app.api.routers.ingestion._CONNECTORS", {"outlook": lambda: mock_connector}), \
             patch("app.services.integration_service.get_decrypted_token", return_value="tok"):
            await scheduler._run_sync(str(mock_integration.id), str(mock_integration.user_id))

        assert len(mock_integration.last_sync_error) <= 500


class TestSyncStatusTracking:
    def test_sync_integration_status_schema(self) -> None:
        from app.api.schemas.sync import SyncIntegrationStatus

        status = SyncIntegrationStatus(
            integration_id=str(uuid.uuid4()),
            platform="outlook",
            sync_enabled=True,
            sync_interval_minutes=30,
            last_sync_at=None,
            last_sync_status=None,
            last_sync_error=None,
            next_scheduled_run=None,
        )
        assert status.sync_enabled is True
        assert status.sync_interval_minutes == 30

    def test_sync_configure_request_validates_interval(self) -> None:
        from pydantic import ValidationError
        from app.api.schemas.sync import SyncConfigureRequest

        # Valid
        req = SyncConfigureRequest(platform="outlook", interval_minutes=30)
        assert req.interval_minutes == 30

        # Too low
        with pytest.raises(ValidationError):
            SyncConfigureRequest(platform="outlook", interval_minutes=2)

        # Too high
        with pytest.raises(ValidationError):
            SyncConfigureRequest(platform="outlook", interval_minutes=2000)


class TestCLIAutoDetect:
    @pytest.mark.asyncio
    async def test_skips_when_server_sync_active(self) -> None:
        """BackgroundSync.start() skips client-side sync when server has scheduler."""
        import httpx
        from cli.background import BackgroundSync

        mock_api = MagicMock()
        mock_config = MagicMock()
        mock_config.preferences = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"scheduler_active": True, "integrations": []}
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_api._get_client.return_value = mock_client
        mock_api._base_url = "http://test"
        mock_api._headers.return_value = {}

        bg = BackgroundSync(api=mock_api, config=mock_config, on_sync_result=MagicMock())
        await bg.start()
        assert not bg.is_running  # should NOT start client-side sync

    @pytest.mark.asyncio
    async def test_starts_when_server_sync_inactive(self) -> None:
        """BackgroundSync.start() starts client-side sync when server has no scheduler."""
        from cli.background import BackgroundSync

        mock_api = MagicMock()
        mock_config = MagicMock()
        mock_config.preferences = {}

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"scheduler_active": False, "integrations": []}
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_api._get_client.return_value = mock_client
        mock_api._base_url = "http://test"
        mock_api._headers.return_value = {}

        bg = BackgroundSync(api=mock_api, config=mock_config, on_sync_result=MagicMock())
        await bg.start()
        assert bg.is_running  # should start client-side sync
        await bg.stop()

    @pytest.mark.asyncio
    async def test_starts_when_server_unreachable(self) -> None:
        """BackgroundSync.start() falls through to client-side sync on error."""
        from cli.background import BackgroundSync

        mock_api = MagicMock()
        mock_config = MagicMock()
        mock_config.preferences = {}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_api._get_client.return_value = mock_client
        mock_api._base_url = "http://test"
        mock_api._headers.return_value = {}

        bg = BackgroundSync(api=mock_api, config=mock_config, on_sync_result=MagicMock())
        await bg.start()
        assert bg.is_running  # should fall through to client-side sync
        await bg.stop()
