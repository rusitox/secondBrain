# Technical Architecture: AI Chief of Staff

## 🛠️ Technology Stack

- **Language:** Python 3.11+
- **Orchestration:** LangChain
- **Embeddings:** OpenAI (`text-embedding-3-small` or `large`)
- **Vector Database:** Supabase (pgvector)
    - *Decision:* Supabase is preferred over Pinecone because this project requires both **Vector Search** (for semantic memory) and **Relational Data** (for tracking commitments, tasks, and user profiles). Having both in one place simplifies the architecture.
- **LLM:** Claude 3.5 Sonnet (via API) for high-reasoning and ghostwriting.
- **API Framework:** FastAPI (for the backend and integration hooks).

---

## 🏗️ System Architecture

### 1. Data Ingestion Pipeline (The Intake)
The system uses a modular connector architecture to ingest text from multiple sources:

- **Connectors:**
    - `MSGraphConnector`: Handles OAuth2 flow for Outlook (Emails and Calendar events).
    - `TeamsConnector`: Handles Microsoft Teams chat messages (1:1 and group chats) via MS Graph API with rate limiting and retry.
    - `SlackConnector`: Uses Bot Tokens to read channels and DMs with cursor pagination and rate limit handling.
    - `FathomConnector`: Processes meeting transcripts via Fathom API.
- **Processing Flow:**
    - **Cleaning:** Remove noise (signatures, boilerplate).
    - **Chunking:** Use `RecursiveCharacterTextSplitter` from LangChain to split long transcripts/emails into semantic chunks (approx. 500-1000 tokens).
    - **Embedding:** Convert chunks into vectors using OpenAI Embeddings.
    - **Storage:** Upsert to Supabase `documents` table with metadata (source, timestamp, author, project_id).

### 2. Memory & Retrieval Layer (The Brain)
Implementing a **Hybrid Search** strategy to ensure accuracy:

- **Semantic Search:** Vector search via `pgvector` to find conceptually related information.
- **Metadata Filtering:** Ability to filter by date range or specific person (e.g., "Find mentions of 'Budget' only in the last 7 days").
- **Knowledge Graph (Light):** A relational table in Supabase mapping `Entity A` $\rightarrow$ `Relationship` $\rightarrow$ `Entity B` (e.g., "John Doe" is the "Project Lead" of "Project X").

### 3. The Agentic Core (The Logic)
The system operates as an agent with access to specialized **Tools**:

- **Tool A: Memory Retriever:** Searches the vector DB for context.
- **Tool B: Task Manager:** Reads/Writes to the "Open Commitments" relational table.
- **Tool C: Calendar Sync:** Checks for upcoming meetings.
- **Tool D: Style Analyzer:** Retrieves a "Style Guide" document containing examples of the user's tone and heuristics.

**The Proactive Loop:**
A cron job (via FastAPI/Celery) triggers the "Daily Briefing" agent every morning. It:
1. Checks the calendar for the day.
2. Queries the Task Manager for pending commitments.
3. Synthesizes a "Daily Briefing" and pushes it to the interface.

---

## 🔄 Data Flow Diagram

`Sources (Slack/Outlook/Teams/Fathom)` $\rightarrow$ `FastAPI Ingestion` $\rightarrow$ `OpenAI Embeddings` $\rightarrow$ `Supabase (pgvector)`

`User Query / Cron Trigger` $\rightarrow$ `LangChain Agent` $\rightarrow$ `Retrieve Context (Supabase)` $\rightarrow$ `Claude 3.5 Sonnet` $\rightarrow$ `Response / Briefing`

---

## 🛡️ Security & Privacy
- **Encryption:** Data encrypted at rest in Supabase.
- **OAuth2:** Using standard authorization flows; the system never stores raw passwords.
- **PII Filtering:** Option to implement a regex-based filter to prevent sensitive data (passwords, credit cards) from being embedded and stored.
