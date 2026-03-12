from __future__ import annotations
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai

from debate_engine.config import (
    GOOGLE_API_KEY, GEMINI_MODEL, PROMPTS_DIR, MAX_OUTPUT_TOKENS_SYNTHESIZER,
    THINKING_BUDGET_SYNTHESIZER, UNANIMOUS_CONFIDENCE_THRESHOLD,
)
from debate_engine.agents.base import BaseAgent
from debate_engine.utils import parse_llm_json

client = genai.Client(api_key=GOOGLE_API_KEY)


def _check_unanimous(perspectives: list[dict], module_context: str) -> dict | None:
    """Check if all agents agree unanimously with high confidence.

    Returns a lightweight consensus synthesis dict if unanimous, else None.
    """
    if len(perspectives) < 3:
        return None

    threshold = UNANIMOUS_CONFIDENCE_THRESHOLD

    if module_context == "red_flag":
        verdicts = [p.get("verdict") for p in perspectives]
        confidences = [p.get("confidence", 0) for p in perspectives]
        if len(set(verdicts)) == 1 and all(c >= threshold for c in confidences):
            verdict = verdicts[0]
            avg_conf = round(sum(confidences) / len(confidences), 2)
            return {
                "final_decision": verdict,
                "confidence_score": avg_conf,
                "consensus_reached": True,
                "recommended_action": (
                    "Urgent specialist review required"
                    if verdict == "RED_FLAG_PRESENT"
                    else "Proceed to pattern analysis"
                ),
                "key_arguments_for_red_flag": [
                    f.get("reasoning", "") for f in perspectives if f.get("verdict") == "RED_FLAG_PRESENT"
                ],
                "key_arguments_against_red_flag": [
                    f.get("reasoning", "") for f in perspectives if f.get("verdict") != "RED_FLAG_PRESENT"
                ],
                "key_contention_points": [],
                "synthesis_rationale": f"All {len(perspectives)} agents unanimously agreed on {verdict} with average confidence {avg_conf}. Synthesizer skipped.",
                "_short_circuited": True,
            }

    elif module_context == "pattern":
        classifications = [p.get("classification", "").upper() for p in perspectives]
        confidences = [p.get("confidence", 0) for p in perspectives]
        if len(set(classifications)) == 1 and all(c >= threshold for c in confidences):
            cls = classifications[0]
            avg_conf = round(sum(confidences) / len(confidences), 2)
            return {
                "final_classification": cls,
                "confidence_score": avg_conf,
                "consensus_reached": True,
                "recommended_action": f"Follow {cls.lower()} pathway guidelines",
                "key_arguments_for_primary": [p.get("reasoning", "") for p in perspectives],
                "key_arguments_against_primary": [],
                "key_contention_points": [],
                "synthesis_rationale": f"All {len(perspectives)} agents unanimously classified as {cls} with average confidence {avg_conf}. Synthesizer skipped.",
                "_short_circuited": True,
            }

    return None


def run_debate(
    agents: list[BaseAgent],
    patient_data: dict,
    module_context: str,
    synthesizer_prompt_file: str,
) -> dict:
    """Run a full debate loop: parallel agents → (optional) synthesizer.

    If all agents agree unanimously with high confidence, the synthesizer
    is skipped to save ~30-60s of API call time.

    Args:
        agents: List of 3 agent instances.
        patient_data: Enriched patient payload.
        module_context: 'red_flag' or 'pattern'.
        synthesizer_prompt_file: Name of the synthesizer prompt markdown file.

    Returns:
        Dict with synthesizer output + agent_perspectives + token_usage.
    """
    start_time = time.time()
    total_tokens = {"input": 0, "output": 0}
    agent_token_breakdown = {}

    # ── Phase 1: Run agents in parallel ──────────────────────────────────
    perspectives = []
    errors = []

    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_agent = {
            pool.submit(agent.analyze, patient_data, module_context): agent
            for agent in agents
        }
        for future in as_completed(future_to_agent):
            agent = future_to_agent[future]
            try:
                result = future.result()
                # Track tokens
                usage = result.pop("_token_usage", {})
                total_tokens["input"] += usage.get("input", 0)
                total_tokens["output"] += usage.get("output", 0)
                agent_token_breakdown[agent.agent_id] = usage
                perspectives.append(result)
            except Exception as e:
                errors.append({"agent_id": agent.agent_id, "error": str(e)})

    # Sort perspectives by agent_id for consistency
    perspectives.sort(key=lambda p: p.get("agent_id", ""))

    # ── Phase 1.5: Check for unanimous agreement ─────────────────────────
    unanimous = _check_unanimous(perspectives, module_context)
    if unanimous is not None:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "synthesis": unanimous,
            "agent_perspectives": perspectives,
            "errors": errors,
            "processing_metadata": {
                "model_used": GEMINI_MODEL,
                "total_agents": len(agents),
                "debate_rounds": 1,
                "short_circuited": True,
                "processing_time_ms": elapsed_ms,
                "token_usage": {
                    "input": total_tokens["input"],
                    "output": total_tokens["output"],
                    "total": total_tokens["input"] + total_tokens["output"],
                    "breakdown": agent_token_breakdown,
                },
            },
        }

    # ── Phase 2: Synthesizer (only when agents disagree) ─────────────────
    synth_prompt = (PROMPTS_DIR / synthesizer_prompt_file).read_text(encoding="utf-8")

    synth_input = (
        f"{synth_prompt}\n\n"
        f"## Agent Perspectives\n\n"
        f"```json\n{json.dumps(perspectives, indent=2)}\n```"
    )

    synth_response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[{"role": "user", "parts": [{"text": synth_input}]}],
        config={
            "max_output_tokens": MAX_OUTPUT_TOKENS_SYNTHESIZER,
            "response_mime_type": "application/json",
            "thinking_config": {"thinking_budget": THINKING_BUDGET_SYNTHESIZER},
        },
    )

    synthesis = parse_llm_json(synth_response.text)

    # Track synthesizer tokens
    synth_usage = getattr(synth_response, "usage_metadata", None)
    synth_tokens = {
        "input": getattr(synth_usage, "prompt_token_count", 0) or 0,
        "output": getattr(synth_usage, "candidates_token_count", 0) or 0,
    }
    total_tokens["input"] += synth_tokens["input"]
    total_tokens["output"] += synth_tokens["output"]
    agent_token_breakdown["synthesizer"] = synth_tokens

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "synthesis": synthesis,
        "agent_perspectives": perspectives,
        "errors": errors,
        "processing_metadata": {
            "model_used": GEMINI_MODEL,
            "total_agents": len(agents),
            "debate_rounds": 1,
            "short_circuited": False,
            "processing_time_ms": elapsed_ms,
            "token_usage": {
                "input": total_tokens["input"],
                "output": total_tokens["output"],
                "total": total_tokens["input"] + total_tokens["output"],
                "breakdown": agent_token_breakdown,
            },
        },
    }
