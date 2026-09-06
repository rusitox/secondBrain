"""Shared scoped-Swarm negotiation core.

One negotiation mechanism, two triggers: domain_agent.ask_peer_agents uses
this proactively (an agent has a doubt about one entity), and
reconciliation.negotiate_same_as uses it reactively (a batch scan flagged a
candidate cross-source duplicate). Previously each reimplemented the same
Agent/Swarm construction + invoke + exception handling — a fix or tuning
change (e.g. lowering max_handoffs after observing runaway swarms) applied
to one copy wouldn't have applied to the other. Now there's one copy.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_HANDOFFS = 6
MAX_ITERATIONS = 6


async def run_negotiation(node_specs: List[Dict[str, Any]], task: str, log_context: str) -> None:
    """Build one Agent per spec and run them as a scoped Swarm.

    Args:
        node_specs: One dict per negotiator — {"name": str, "system_prompt":
            str, "tools": [...]}. Each caller supplies its own tools (e.g.
            view_claims scoped differently, plus its own verdict tool) since
            that's the part that's genuinely different between callers; only
            the Agent/Swarm scaffold itself is shared here.
        task: The question posed to the swarm's entry point (first spec).
        log_context: Short label for the exception log line (e.g. the
            calling function's name) so a failure is traceable to its trigger.

    The verdict itself is never returned by this function — callers capture
    it via a closure-based tool (e.g. submit_verdict) passed in `node_specs`,
    since Swarm itself has no structured return value for "what did the
    group conclude." A crashed or non-converging negotiation just leaves
    that closure at its default; callers treat that as "couldn't resolve,"
    not as an exception to propagate.
    """
    from strands import Agent
    from strands.multiagent import Swarm
    from strands.tools.executors import SequentialToolExecutor

    from app.services.agent.strands_model import build_openai_model

    model = build_openai_model()
    nodes = [
        Agent(
            model=model,
            tools=spec["tools"],
            system_prompt=spec["system_prompt"],
            name=spec["name"],
            tool_executor=SequentialToolExecutor(),
        )
        for spec in node_specs
    ]

    swarm = Swarm(nodes, max_handoffs=MAX_HANDOFFS, max_iterations=MAX_ITERATIONS)
    try:
        await swarm.invoke_async(task)
    except Exception:
        logger.exception("%s: swarm negotiation failed", log_context)
