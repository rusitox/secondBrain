---
name: Teams Connector Review
description: Review of TeamsConnector addition -- path injection, missing retry logic, unsupported OData filters on chat messages endpoint, raw HTML content
type: project
---

Teams connector review completed 2026-04-17. Key findings:

- Path injection risk: `chat_id` interpolated directly into URL without encoding/validation.
- No rate-limit retry logic, unlike SlackConnector which has full 429 + backoff handling. This is the 3rd connector without it (msgraph, fathom, now teams).
- MS Graph `/me/chats/{id}/messages` does NOT support `$filter` or `$orderby` OData params. The `since` filter is silently ignored, causing full re-fetch every sync.
- Raw HTML from `contentType: "html"` messages stored unsanitized -- same systemic issue as msgraph connector email bodies.
- Unsafe nested dict access (`msg.get("from", {}).get("user", {})`) fails when intermediate values are `None` rather than missing.

**Why:** Confirms 3 recurring systemic patterns: (1) no retry/rate-limit at connector boundaries, (2) raw HTML in embeddings, (3) bare dict access crashes. These have appeared in Phase 3 and Phase 5 reviews.

**How to apply:** Any new connector review should immediately check for: retry logic, HTML sanitization, safe nested dict access, and API-specific OData/query param support verification.
