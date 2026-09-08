---
name: backoffice-ui-phase5-review
description: Phase 5 knowledge-backoffice UI review (static/backoffice/) -- CSS/markup mismatch, unguarded render, double-submit gaps; confirms strong XSS/escaping discipline
metadata:
  type: project
---

Phase 5 review completed 2026-09-07, on top of the already-reviewed Phase 4 `/backoffice/*` API
([[project_apikey_auth_review]], [[project_agent_memory_review]] establish the API-key/auth
conventions this UI reuses). Scope: `static/backoffice/{index.html,app.js,style.css}`, `app/main.py`
static mount, `Dockerfile` `COPY static/`. No build step, same vanilla-JS pattern as `static/voice/`
([[project_voice_interface_review]]).

**No CRITICALs.** This pass had unusually strong escaping discipline going in (author had already
audited every `${...}` interpolation) — independently re-derived and confirmed: `escapeHtml()`
(escapes `& < > " '`) is applied to every user/agent-controlled string in every `innerHTML`
template literal, including the `value="..."` attribute on the question-answer input and the
system-prompt textarea body (which correctly neutralizes a literal `</textarea>` in stored prompt
text). Event listeners are correctly re-bound after every `innerHTML` regeneration. The MCP
edit-form key-wipe risk (`if (apiKeyInput) body.api_key = apiKeyInput`) is safe because the backend
(`mcp_server_service.update_mcp_server`) only touches `api_key_encrypted` `if api_key is not None`
— an omitted/empty field is correctly "leave unchanged," not "clear." Similarly
`agent_config_service.upsert_agent_config`'s `mcp_server_ids` param has no `UNSET` sentinel by
design (docstring: "cleared" and "not mentioned" collapse to the same no-op for list/dict fields),
so the frontend omitting `mcp_server_ids` from the PUT body for every non-`rd` agent_key is
correct, not an accidental field wipe.

Findings worth remembering as a *pattern*, not just this file:

- **CSS selector assumes DOM structure that doesn't exist**: `.nav-item span:not(.nav-icon) {
  display: none }` (collapsed-sidebar responsive rule) assumes nav labels are wrapped in a `<span>`
  the way `.brand span` actually is — but `index.html`'s nav buttons have the label as a bare text
  node (`<span class="nav-icon">📊</span>Dashboard`), so the rule silently matches nothing for the
  label and instead accidentally hides the `#questions-badge` notification pill (which *does*
  happen to be a stray `span:not(.nav-icon)`). Lesson for future frontend reviews in this repo: when
  a CSS selector targets "every child except X", verify the actual sibling markup exists — grep the
  HTML for the assumed wrapper, don't trust the selector's intent.
- **Inconsistent try/catch scope across near-identical view-loader functions is a real bug class
  here**: every `load*`/`select*` pair in this file wraps its render call inside the same
  try/catch as the fetch — except `loadGraph()`, where `renderGraph(entities)` sits *after* the
  try/catch block. A Cytoscape init failure (CDN blocked, adblocker) throws uncaught there while
  every sibling view degrades gracefully with a toast. Worth a quick structural diff of
  try/catch boundaries across sibling functions in any file with this many parallel view-loaders.
- **Button-disable-during-request is inconsistent**: `authSubmitBtn`, `runAgentNow`'s button, and
  `testMcpServer`'s button all disable themselves for the request duration; `submitMcpForm`'s
  Guardar button and the question answer/dismiss buttons don't — a double-click on MCP-server
  create can produce two rows (no visible idempotency key in the API).
- Two other systemic-audit misses worth spot-checking again next UI review: the MCP API-key input
  is the only form field not `.trim()`'d before being sent (every sibling field is); and
  `runAgentNow`'s in-flight/disabled state lives only on the captured DOM node, so navigating away
  from an agent mid-run and back re-renders a fresh non-disabled button, allowing a second
  concurrent manual run of the same (LLM-calling) agent.

Confirmed fine, no action needed: `app/main.py` static mounts (`/voice-ui`, `/backoffice-ui`) don't
shadow the `/backoffice` API router (registered first, different path prefix); `Dockerfile`'s new
`COPY static/ ./static/` fixes both UIs' prior 404-in-prod bug; no duplicate DOM ids in
`index.html`; `boot()`'s concurrent `loadDashboard()`/`loadAgentsList()`/`refreshQuestionsBadge()`
don't share mutable state so no race; script tag placement (`app.js` at end of `<body>`, no
`defer` needed) is correct — `init()`'s `getElementById` calls all resolve.
