"""
SVG Dashboard Service - Bridge between main app and dynamic_svg module.

Handles sys.path setup, workflow invocation, and result management
for the dynamic_svg MASH clinical dashboard generation pipeline.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any

# Ensure dynamic_svg is importable
_DYNAMIC_SVG_DIR = str(Path(__file__).resolve().parent.parent.parent / "dynamic_svg")
if _DYNAMIC_SVG_DIR not in sys.path:
    sys.path.insert(0, _DYNAMIC_SVG_DIR)


async def generate_svg_dashboard(
    patient_data: dict[str, Any],
    analysis_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run the full MASH SVG workflow on patient data.

    Args:
        patient_data: The extractionRecord (PatientRecord format)
                      with keys: patient, sections, extraction_metadata
        analysis_results: Optional debate engine output containing
                         risk_factors, red_flag, pattern_analysis

    Returns:
        Dictionary with svg_code, metadata, and timing info
    """
    from dynamic_svg.workflow_parallel import build_mash_workflow
    from dynamic_svg.core.state_manager import StateManager

    start_time = time.time()

    # The workflow expects raw_patient_data as a list of dicts.
    # If patient_data is a single record, wrap it.
    if isinstance(patient_data, dict):
        raw_data = [patient_data]
    else:
        raw_data = patient_data

    # Initialize LangGraph state (with optional analysis results)
    initial_state = StateManager.initialize_state(raw_data, analysis_results)

    # Build and run the workflow (synchronous, runs in thread)
    import asyncio
    loop = asyncio.get_event_loop()

    def _run_workflow():
        app = build_mash_workflow()
        return app.invoke(initial_state)

    final_state = await loop.run_in_executor(None, _run_workflow)

    elapsed = time.time() - start_time

    # Extract results
    svg_code = final_state.get("final_svg", "")
    approval_status = final_state.get("approval_status", "Unknown")
    loop_count = final_state.get("loop_count", 0)
    dashboard_image = final_state.get("dashboard_image")

    return {
        "svg_code": svg_code,
        "approval_status": approval_status,
        "loop_count": loop_count,
        "dashboard_image": dashboard_image,
        "svg_size_chars": len(svg_code),
        "execution_time_seconds": round(elapsed, 2),
    }

