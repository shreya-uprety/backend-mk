"""Module B: LFT Pattern Analyzer.

Runs a 3-agent debate loop to classify the LFT pattern.
"""
from __future__ import annotations
from datetime import datetime, timezone

from debate_engine.agents.safety_net import SafetyNetPattern
from debate_engine.agents.guideline import GuidelinePattern
from debate_engine.agents.statistician import StatisticianPattern
from debate_engine.orchestrator import run_debate
from debate_engine.schemas import (
    PatientPayload, PatternAnalysisResponse, PatternDebateSummary,
    PatternVoteTally, AgentPerspective, DebateProcessingMetadata,
    RFactor, TokenUsage,
)
from debate_engine.config import ULN


def analyze_pattern(payload: PatientPayload) -> PatternAnalysisResponse:
    """Run the LFT pattern debate loop."""
    agents = [SafetyNetPattern(), GuidelinePattern(), StatisticianPattern()]
    patient_data = payload.model_dump()

    result = run_debate(
        agents=agents,
        patient_data=patient_data,
        module_context="pattern",
        synthesizer_prompt_file="pattern_synthesizer.md",
    )

    synthesis = result["synthesis"]
    perspectives = result["agent_perspectives"]
    meta = result["processing_metadata"]

    # ── Build vote tally ─────────────────────────────────────────────────
    tally = {"cholestatic": 0, "hepatitic": 0, "mixed": 0}
    for p in perspectives:
        cls = (p.get("classification") or "mixed").lower()
        if cls in tally:
            tally[cls] += 1
        else:
            tally["mixed"] += 1

    # ── Build agent perspectives ─────────────────────────────────────────
    agent_persp = [
        AgentPerspective(
            agent_id=p["agent_id"],
            agent_persona=p["agent_persona"],
            classification=p.get("classification", "UNKNOWN"),
            confidence=p.get("confidence", 0.5),
            reasoning=p.get("reasoning", ""),
            key_factors_cited=p.get("key_factors_cited", []),
        )
        for p in perspectives
    ]

    debate_summary = PatternDebateSummary(
        consensus_reached=synthesis.get("consensus_reached", False),
        vote_tally=PatternVoteTally(**tally),
        key_arguments_for_primary=synthesis.get("key_arguments_for_primary", []),
        key_arguments_against_primary=synthesis.get("key_arguments_against_primary", []),
        key_contention_points=synthesis.get("key_contention_points", []),
        synthesis_rationale=synthesis.get("synthesis_rationale", ""),
        agent_perspectives=agent_persp,
    )

    # ── R-factor from derived_metrics or compute ─────────────────────────
    if payload.derived_metrics and "r_factor" in payload.derived_metrics:
        rf = payload.derived_metrics["r_factor"]
        r_factor = RFactor(
            value=rf.get("value", 0),
            formula=rf.get("formula", ""),
            zone=rf.get("zone", "mixed"),
        )
    else:
        labs = payload.lft_blood_results
        alt_uln = round(labs.ALT_IU_L / ULN["ALT"], 2)
        alp_uln = round(labs.ALP_IU_L / ULN["ALP"], 2)
        r_val = round(alt_uln / alp_uln, 2) if alp_uln > 0 else 0
        zone = "cholestatic" if r_val < 2 else ("hepatitic" if r_val > 5 else "mixed")
        r_factor = RFactor(value=r_val, formula=f"{alt_uln} / {alp_uln}", zone=zone)

    token_data = meta["token_usage"]

    return PatternAnalysisResponse(
        scenario_id=payload.scenario_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        final_classification=synthesis.get("final_classification", "MIXED"),
        confidence_score=synthesis.get("confidence_score", 0.5),
        r_factor=r_factor,
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
