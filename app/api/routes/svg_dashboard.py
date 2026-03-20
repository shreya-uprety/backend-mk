"""
SVG Dashboard API routes.

Endpoints for generating MASH clinical SVG dashboards
from patient extraction records.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/svg-dashboard", tags=["svg-dashboard"])


@router.post("/generate/{patient_id}")
async def generate_from_gcs(patient_id: str):
    """
    Generate SVG dashboard for a patient using their record.json from GCS.

    Reads pipeline_output/{patient_id}/record.json from GCS,
    runs the full MASH SVG workflow, and returns the result.
    """
    from app.services.gcs import download_json

    # Read the extraction record from GCS
    gcs_path = f"pipeline_output/{patient_id}/record.json"
    try:
        patient_data = download_json(gcs_path)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Patient record not found at {gcs_path}: {e}",
        )

    from app.services.svg_dashboard_service import generate_svg_dashboard

    result = await generate_svg_dashboard(patient_data)

    return {
        "patient_id": patient_id,
        **result,
    }


@router.post("/generate")
async def generate_from_json(body: dict):
    """
    Generate SVG dashboard from a raw JSON body.

    Accepts either:
      1. Combined payload: { extraction_record: {...}, analysis_results: {...} }
      2. Raw extractionRecord directly (backward compatible)
    """
    from app.services.svg_dashboard_service import generate_svg_dashboard

    if not body:
        raise HTTPException(status_code=400, detail="Request body cannot be empty")

    # Check if it's the combined payload format
    if "extraction_record" in body:
        patient_data = body["extraction_record"]
        analysis_results = body.get("analysis_results")
    else:
        # Backward compatible: treat entire body as patient data
        patient_data = body
        analysis_results = None

    result = await generate_svg_dashboard(patient_data, analysis_results)
    return result


@router.post("/generate/{patient_id}/svg")
async def generate_svg_only(patient_id: str):
    """
    Generate and return only the SVG content (as image/svg+xml).

    Useful for embedding directly in <img> tags or iframes.
    """
    from app.services.gcs import download_json
    from app.services.svg_dashboard_service import generate_svg_dashboard

    gcs_path = f"pipeline_output/{patient_id}/record.json"
    try:
        patient_data = download_json(gcs_path)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Patient record not found: {e}",
        )

    result = await generate_svg_dashboard(patient_data)

    return Response(
        content=result["svg_code"],
        media_type="image/svg+xml",
    )
