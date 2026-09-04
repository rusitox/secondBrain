---
name: Intelligent Learning Agent plan
description: Plan para evolucionar el agente a aprendizaje activo de ownership, cross-platform correlation, y welcome que pregunta en lugar de reportar
type: project
---

Plan en specs/plan-intelligent-learning.md. Secuencia: Phase 1 (ownership questioning via system prompt) → Phase 2 (welcome redesign) → Phase 5 (cross-platform correlation) → Phase 3A (conectar LearningExtractor al pipeline) → Phase 3B (ampliar EXTRACTION_INSTRUCTIONS) → Phase 4 (commitment detector ownership signal).

**Why:** Mariano quiere que el sistema aprenda activamente quién es dueño de cada commitment, que nunca asuma sino que pregunte y guarde la respuesta como learning, y que el welcome sea una oportunidad de aprendizaje, no un dump de tareas.

**Key decisions:**
- No se agrega confidence_score al modelo Commitment — todo el ownership resuelto vive en memories
- No se crea tool correlate_topics — se instruye al agente a hacer múltiples search_memory calls
- LearningExtractor existe en código pero no está conectado al pipeline (Phase 3A lo activa)
- Phases 1+2+5 son cambios de texto puro, sin riesgo de regresión, máximo impacto inmediato
- owner="unknown" y owner="speaker" son los triggers de ownership ambiguity que el agente ya puede usar hoy

**How to apply:** Al planear cualquier feature que toque el agente, el welcome, o el pipeline de ingestion, tener en cuenta que este plan ya decidió no tocar el schema de DB ni crear nuevos tools.
