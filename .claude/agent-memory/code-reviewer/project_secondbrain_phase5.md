---
name: secondBrain Phase 5 Review Patterns
description: Commitment detection review -- route shadowing, owner field dropped, duplicate multi-chunk detections, recurring dataclass/singleton patterns
type: project
---

Phase 5 code review completed on 2026-04-16. Key findings:

- Route ordering bug: `/commitments/filter/pending` and `/filter/overdue` defined after `/{commitment_id}`, causing FastAPI to match the UUID path parameter first and return 422.
- `owner` field from LLM commitment detection is captured in `DetectedCommitment` but never stored in the database (no `owner` column on `Commitment` model). Core attribution data silently lost.
- Multi-chunk documents trigger commitment detection N times with the full cleaned text (not per-chunk), creating N sets of duplicate commitments.
- `ingest_batch` does not aggregate `commitments_detected` from `ingest_raw` results -- count is dropped during batch sync.
- `datetime.fromisoformat()` on Python 3.8 does not support `Z` timezone suffix that LLM may return.
- No type validation on LLM-returned `priority` field (could be string or float).
- Prompt injection: user text concatenated directly into LLM prompt without delimiters.

**Recurring patterns now confirmed across phases 1/3/4/5:**
1. Plain classes instead of `@dataclass` (DetectedCommitment, IngestionResult -- 4th consecutive phase)
2. Module-level singleton without `@lru_cache` (ingestion router -- 2nd time flagged)
3. Bare/broad exception catches instead of specific types
4. Missing validation at LLM response boundaries

**Why:** These systemic patterns indicate the need for a project-wide conventions check. Each phase introduces the same class of issues.

**How to apply:** In future phases, proactively verify: (a) all data classes use @dataclass, (b) all singletons use @lru_cache, (c) all LLM responses have type-validated fields, (d) route ordering puts static paths before parameterized paths.
