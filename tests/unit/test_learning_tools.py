"""Unit tests for SaveLearningTool, SearchLearningsTool, and LearningExtractor."""
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.tools.save_learning import SaveLearningTool
from app.services.agent.tools.search_learnings import SearchLearningsTool
from app.services.agent.learning_extractor import LearningExtractor
from app.services.llm.claude_client import LLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedder(embedding: List[float] = None) -> MagicMock:
    embedder = MagicMock()
    embedder.embed_single = AsyncMock(return_value=embedding or [0.1] * 1536)
    return embedder


def _make_db_no_duplicate() -> AsyncMock:
    """DB where dedup check returns None (no near-duplicates)."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


def _make_db_with_duplicate(distance: float) -> AsyncMock:
    """DB where dedup check returns a memory at the given cosine distance."""
    mock_mem = MagicMock()
    mock_mem.id = uuid.uuid4()
    mock_mem.embedding = [0.1] * 1536

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = (mock_mem, distance)
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# SaveLearningTool
# ---------------------------------------------------------------------------

class TestSaveLearningToolNewMemory:
    @pytest.mark.asyncio
    async def test_save_new_learning_no_prior_memories(self) -> None:
        tool = SaveLearningTool(embedder=_make_embedder())
        expected_id = uuid.uuid4()

        mock_db = _make_db_no_duplicate()

        # Simulate SQLAlchemy assigning the id on flush
        def _set_id_on_flush() -> None:
            added_memory = mock_db.add.call_args[0][0]
            added_memory.id = expected_id

        mock_db.flush = AsyncMock(side_effect=_set_id_on_flush)

        result = await tool.run(db=mock_db, user_id=uuid.uuid4(), content="Acme prefers async standups")

        assert result["saved"] is True
        assert result["memory_id"] == str(expected_id)
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_entities_stored(self) -> None:
        tool = SaveLearningTool(embedder=_make_embedder())
        mock_db = _make_db_no_duplicate()
        entities = [{"name": "Acme", "type": "company"}]

        await tool.run(
            db=mock_db,
            user_id=uuid.uuid4(),
            content="Acme prefers async standups",
            entities=entities,
        )

        added_memory = mock_db.add.call_args[0][0]
        assert added_memory.entities == entities


class TestSaveLearningToolDeduplication:
    @pytest.mark.asyncio
    async def test_save_duplicate_skipped(self) -> None:
        """Distance 0.07 is within threshold (1 - 0.92 = 0.08), so skip."""
        tool = SaveLearningTool(embedder=_make_embedder())
        mock_db = _make_db_with_duplicate(distance=0.07)

        result = await tool.run(db=mock_db, user_id=uuid.uuid4(), content="duplicate fact")

        assert result["saved"] is False
        assert result["reason"] == "duplicate"
        assert "memory_id" in result
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_near_threshold_saved(self) -> None:
        """Distance 0.09 is above threshold (> 0.08), so save it."""
        tool = SaveLearningTool(embedder=_make_embedder())
        mock_db = _make_db_with_duplicate(distance=0.09)

        result = await tool.run(db=mock_db, user_id=uuid.uuid4(), content="slightly different fact")

        assert result["saved"] is True
        mock_db.add.assert_called_once()


# ---------------------------------------------------------------------------
# SearchLearningsTool
# ---------------------------------------------------------------------------

def _make_mock_memory(content: str = "test content") -> MagicMock:
    mem = MagicMock()
    mem.id = uuid.uuid4()
    mem.content = content
    mem.entities = []
    mem.importance = 3
    mem.source_type = "conversation"
    mem.created_at = None
    return mem


class TestSearchLearningsTool:
    @pytest.mark.asyncio
    async def test_search_returns_ranked_results(self) -> None:
        embedder = _make_embedder()
        tool = SearchLearningsTool(embedder=embedder)

        mem = _make_mock_memory("Acme prefers async standups")
        distance = 0.15

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(mem, distance)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await tool.run(db=mock_db, user_id=uuid.uuid4(), query="standups")

        assert len(results) == 1
        assert results[0]["content"] == "Acme prefers async standups"
        assert results[0]["similarity"] == round(1.0 - distance, 4)
        assert results[0]["memory_id"] == str(mem.id)

    @pytest.mark.asyncio
    async def test_search_empty_returns_empty_list(self) -> None:
        tool = SearchLearningsTool(embedder=_make_embedder())

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await tool.run(db=mock_db, user_id=uuid.uuid4(), query="nothing")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_with_entity_filter(self) -> None:
        """Entity filter should be applied without error and return correct format."""
        tool = SearchLearningsTool(embedder=_make_embedder())
        mem = _make_mock_memory("Acme detail")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(mem, 0.1)]
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await tool.run(
            db=mock_db,
            user_id=uuid.uuid4(),
            query="Acme",
            entity_name="Acme",
        )

        assert len(results) == 1
        assert "similarity" in results[0]
        assert "memory_id" in results[0]


# ---------------------------------------------------------------------------
# LearningExtractor
# ---------------------------------------------------------------------------

def _make_mock_document(content: str = "Meeting notes") -> MagicMock:
    doc = MagicMock()
    doc.content = content
    doc.source = "slack"
    doc.metadata_ = {"author": "Alice"}
    return doc


class TestLearningExtractorEdgeCases:
    @pytest.mark.asyncio
    async def test_extract_empty_documents_returns_empty(self) -> None:
        mock_llm = AsyncMock(spec=LLMClient)
        extractor = LearningExtractor(llm_client=mock_llm, embedder=_make_embedder())
        mock_db = AsyncMock()

        result = await extractor.extract_from_documents(
            db=mock_db, user_id=uuid.uuid4(), documents=[]
        )

        assert result == []
        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_llm_failure_returns_empty(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("API down"))
        extractor = LearningExtractor(llm_client=mock_llm, embedder=_make_embedder())
        mock_db = AsyncMock()

        result = await extractor.extract_from_documents(
            db=mock_db, user_id=uuid.uuid4(), documents=[_make_mock_document()]
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_invalid_json_returns_empty(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="not json")
        extractor = LearningExtractor(llm_client=mock_llm, embedder=_make_embedder())
        mock_db = AsyncMock()

        result = await extractor.extract_from_documents(
            db=mock_db, user_id=uuid.uuid4(), documents=[_make_mock_document()]
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_skips_facts_without_content(self) -> None:
        mock_llm = MagicMock()
        # Fact missing required "content" key
        mock_llm.generate = AsyncMock(
            return_value='[{"entities": [], "importance": 3}]'
        )
        extractor = LearningExtractor(llm_client=mock_llm, embedder=_make_embedder())
        mock_db = _make_db_no_duplicate()

        with patch.object(extractor._save_tool, "run", new_callable=AsyncMock) as mock_save:
            result = await extractor.extract_from_documents(
                db=mock_db, user_id=uuid.uuid4(), documents=[_make_mock_document()]
            )

        assert result == []
        mock_save.assert_not_called()


class TestLearningExtractorHappyPath:
    @pytest.mark.asyncio
    async def test_extract_happy_path(self) -> None:
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(
            return_value='[{"content": "Acme prefers daily standups", "entities": [], "importance": 3}]'
        )
        extractor = LearningExtractor(llm_client=mock_llm, embedder=_make_embedder())

        saved_mem_id = uuid.uuid4()
        saved_mem = MagicMock()
        saved_mem.id = saved_mem_id

        # DB: dedup check returns nothing, then select-by-id returns the saved memory
        mock_db = AsyncMock()
        dedup_result = MagicMock()
        dedup_result.first.return_value = None
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = saved_mem

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Patch save_tool.run directly to control the memory_id
        with patch.object(
            extractor._save_tool,
            "run",
            new_callable=AsyncMock,
            return_value={"saved": True, "memory_id": str(saved_mem_id)},
        ):
            mock_db.execute = AsyncMock(return_value=select_result)
            result = await extractor.extract_from_documents(
                db=mock_db, user_id=uuid.uuid4(), documents=[_make_mock_document()]
            )

        assert len(result) == 1
        assert result[0] is saved_mem
