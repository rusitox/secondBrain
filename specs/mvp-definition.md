# MVP Definition: AI Chief of Staff

## 🎯 MVP Objective
Create a "Proactive Memory Assistant" that connects professional interaction data from multiple sources to prevent information loss, manage commitments, and provide instant context.

## 📦 MVP Scope: Ingestion & Sources
The MVP will integrate the following data sources (text-only):
- **Microsoft Outlook:** Emails and Calendar events.
- **Slack:** Direct messages and channel conversations.
- **Microsoft Teams:** Chat history.
- **Fathom:** Meeting transcripts (existing text).

## ✨ Core MVP Features

### 1. Proactive Commitment Tracking
- **Detection:** Automatically identify promises/commitments in the ingested text (e.g., "I'll send the file by Friday").
- **Tracking:** Maintain a structured list of "Open Commitments".
- **Reminders:** Notify the user via a Daily Briefing if a commitment remains unfulfilled.

### 2. The Daily Briefing
A morning summary delivered via chat containing:
- **Agenda:** Today's meetings and key participants.
- **Priority Pendings:** Critical promises or answers pending from the previous days.
- **Contextual Alerts:** "You have a call with X; remember you promised them Y in a Slack message yesterday."

### 3. Cross-Platform Context Querying
- Ability to ask complex questions that span multiple sources:
  - *Example:* "What was the final agreement on the budget considering the last few emails and the Fathom transcript from Wednesday?"

## 🛠️ Technical Architecture & Viability

### Data Pipeline
- **Microsoft Graph API:** Unified access for Outlook and Teams Chat. Requires Azure AD App Registration.
- **Slack API:** Standard Bot tokens for reading messages.
- **Fathom Integration:** API-based ingestion or import of exported text transcripts.

### Memory & Retrieval (RAG)
- **Vector Database:** Use of a vector DB (e.g., Pinecone, ChromaDB) to store embeddings of all interactions.
- **Retrieval Augmented Generation (RAG):** 
  - User query $\rightarrow$ Embedding $\rightarrow$ Vector Search $\rightarrow$ Top-K fragments $\rightarrow$ LLM $\rightarrow$ Final Answer.
- **Knowledge Graph:** A light layer to map the relationship: `Person <-> Project <-> Channel`.

### Interface
- **Initial Phase:** A clean chat interface (Web/App) for interaction and receiving the Daily Briefing.

## 📖 Key User Stories

1. **The Promise Guard:** "As a user, I want the assistant to detect when I make a commitment in any channel and remind me the next morning if it's not done."
2. **The Unified Summary:** "As a user, I want to ask 'What's the status of X?' and get a summary that combines data from Slack, Mail, and Teams without searching manually."
3. **The Meeting Prep:** "As a user, I want a summary of the last 3 interactions with a person before I start a meeting with them."
