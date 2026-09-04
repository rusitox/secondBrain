---
name: Agent Memory Upgrade QA
description: QA audit of Phase 1 (tool-use loop), Phase 2 (conversation memory), Phase 3 (experiential memory) — gaps, coverage, migration status
type: project
---

# Agent Memory Upgrade QA Audit (2026-09-02)

## What passed
- AgentOrchestrator.query(): session_id passthrough, auto-generation, tools_used list, sources extraction from search_memory — all unit-tested
- ToolCall/ToolUseResult dataclasses: imported and used in tests
- generate_with_tools: mocked at the orchestrator level (not directly tested at LLMClient layer)
- API schemas: session_id + iterations fields present in AgentQueryRequest/AgentQueryResponse
- E2E /agent/query: auth, validation (empty/too-long/missing), 502 on RuntimeError, response schema types all covered
- Migrations 009 and 010: correct down_revision chain (008→009→010), correct column types, correct indexes
- ConversationTurn model: matches migration schema exactly
- Memory model: matches migration schema exactly (pgvector 1536, JSONB entities)
- tool_definitions.py: 6 tools defined; save_learning and search_learnings schemas present

## Critical gaps — NOW RESOLVED (2026-09-02)
- generate_with_tools(): 7 tests in tests/unit/test_agent_tool_use.py — all paths covered
- SaveLearningTool.run(): 4 tests in tests/unit/test_learning_tools.py — dedup, save, entities
- SearchLearningsTool.run(): 3 tests in tests/unit/test_learning_tools.py — ranked results, empty, entity filter
- LearningExtractor: 5 tests in tests/unit/test_learning_tools.py — empty, LLM failure, bad JSON, missing content, happy path

### Key implementation note for future tests
- Memory.id is None at construction time (SQLAlchemy column default, not Python default). To test the saved memory_id, use a db.flush side_effect that manually sets memory.id on the object passed to db.add().

## Medium gaps (MEDIUM priority)
- ConversationTurn model: no unit test for the model (fields, indexes) — other models have test_models.py coverage
- test_claude_client.py covers generate() but not generate_with_tools() at all — retry logic tested for generate() only
- E2E /agent/query: session_id not validated in response (no assertion that session_id is a valid UUID string, no test passing session_id in request body and verifying it echoes back)
- AgentOrchestrator: no test for conversation_history parameter being prepended to messages
- tool_executors called correctly: no test verifying _make_save_learning / _make_search_learnings factories bind correct db+user_id

## Low gaps
- tool_definitions.py: no test that all 6 tool names match the executor keys in AgentOrchestrator
- _call_anthropic_with_retry(): 500 server error retry path untested (generate() retry tested, but not the tools variant)
- LearningExtractor source_type="ingestion" field not verified in any test
