---
name: secondBrain Phase 4 Review Patterns
description: RAG retrieval + query endpoint review -- prompt injection, API key validation, singleton thread safety, recurring dataclass/error-handling patterns
type: project
---

Phase 4 code review completed on 2026-04-16. Key findings:

- `str.format()` used with unsanitized user input in RAG prompts (`prompts.py`). Curly braces in questions cause KeyError crashes; also a prompt injection vector. Must escape or use safe templating.
- `claude_api_key` defaults to empty string with no validation -- same pattern as `openai_api_key` from Phase 3. Third consecutive phase with this issue.
- Module-level singleton initialization (`_embedder`, `_claude_client` in query router) is not thread-safe under concurrent requests. Should use `@lru_cache` or FastAPI DI.
- `SearchResult` is a plain class, not a dataclass -- same convention violation as `IngestionResult`/`ConnectorItem` from Phase 3.
- Date range filtering uses string comparison on JSONB `metadata_.timestamp` which breaks with mixed timestamp formats.
- `source` and `sources` filter fields can conflict (AND semantics yields zero results when both set).
- Embedder call in query endpoint has no error handling -- only Claude call is wrapped in try/except.
- Integration tests for search mock the function under test rather than testing actual search logic.
- `services/__init__.py` not updated with `retrieval` and `llm` subpackages.
- `prompts.py` functions use bare `list` instead of `List[Dict[str, Any]]` for type annotations.

**Why:** Three recurring patterns now confirmed across phases 1/3/4: (1) API keys defaulting to empty string, (2) plain classes instead of dataclasses, (3) missing error handling around external API calls. These should be treated as systemic.

**How to apply:** In Phase 5+, proactively check: (a) all new config fields have validation, (b) all data-holding classes use @dataclass, (c) every external API call has specific exception handling, (d) user input is never passed to str.format() unsanitized.
