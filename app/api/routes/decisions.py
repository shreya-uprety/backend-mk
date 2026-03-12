from fastapi import APIRouter, HTTPException

from debate_engine.schemas import (
    PatientPayload, RiskFactorResponse, RedFlagResponse, PatternAnalysisResponse,
)
from debate_engine.modules.risk_factor_extractor import extract_risk_factors
from debate_engine.modules.red_flag import analyze_red_flags
from debate_engine.modules.pattern_analysis import analyze_pattern
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
