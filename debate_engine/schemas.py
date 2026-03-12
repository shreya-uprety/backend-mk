from __future__ import annotations
from typing import Any
from pydantic import BaseModel


# ── Request Schemas ──────────────────────────────────────────────────────

class PatientDemographics(BaseModel):
    age: int
    sex: str


class ReferralSummary(BaseModel):
    symptoms: list[str]
    urgency_requested: str


class LFTBloodResults(BaseModel):
    ALT_IU_L: float
    AST_IU_L: float
    ALP_IU_L: float
    Bilirubin_umol_L: float
    Albumin_g_L: float
    GGT_IU_L: float


class HistoryRiskFactors(BaseModel):
    alcohol_units_weekly: float
    bmi: float
    known_liver_disease: bool
    comorbidities: list[str]


class PatientPayload(BaseModel):
    scenario_id: str
    patient_demographics: PatientDemographics
    referral_summary: ReferralSummary
    lft_blood_results: LFTBloodResults
    history_risk_factors: HistoryRiskFactors
    # Enriched fields (added by Module 0, optional on input)
    risk_factors: dict[str, Any] | None = None
    derived_metrics: dict[str, Any] | None = None


# ── Module 0: Risk Factor Extraction Response ────────────────────────────

class Completeness(BaseModel):
    score: float
    missing_fields: list[str]
    warnings: list[str]


class AlcoholRisk(BaseModel):
    units_weekly: float
    level: str
    exceeds_guidelines: bool


class BMICategory(BaseModel):
    value: float
    category: str


class DiabetesStatus(BaseModel):
    present: bool
    type: str


class CancerHistory(BaseModel):
    present: bool
    types: list[str]
    metastasis_risk: str


class SymptomSeverity(BaseModel):
    has_red_flag_symptoms: bool
    jaundice: bool
    weight_loss: bool
    abdominal_mass: bool
    dark_urine_pale_stools: bool
    pain_severity: str
    symptom_list: list[str]


class LiverDiseaseHistory(BaseModel):
    known_disease: bool
    details: str


class RiskFactors(BaseModel):
    alcohol_risk: AlcoholRisk
    bmi_category: BMICategory
    diabetes_status: DiabetesStatus
    cancer_history: CancerHistory
    symptom_severity: SymptomSeverity
    liver_disease_history: LiverDiseaseHistory


class RFactor(BaseModel):
    value: float
    formula: str
    zone: str


class ULNMultiples(BaseModel):
    ALT: float
    AST: float
    ALP: float
    Bilirubin: float
    GGT: float


class ASTALTRatio(BaseModel):
    value: float
    interpretation: str


class DerivedMetrics(BaseModel):
    r_factor: RFactor
    uln_multiples: ULNMultiples
    ast_alt_ratio: ASTALTRatio
    albumin_status: str
    overall_lab_severity: str


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0


class ProcessingMetadata(BaseModel):
    model_used: str
    processing_time_ms: int
    token_usage: TokenUsage


class RiskFactorResponse(BaseModel):
    scenario_id: str
    module: str = "risk_factor_extractor"
    timestamp: str
    completeness: Completeness
    risk_factors: RiskFactors
    derived_metrics: DerivedMetrics
    processing_metadata: ProcessingMetadata


# ── Agent Perspective (shared by Module A and B) ─────────────────────────

class AgentPerspective(BaseModel):
    agent_id: str
    agent_persona: str
    verdict: str | None = None         # Module A
    classification: str | None = None  # Module B
    confidence: float
    reasoning: str
    key_factors_cited: list[str]


# ── Module A: Red Flag Response ──────────────────────────────────────────

class RedFlagVoteTally(BaseModel):
    red_flag_present: int
    no_red_flag: int


class RedFlagDebateSummary(BaseModel):
    consensus_reached: bool
    vote_tally: RedFlagVoteTally
    key_arguments_for_red_flag: list[str]
    key_arguments_against_red_flag: list[str]
    key_contention_points: list[str]
    synthesis_rationale: str
    agent_perspectives: list[AgentPerspective]


class DebateProcessingMetadata(BaseModel):
    model_used: str
    total_agents: int
    debate_rounds: int
    processing_time_ms: int
    token_usage: TokenUsage


class RedFlagResponse(BaseModel):
    scenario_id: str
    module: str = "red_flag_determinator"
    timestamp: str
    final_decision: str
    confidence_score: float
    recommended_action: str
    debate_summary: RedFlagDebateSummary
    processing_metadata: DebateProcessingMetadata


# ── Module B: Pattern Analysis Response ──────────────────────────────────

class PatternVoteTally(BaseModel):
    cholestatic: int
    hepatitic: int
    mixed: int


class PatternDebateSummary(BaseModel):
    consensus_reached: bool
    vote_tally: PatternVoteTally
    key_arguments_for_primary: list[str]
    key_arguments_against_primary: list[str]
    key_contention_points: list[str]
    synthesis_rationale: str
    agent_perspectives: list[AgentPerspective]


class PatternAnalysisResponse(BaseModel):
    scenario_id: str
    module: str = "lft_pattern_analyzer"
    timestamp: str
    final_classification: str
    confidence_score: float
    r_factor: RFactor
    recommended_action: str
    debate_summary: PatternDebateSummary
    processing_metadata: DebateProcessingMetadata
