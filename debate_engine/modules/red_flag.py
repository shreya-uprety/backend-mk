"""Module A: Red Flag Determinator.

Runs a 3-agent debate loop to determine if red flag symptoms are present.
"""
from __future__ import annotations
from datetime import datetime, timezone

from debate_engine.agents.registry import create_agents, get_module_config
from debate_engine.orchestrator import run_debate
from debate_engine.schemas import (
    PatientPayload, RedFlagResponse, RedFlagDebateSummary,
    RedFlagVoteTally, AgentPerspective, DebateProcessingMetadata, TokenUsage,
)


def analyze_red_flags(payload: PatientPayload) -> RedFlagResponse:
    """Run the red flag debate loop."""
    module_context = "red_flag"
    module_cfg = get_module_config(module_context)
    agents = create_agents(module_context)
    patient_data = payload.model_dump()

    result = run_debate(
        agents=agents,
        patient_data=patient_data,
        module_context=module_context,
        synthesizer_prompt_file=module_cfg["synthesizer_prompt"],
    )

    synthesis = result["synthesis"]
    perspectives = result["agent_perspectives"]
    meta = result["processing_metadata"]

    # ── Build vote tally ─────────────────────────────────────────────────
    yes_count = sum(1 for p in perspectives if p.get("verdict") == "RED_FLAG_PRESENT")
    no_count = len(perspectives) - yes_count

    # ── Build agent perspectives ─────────────────────────────────────────
    agent_persp = [
        AgentPerspective(
            agent_id=p["agent_id"],
            agent_persona=p["agent_persona"],
            verdict=p.get("verdict", "UNKNOWN"),
            confidence=p.get("confidence", 0.5),
            reasoning=p.get("reasoning", ""),
            key_factors_cited=p.get("key_factors_cited", []),
        )
        for p in perspectives
    ]

    debate_summary = RedFlagDebateSummary(
        consensus_reached=synthesis.get("consensus_reached", yes_count == 0 or no_count == 0),
        vote_tally=RedFlagVoteTally(red_flag_present=yes_count, no_red_flag=no_count),
        key_arguments_for_red_flag=synthesis.get("key_arguments_for_red_flag", []),
        key_arguments_against_red_flag=synthesis.get("key_arguments_against_red_flag", []),
        key_contention_points=synthesis.get("key_contention_points", []),
        synthesis_rationale=synthesis.get("synthesis_rationale", ""),
        agent_perspectives=agent_persp,
    )

    token_data = meta["token_usage"]

    return RedFlagResponse(
        scenario_id=payload.scenario_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        final_decision=synthesis.get("final_decision", "NO_RED_FLAG"),
        confidence_score=synthesis.get("confidence_score", 0.5),
        recommended_action=synthesis.get("recommended_action", ""),
        debate_summary=debate_summary,
        processing_metadata=DebateProcessingMetadata(
            model_used=meta["model_used"],
            total_agents=meta["total_agents"],
            debate_rounds=meta["debate_rounds"],
            processing_time_ms=meta["processing_time_ms"],
            token_usage=TokenUsage(
                input=token_data["input"],
                output=token_data["output"],
                total=token_data["total"],
            ),
        ),
    )
