---
name: Agent memory Phase 3
description: Memory model, migration 010, save_learning + search_learnings tools, LearningExtractor background extractor
type: project
---

Phase 3 adds long-term distilled memory to the agent.

**Key decisions:**

- `Memory` model in `app/models/memory.py` — `memories` table with pgvector embedding (1536), JSONB entities, SMALLINT importance (1-5), source_type/source_ref provenance.
- Migration `010_add_memories_table.py` chains from 009.
- `SaveLearningTool` in `app/services/agent/tools/save_learning.py` — deduplication via cosine distance <= 0.08 (threshold 0.92 similarity) before insert; uses `db.flush()` to get id without committing.
- `SearchLearningsTool` in `app/services/agent/tools/search_learnings.py` — JSONB `entities.contains([{"name": entity_name}])` for entity filtering.
- `LearningExtractor` in `app/services/agent/learning_extractor.py` — batches documents (10/batch, max 20 extractions), calls LLM for JSON fact list, then calls SaveLearningTool per fact.
- `AgentOrchestrator` instance attrs named `_save_learning_tool` / `_search_learnings_tool` (not `_save_learning` / `_search_learnings`) to avoid collision with factory methods of the same name.
- Phase 3 stubs (commented code) in `tool_definitions.py` replaced with live definitions.

**How to apply:** When extending the agent with more long-term memory tools, follow the same factory-method pattern in AgentOrchestrator and register in both AGENT_TOOLS and tool_executors.
