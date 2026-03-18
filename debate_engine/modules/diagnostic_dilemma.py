"""Module C: Diagnostic Dilemma Assessment.

Runs a 3-agent debate loop to determine if the case is complex
(requiring MDT escalation) or straightforward.
"""
from __future__ import annotations
from datetime import datetime, timezone

from debate_engine.agents.registry import create_agents, get_module_config
from debate_engine.orchestrator import run_debate
from debate_engine.schemas import (
    PatientPayload, AgentPerspective, DebateProcessingMetadata, TokenUsage,
)


def assess_dilemma(payload: PatientPayload, extra_context: dict | None = None) -> dict:
    """Run the diagnostic dilemma debate loop.

    Returns a dict with final_decision, confidence_score, debate_summary, etc.
    """
    module_context = "dilemma"
    module_cfg = get_module_config(module_context)
    agents = create_agents(module_context)

    patient_data = payload.model_dump()
    if extra_context:
        patient_data["_extra_context"] = extra_context

    result = run_debate(
        agents=agents,
        patient_data=patient_data,
        module_context=module_context,
        synthesizer_prompt_file=module_cfg["synthesizer_prompt"],
    )

    synthesis = result["synthesis"]
    perspectives = result["agent_perspectives"]
    meta = result["processing_metadata"]

    # Build vote tally
    yes_count = sum(1 for p in perspectives if p.get("verdict") == "DIAGNOSTIC_DILEMMA")
    no_count = len(perspectives) - yes_count

    agent_persp = [
        {
            "agent_id": p["agent_id"],
            "agent_persona": p["agent_persona"],
            "verdict": p.get("verdict", "UNKNOWN"),
            "confidence": p.get("confidence", 0.5),
            "reasoning": p.get("reasoning", ""),
            "key_factors_cited": p.get("key_factors_cited", []),
        }
        for p in perspectives
    ]

    token_data = meta["token_usage"]

    return {
        "module": "diagnostic_dilemma",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "final_decision": synthesis.get("final_decision", "NO_DILEMMA"),
        "confidence_score": synthesis.get("confidence_score", 0.5),
        "complexity_factors": synthesis.get("complexity_factors", []),
        "recommended_action": synthesis.get("recommended_action", ""),
        "debate_summary": {
            "consensus_reached": synthesis.get("consensus_reached", False),
            "vote_tally": {"dilemma_present": yes_count, "no_dilemma": no_count},
            "key_arguments_for_dilemma": synthesis.get("key_arguments_for_dilemma", []),
            "key_arguments_against_dilemma": synthesis.get("key_arguments_against_dilemma", []),
            "key_contention_points": synthesis.get("key_contention_points", []),
            "synthesis_rationale": synthesis.get("synthesis_rationale", ""),
            "agent_perspectives": agent_persp,
        },
        "processing_metadata": {
            "model_used": meta["model_used"],
            "total_agents": meta["total_agents"],
            "debate_rounds": meta["debate_rounds"],
            "processing_time_ms": meta["processing_time_ms"],
            "token_usage": token_data,
        },
    }
