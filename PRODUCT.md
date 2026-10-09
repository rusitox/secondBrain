# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user: a busy professional (knowledge worker, exec, or founder) who wants a personal "Chief of Staff" watching their communications across platforms so nothing falls through the cracks. The project's first and current user is Mariano, running his own instance.

The architecture is deliberately built so other professionals can self-host their own private instance too (per-user accounts, bcrypt-hashed API keys, a remote-only CLI install path, an automated local installer) — this is not a shared multi-tenant SaaS, it's "one instance per person, run it yourself."

## Product Purpose

secondBrain ingests a user's professional communications (email, chat, meeting transcripts, Notion docs) into a personal knowledge base, tracks commitments made in that communication (promises, deadlines, action items), generates daily briefings, and answers natural-language questions across all of it via RAG — all from a terminal chat interface, with a web chat UI, a voice UI, and an admin/backoffice UI as secondary surfaces.

Success looks like: the user never has to manually re-read scattered threads to remember what they promised someone, what's overdue, or what happened in a meeting — the system already knows and either tells them proactively (briefing, alert) or answers on demand.

## Positioning

Not a reactive RAG chatbot you query on demand — a proactive "digital twin" that:

- learns the user's behavior, priorities, and communication style over time;
- maintains contextual awareness of the "current state" of any relationship or project across every connected platform, catching gaps/contradictions between channels;
- resolves its own doubts internally first. A per-source multi-agent knowledge system (one domain agent per platform) proposes facts into a shared knowledge graph and works through a resolution ladder — consult the existing knowledge base, negotiate with peer agents — before ever interrupting the human; the human is asked only as a last resort, and even then the agent carries a candidate answer.

This "ask-the-human-last" posture, combined with treating every connected platform as one coherent personal graph instead of N separate inboxes, is the mechanism a plain RAG-over-your-docs chatbot does not have.

## Operating Context

- Primary interaction is a terminal CLI chat loop (`cli/`) with slash commands (briefing, commitments, sync, notion, digest, prep, server, etc.) and natural-language queries routed to the agent.
- Secondary surfaces are three separate web UIs served as static builds off the FastAPI backend: a Svelte SPA chat UI (internal codename "MAREA", currently mid-redesign toward a "Liquid UI" + generative-UI protocol), a voice UI, and a backoffice/admin UI for observing and configuring the knowledge-agent system (runs, traces, per-agent config, MCP servers).
- Data sources connected per user: Outlook (email + calendar), Teams (1:1/group chat), Slack, Fathom (meeting transcripts), Notion (pages + databases) — each via its own connector and, for the knowledge system, its own domain agent.
- Deployment is self-hosted: Docker Compose + Postgres/pgvector, deployed to a VPS (e.g. Oracle Cloud) the user controls, or run locally. CI builds and pushes images to GHCR on every push to `main`.
- Notion is also a one-way-out surface: commitments, daily briefings, weekly digests, and meeting prep can be bidirectionally synced to / published into the user's own Notion workspace.

## Capabilities and Constraints

- Backend: FastAPI (async), SQLAlchemy 2.0 async ORM, PostgreSQL + pgvector, OpenAI embeddings, Claude (Anthropic) for reasoning/commitment-detection/briefings, AWS Strands Agents for the tool-use/multi-agent orchestration.
- Auth: per-user API keys (`sb_` prefix, bcrypt-hashed), Bearer token auth; integration tokens are Fernet-encrypted at rest.
- Backend must stay Python 3.8+ compatible (no modern-only syntax).
- The knowledge-agent system and its scheduler are opt-in and cost real LLM calls per cycle — not enabled by default.
- Terminology: a "commitment" is a detected promise/deadline/action item; a "briefing" is the daily summary; a "digest" is the weekly Notion summary; the "knowledge graph" holds entities/claims proposed by per-source "domain agents"; a "pending question" is something a domain agent couldn't resolve internally and escalated.
- Undecided: no committed visual identity for any of the three web surfaces yet — MAREA's "Liquid UI" redesign is in progress, not finalized.

## Evidence on Hand

None. No real customer testimonials, case studies, press, or usage benchmarks exist — this is a personal/self-hosted tool, not a marketed product with outside customers yet. Future design or marketing work must not fabricate any of these.

## Product Principles

1. **Proactive, not reactive.** Surface problems and answers before being asked (briefings, alerts, gap detection) rather than waiting for a query.
2. **Resolve ambiguity internally before asking the human.** Agents consult the knowledge base and negotiate with peer agents first; the human is the last resort, and is handed a candidate answer, not an open question.
3. **One coherent graph, not N inboxes.** Every connected platform feeds a single personal knowledge graph and briefing, not siloed per-source views.
4. **Privacy-first, self-hosted.** The user runs and owns their own instance and data; tokens/secrets are encrypted at rest; no third-party data sharing beyond platforms the user explicitly connects.
5. **Self-hostable by design, not just by Mariano.** Multi-user plumbing (accounts, API keys, remote CLI, installer) exists so another professional could run their own private instance, even though the current and founding user is Mariano.
