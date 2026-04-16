"""Prompt templates for RAG queries."""
from typing import Any, Dict, List

RAG_SYSTEM_PROMPT = """You are a personal AI assistant acting as a "Second Brain" \
for the user. Your role is to answer questions based ONLY on the context provided \
from the user's personal knowledge base (emails, meetings, messages, notes).

Rules:
- Answer ONLY based on the provided context. Do not use prior knowledge.
- If the context does not contain enough information to answer, say so clearly.
- Cite your sources: mention the platform (email, slack, calendar, fathom) and \
relevant metadata (author, date, subject) when referencing information.
- Be concise and direct. The user values actionable answers.
- If the question is about commitments or action items, highlight deadlines and owners.
- Respond in the same language as the user's question."""


def build_context_block(sources: List[Dict[str, Any]]) -> str:
    """Build the context block from search results for the RAG prompt.

    Each source is a dict with: content, source, metadata, similarity.
    """
    if not sources:
        return "(No relevant documents found in your knowledge base.)"

    blocks = []
    for i, src in enumerate(sources, 1):
        meta = src.get("metadata", {})
        header_parts = [f"[Source {i}]"]
        header_parts.append(f"Platform: {src.get('source', 'unknown')}")
        if meta.get("author"):
            header_parts.append(f"From: {meta['author']}")
        if meta.get("subject"):
            header_parts.append(f"Subject: {meta['subject']}")
        if meta.get("timestamp"):
            header_parts.append(f"Date: {meta['timestamp']}")
        if meta.get("channel"):
            header_parts.append(f"Channel: #{meta['channel']}")

        header = " | ".join(header_parts)
        blocks.append(f"{header}\n{src['content']}")

    return "\n\n---\n\n".join(blocks)


def format_rag_prompt(question: str, sources: List[Dict[str, Any]]) -> str:
    """Format the full user message for the RAG query.

    Uses string concatenation instead of str.format() to avoid
    crashes from curly braces in user input or document content.
    """
    context = build_context_block(sources)
    return (
        "Context from your personal knowledge base:\n\n"
        + context
        + "\n\n---\n\nQuestion: "
        + question
    )
