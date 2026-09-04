---
name: Multi-agent architecture plan
description: Decisiones clave del rediseño de AgentOrchestrator hacia arquitectura multi-agente con 7 agentes especializados
type: project
---

Plan en specs/plan-multi-agent-architecture.md. Status: diseñado, pendiente de review.

**Key architectural decisions:**

1. Sub-agentes son funciones Python async, NO tools de Anthropic tool-use. Razón: permite asyncio.gather() para paralelismo real; sub-agentes como tools serían secuenciales y carísimos en tokens.

2. OrchestratorAgent hace UNA sola llamada LLM para síntesis final, con el output de los sub-agentes inyectado como contexto en el mensaje de usuario. Solo tiene 3 tools propios: get_user_style, search_learnings, save_learning.

3. Routing por palabras clave (AgentRouter.route()) — no LLM intent classification. Default: solo CrossKnowledgeAgent si no hay match específico.

4. El flujo de confirmación de tasks es stateless: TasksAgent hace preguntas en su output, la respuesta llega en el siguiente turn de ConversationTurn. No hay nueva tabla ni campo de estado.

5. agent.py queda como thin shim (backward compat). MultiAgentOrchestrator vive en orchestrator.py. El endpoint /agent/query no cambia.

6. No nuevas tablas DB, no nuevos campos, no nuevos paquetes — consistente con decisión de plan-intelligent-learning.

7. Escape hatch: MULTI_AGENT_ENABLED env var para volver al single-agent si hay problemas de costo/latencia.

**Why:** Mariano quiere que el sistema aprenda ownership activamente, correlacione info entre plataformas, y maneje confirmación de tasks sin asumir.

**How to apply:** Al implementar cualquier agente nuevo, seguir el contrato BaseSubAgent.run() → SubAgentResult. Los sub-agentes no persisten ConversationTurn. Solo el orquestador persiste.
