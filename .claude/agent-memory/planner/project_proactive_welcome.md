---
name: Proactive Welcome plan
description: CLI startup welcome reuses /agent/query with a synthetic prompt — no new endpoint, no backend changes
type: project
---

Proactive welcome is implemented entirely in `cli/chat.py` by sending a synthetic "Good morning, give me a situational review" message to the existing `/agent/query` endpoint using the session's `session_id` as turn #1.

**Why:** Reusing the existing agentic loop means all 6 tools (list_tasks, get_calendar, search_learnings, etc.) work automatically without any backend changes. The welcome becomes the first turn of the conversation, giving the agent context for the rest of the session.

**How to apply:** If the user asks to add more content to the welcome (e.g., weather, news), extend the `_WELCOME_PROMPT` constant in `cli/chat.py` — never add a new endpoint or new tool for this purpose. The fallback path (`_show_static_welcome`) must remain in place as a safety net for new users with no data.
