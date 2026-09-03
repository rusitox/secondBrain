---
name: Multi-Agent Orchestrator Review
description: Code review of orchestrator.py, agent.py (shim), tool_definitions.py, and updated tests for the parallel multi-agent system
type: project
---

Key findings from this review:

**CRITICAL — shared AsyncSession across parallel sub-agents**
A single AsyncSession is passed to all sub-agents running under asyncio.gather(). SQLAlchemy async sessions are not thread/task-safe for concurrent use. Multiple coroutines issuing DB queries concurrently on the same session can corrupt internal state. Fix: give each sub-agent its own session scope, or run them sequentially.

**CRITICAL — synthesis prompt injection via sub-agent analysis strings**
Sub-agent `analysis` strings (which are LLM-generated summaries of tool results that may themselves include raw tool content) are interpolated into the synthesis user_message with `%` formatting and no fencing markers. An adversarial document could inject instructions targeting the synthesis LLM. Fix: wrap each sub-agent section in explicit XML-style fencing and add an instruction to the synthesis system prompt that agent sections are untrusted data.

**CRITICAL — `generate` missing on mock_llm in integration persistence tests**
`TestConversationTurnPersistence` tests set `mock_llm.generate_with_tools` but do NOT set `mock_llm.generate`. The multi-agent path calls `_llm.generate()` for synthesis; the MagicMock will return a new MagicMock (not a string), causing `_persist_turns` to store a MagicMock as the answer. Tests pass only by accident because `str(MagicMock())` is truthy. Fix: add `mock_llm.generate = AsyncMock(return_value="...")` in those tests.

**WARNING — dead `agents/` subdirectory never imported**
The request states `agents/` (base.py, domain_agents.py, tasks_agent.py, cross_knowledge_agent.py) is dead code — nothing imports from it. Should be deleted to avoid confusion with orchestrator.py which defines the same concepts inline.

**WARNING — unused variable `words` in `_route_agents()`**
`words = set(q_lower.split())` at orchestrator.py:385 is assigned and never used. The matching function `_matches` uses `q_lower` directly (substring check). The `words` variable is leftover from an earlier word-boundary approach.

**WARNING — `TasksAgent` missing `search_learnings`/`save_learning` from `tool_definitions.py` TASKS_TOOLS**
`tool_definitions.py` defines `TASKS_TOOLS = _tools("list_tasks", "search_learnings", "save_learning")` but `TasksAgent._get_tools()` in orchestrator.py only returns `_tools_by_name("list_tasks", "get_calendar")`. The two definitions are out of sync; the orchestrator controls actual runtime behavior. `tool_definitions.py` TASKS_TOOLS is misleading dead code.

**WARNING — `/agent/stream` endpoint bypasses MultiAgentOrchestrator entirely**
The stream endpoint in `agent.py` router builds its own tool_executors dict and calls `agent._llm.generate_with_tools` directly using the old single-agent pattern. It does not go through `MultiAgentOrchestrator`. This means streaming users get the old (non-parallel) behavior without any of the routing or synthesis logic.

**WARNING — `_summarise_history` truncates at 300 chars but passes truncated assistant messages to synthesis LLM**
If an assistant answer was truncated, the synthesis LLM might receive a dangling sentence, potentially confusing it. Also, the history is only fetched in `_resolve_session` (returning chronological list) then sliced via `history[-max_turns * 2:]` — but since history is already at most CONVERSATION_WINDOW=20 entries, the math is fine. The 300-char truncation itself is safe for prompt size, but a very long code snippet truncated mid-line could look like injection to a paranoid model. Low risk in practice.

**INFO — `_route_agents` keyword set gaps**
"call", "llamada", "video", "zoom" would not match FathomAgent. "canal" is Spanish for channel but "channel" (English) is not in _SLACK_KEYWORDS. "mail" would not match OutlookAgent. Consider expanding keyword sets or adding a fallback that also runs FathomAgent for generic questions about meetings.

**INFO — `_tools_by_name` vs `_tools` duplication**
`orchestrator.py` defines `_tools_by_name()` and `tool_definitions.py` defines `_tools()` — both do the same thing (filter AGENT_TOOLS by name set). Only one is needed; the orchestrator could import `_tools` from `tool_definitions`.

**Systemic patterns confirmed:** bare except is absent (good). prompt injection risk in synthesis (5th instance across phases). flush-no-commit pattern (safe here because caller commits). Missing `generate` mock in tests is new.

**Why:** The shared-session under asyncio.gather is the highest-risk item — it can produce subtle data corruption that is hard to reproduce. Fix before any load-bearing production use.
**How to apply:** In future reviews, whenever asyncio.gather is used with a DB session, flag immediately.
