# Memory Logic: The RAG Cycle

## 1. The Extraction Loop (The Writer)
Input Message $\rightarrow$ LLM Extraction Engine $\rightarrow$ "Is this a fact?" $\rightarrow$ Yes $\rightarrow$ Embed $\rightarrow$ Store in pgvector.

## 2. The Retrieval Loop (The Reader)
User Query $\rightarrow$ Embed Query $\rightarrow$ Vector Search (Cosine Distance) $\rightarrow$ Top K Results $\rightarrow$ Context String.

## 3. The Generation Loop (The Brain)
Context String + User Query + System Persona $\rightarrow$ LLM $\rightarrow$ Personalized Response.

## 4. The Synthesis Loop (Optimization)
Periodic review of raw logs $\rightarrow$ Merge duplicate memories $\rightarrow$ Update outdated facts $\rightarrow$ Refine KnowledgeItems.
