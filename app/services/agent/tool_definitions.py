"""Anthropic tool definitions for the agent loop.

Each entry follows the Anthropic tool-use JSON schema format.
The tool_executors dict in AgentOrchestrator maps these names to callables.

Per-agent subsets (ORCHESTRATOR_TOOLS, SLACK_TOOLS, etc.) are derived from
AGENT_TOOLS by name so there is a single source of truth for each schema.
"""
from typing import Any, Dict, List

AGENT_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_memory",
        "description": (
            "Search the user's knowledge base (emails, Slack messages, meeting transcripts, "
            "Notion pages, Teams chats). Use this to find specific information the user has "
            "received or discussed. Returns ranked text snippets with source metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in the knowledge base",
                },
                "source": {
                    "type": "string",
                    "enum": ["slack", "outlook", "fathom", "teams", "notion"],
                    "description": "Optional: filter results to a specific platform",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_tasks",
        "description": (
            "List the user's pending commitments, action items, and promises. "
            "Returns tasks with priority, owner, due date, status, and source provenance "
            "(platform, subject, author, timestamp of the original message or document "
            "where the commitment was detected). Use the source field to answer questions "
            "like 'where did this task come from?' or 'who said this?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_overdue": {
                    "type": "boolean",
                    "description": "If true, only return overdue items",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_calendar",
        "description": (
            "Get the user's calendar events for a specific date. "
            "Returns meeting subjects, start times, organizers, and attendees. "
            "Use this to answer questions like 'what meetings do I have today?', "
            "'what's on my calendar tomorrow?', or 'do I have anything on Friday?'. "
            "If no date is specified, defaults to today."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": (
                        "Target date in YYYY-MM-DD format (e.g. '2025-09-04'). "
                        "Omit or leave empty to get today's events."
                    ),
                },
                "upcoming_only": {
                    "type": "boolean",
                    "description": "If true (default), only return events that have not yet started.",
                    "default": True,
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_user_style",
        "description": (
            "Get the user's communication persona, tone guidelines, and style preferences. "
            "ALWAYS call this first before generating any response to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_learnings",
        "description": (
            "Search long-term memory for insights and learnings about clients, projects, "
            "and patterns. Use this when you need to recall what has been learned about "
            "a specific person, company, or topic across all past conversations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in long-term memory",
                },
                "entity_name": {
                    "type": "string",
                    "description": "Optional: filter by person or company name",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_sync_status",
        "description": (
            "Return the last sync timestamp and status for each connected data source "
            "(Slack, Outlook, Teams, Fathom, Notion). Use this to answer questions like "
            "'when was X last updated?', 'is my Slack data fresh?', or 'why is my data stale?'. "
            "Returns platform, last_sync_at (ISO timestamp), status (success/error/null), "
            "error message if any, and sync interval in minutes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "save_learning",
        "description": (
            "Persist a learning or insight to long-term memory. Use this when you discover "
            "something important about a client, project, or pattern that should be remembered "
            "in future conversations. Examples: client preferences, project constraints, "
            "key decisions made, relationship context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The learning, written as a clear factual statement",
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["person", "company", "project", "product"],
                            },
                        },
                        "required": ["name", "type"],
                    },
                    "description": "People, companies, or projects this learning is about",
                },
                "importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "1=trivia, 3=useful, 5=critical",
                },
            },
            "required": ["content"],
        },
    },
]


# ---------------------------------------------------------------------------
# Per-agent tool subsets
# ---------------------------------------------------------------------------
# Derived from AGENT_TOOLS by name — single source of truth for each schema.

def _tools(*names: str) -> List[Dict[str, Any]]:
    """Filter AGENT_TOOLS to only the named tools, preserving AGENT_TOOLS order."""
    name_set = set(names)
    return [t for t in AGENT_TOOLS if t["name"] in name_set]


ORCHESTRATOR_TOOLS = _tools("get_user_style", "search_learnings")
SLACK_TOOLS = _tools("search_memory")
OUTLOOK_TOOLS = _tools("search_memory", "get_calendar")
TEAMS_TOOLS = _tools("search_memory")
FATHOM_TOOLS = _tools("search_memory")
NOTION_TOOLS = _tools("search_memory")
CROSS_KNOWLEDGE_TOOLS = _tools("search_memory", "search_learnings", "save_learning", "get_sync_status")
TASKS_TOOLS = _tools("list_tasks", "get_calendar", "search_learnings", "save_learning")
