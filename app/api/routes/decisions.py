from fastapi import APIRouter, HTTPException, Request

from debate_engine.schemas import (
    PatientPayload, RiskFactorResponse, RedFlagResponse, PatternAnalysisResponse,
)
from debate_engine.modules.risk_factor_extractor import extract_risk_factors
from debate_engine.modules.red_flag import analyze_red_flags
from debate_engine.modules.pattern_analysis import analyze_pattern
from debate_engine.modules.record_transformer import transform_record_to_payload
from debate_engine.rate_limiter import (
    check_rate_limit, record_request, record_tokens, record_failure,
)

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])


@router.post("/extract-risk-factors", response_model=RiskFactorResponse)
async def extract_risk_factors_endpoint(payload: PatientPayload):
    """Module 0: Extract and classify risk factors from raw patient data."""
    allowed, reason = check_rate_limit()
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    try:
        result = extract_risk_factors(payload)
        record_request()
        record_tokens(result.processing_metadata.token_usage.total)
        return result
    except Exception as e:
        record_failure()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/red-flag-check", response_model=RedFlagResponse)
async def red_flag_check_endpoint(payload: PatientPayload):
    """Module A: Run red flag debate loop."""
    allowed, reason = check_rate_limit()
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    try:
        result = analyze_red_flags(payload)
        record_request()
        record_tokens(result.processing_metadata.token_usage.total)
        return result
    except Exception as e:
        record_failure()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pattern-analysis", response_model=PatternAnalysisResponse)
async def pattern_analysis_endpoint(payload: PatientPayload):
    """Module B: Run LFT pattern debate loop."""
    allowed, reason = check_rate_limit()
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    try:
        result = analyze_pattern(payload)
        record_request()
        record_tokens(result.processing_metadata.token_usage.total)
        return result
    except Exception as e:
        record_failure()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transform-record")
async def transform_record_endpoint(request: Request):
    """Transform a pipeline_output record into a PatientPayload.

    Accepts the full record.json format from the extraction pipeline
    and returns the structured PatientPayload for the debate engine.
    """
    try:
        record = await request.json()
        payload = transform_record_to_payload(record)
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/full-pipeline")
async def full_pipeline_endpoint(request: Request):
    """Run the complete pipeline: Transform → Extract → Red Flag → Pattern.

    Accepts a pipeline_output record (full patient record from photo extraction)
    and runs all stages sequentially.
    """
    allowed, reason = check_rate_limit()
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    try:
        record = await request.json()

        # Step 0: Transform record to PatientPayload
        payload_dict = transform_record_to_payload(record)
        payload = PatientPayload(**payload_dict)

        # Step 1: Extract risk factors (deterministic)
        risk_result = extract_risk_factors(payload)

        # Enrich payload with risk factors
        payload.risk_factors = risk_result.risk_factors.model_dump()
        payload.derived_metrics = risk_result.derived_metrics.model_dump()

        # Step 2: Red flag check
        rf_result = analyze_red_flags(payload)
        record_request()
        record_tokens(rf_result.processing_metadata.token_usage.total)

        # Step 3: Pattern analysis (only if no red flag)
        pa_result = None
        if rf_result.final_decision != "RED_FLAG_PRESENT":
            pa_result = analyze_pattern(payload)
            record_request()
            record_tokens(pa_result.processing_metadata.token_usage.total)

        return {
            "patient": record.get("patient", {}),
            "transformed_payload": payload_dict,
            "risk_factors": risk_result.model_dump(),
            "red_flag": rf_result.model_dump(),
            "pattern_analysis": pa_result.model_dump() if pa_result else None,
        }

    except Exception as e:
        record_failure()
        raise HTTPException(status_code=500, detail=str(e))
