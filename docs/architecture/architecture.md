# High-Level Architecture: Digital Twin Assistant

## Overview
The Digital Twin is a personalized AI assistant that acts as a semantic mirror of the user. It doesn't just process queries; it maintains a dynamic, evolving long-term memory of the user's preferences, goals, and knowledge.

## Core Philosophy
- **Proactive Learning**: The system extracts facts from conversations automatically.
- **Semantic Retrieval**: Use of vector embeddings to find context based on meaning, not keywords.
- **Augmented Intelligence**: LLM responses are always grounded in retrieved user-specific context (RAG).

## Component Stack
- **API**: FastAPI (Async, high performance).
- **Memory Store**: PostgreSQL + pgvector (Supabase).
- **LLM**: Claude 3.5 / GPT-4o.
- **Embeddings**: OpenAI `text-embedding-3-small`.
- **Orchestration**: Custom MemoryManager (RAG loop).
