from __future__ import annotations
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai

logger = logging.getLogger(__name__)

from debate_engine.config import (
    GOOGLE_API_KEY, GEMINI_MODEL, PROMPTS_DIR, MAX_OUTPUT_TOKENS_SYNTHESIZER,
    THINKING_BUDGET_SYNTHESIZER, UNANIMOUS_CONFIDENCE_THRESHOLD, MODULES,
)
from debate_engine.agents.base import BaseAgent
from debate_engine.utils import parse_llm_json

client = genai.Client(api_key=GOOGLE_API_KEY)


def _check_unanimous(perspectives: list[dict], module_context: str) -> dict | None:
    """Check if all agents agree unanimously with high confidence.

    Uses module config from MODULES to determine the decision field and output keys,
    so new modules work automatically without changes here.

    Returns a lightweight consensus synthesis dict if unanimous, else None.
    """
    if len(perspectives) < 2:
        return None

    module_cfg = MODULES.get(module_context)
    if module_cfg is None:
        return None

    field = module_cfg["decision_field"]
    decision_key = module_cfg["output_decision_key"]
    args_for_key = module_cfg["output_args_for_key"]
    args_against_key = module_cfg["output_args_against_key"]
    consensus_actions = module_cfg.get("consensus_actions", {})

    threshold = UNANIMOUS_CONFIDENCE_THRESHOLD

    decisions = [p.get(field, "").upper() for p in perspectives]
    confidences = [p.get("confidence", 0) for p in perspectives]

    if len(set(decisions)) != 1 or not all(c >= threshold for c in confidences):
        return None

    decision = decisions[0]
    avg_conf = round(sum(confidences) / len(confidences), 2)

    # Resolve recommended action from config
    action = consensus_actions.get(
        decision,
        consensus_actions.get("_default", ""),
    ).format(decision=decision.lower())

    return {
        decision_key: decision,
        "confidence_score": avg_conf,
        "consensus_reached": True,
        "recommended_action": action,
        args_for_key: [
            p.get("reasoning", "") for p in perspectives
            if p.get(field, "").upper() == decision
        ],
        args_against_key: [
            p.get("reasoning", "") for p in perspectives
            if p.get(field, "").upper() != decision
        ],
        "key_contention_points": [],
        "synthesis_rationale": (
            f"All {len(perspectives)} agents unanimously agreed on {decision} "
            f"with average confidence {avg_conf}. Synthesizer skipped."
        ),
        "_short_circuited": True,
    }


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
                logger.error("Agent %s failed: %s", agent.agent_id, e, exc_info=True)
                errors.append({"agent_id": agent.agent_id, "error": str(e)})

    # Sort perspectives by agent_id for consistency
    perspectives.sort(key=lambda p: p.get("agent_id", ""))
    logger.info(
        "Debate [%s]: %d/%d agents succeeded%s",
        module_context, len(perspectives), len(agents),
        f", {len(errors)} failed: {[e['agent_id'] for e in errors]}" if errors else "",
    )

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
            "temperature": 0,
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
