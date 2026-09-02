"""Anthropic tool definitions for the agent loop.

Each entry follows the Anthropic tool-use JSON schema format.
The tool_executors dict in AgentOrchestrator maps these names to callables.
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
            "Returns tasks with priority, owner, due date, and status."
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
            "Get the user's upcoming calendar events for today (events not yet started). "
            "Returns meeting subjects, start times, organizers, and attendees. "
            "Use this to answer questions like 'what meetings do I have left?' or 'what's next on my calendar?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
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
