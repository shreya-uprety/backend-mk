"""Agent registry — creates agent instances from module config.

To add a new agent to a module, add an entry to MODULES in config.py
and create the corresponding prompt file. No code changes needed.
"""
from __future__ import annotations

from debate_engine.config import MODULES, PROMPTS_DIR
from debate_engine.agents.base import BaseAgent


def create_agents(module_context: str) -> list[BaseAgent]:
    """Create agent instances for a given module context from config."""
    if module_context not in MODULES:
        raise ValueError(
            f"Unknown module context: {module_context}. "
            f"Available: {list(MODULES.keys())}"
        )

    module_cfg = MODULES[module_context]
    return [
        BaseAgent(
            agent_id=a["id"],
            agent_persona=a["persona"],
            prompt_path=PROMPTS_DIR / a["prompt"],
        )
        for a in module_cfg["agents"]
    ]


def get_module_config(module_context: str) -> dict:
    """Get the full configuration for a module context."""
    if module_context not in MODULES:
        raise ValueError(
            f"Unknown module context: {module_context}. "
            f"Available: {list(MODULES.keys())}"
        )
    return MODULES[module_context]
