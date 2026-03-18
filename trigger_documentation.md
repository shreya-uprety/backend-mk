# Patient Status Triggers — Frontend Documentation

Base URL: Use relative paths (e.g. `/api/v1/patient-status`).

---

## Overview

The status trigger system tracks a patient through the MedForce MK clinical pathway. When you advance a step, the backend **automatically runs the corresponding AI pipeline function** if one exists — risk factor extraction, red flag debate, or pattern analysis. Results are stored in GCS and returned for display.

### Key Concept

One click of "Advance" = one step forward. If that step has a handler:
- The handler runs (may take 30-90s for AI debate steps)
- Results are stored in GCS
- For decision steps (red flag, LFT classification), the AI auto-resolves the decision
- The response includes `handler_result` with what happened

---

## Endpoints

### 1. Create Patient Status

**`POST /api/v1/patient-status/create`**

```javascript
const res = await fetch('/api/v1/patient-status/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patient_id: 'MK-0002' }),
});
const status = await res.json();
```

The patient must already have an extracted record in GCS at `pipeline_output/{patient_id}/record.json` (from photo extraction via `/pipeline/extract`).

---

### 2. Advance One Step

**`POST /api/v1/patient-status/{patient_id}/advance`**

This is the main endpoint. Each call advances exactly one step and runs the handler if one exists.

```javascript
// Regular advance (no decision needed)
const res = await fetch('/api/v1/patient-status/MK-0002/advance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
});
const result = await res.json();

// Advance with a manual decision (for diagnostic_dilemma, monitoring)
const res = await fetch('/api/v1/patient-status/MK-0002/advance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision: 'yes' }),
});
```

#### Response

```json
{
    "patient_id": "MK-0002",
    "current_step": "PRESENT_TRIAGE_OPTIONS",
    "step_status": "in_progress",
    "pathway": "standard_triage",
    "started_at": "2026-03-17T10:00:00Z",
    "updated_at": "2026-03-17T10:01:30Z",
    "metadata": {
        "red_flag_detected": false,
        "red_flag_confidence": 0.97,
        "triage_probability": null,
        "lft_pattern": null,
        "lft_pattern_confidence": null,
        "diagnostic_dilemma": null,
        "monitoring_required": null
    },
    "step_history": [...],
    "is_archived": false,
    "final_disposition": null,
    "handler_result": {
        "step": "RED_FLAG_ASSESSMENT",
        "auto_decision": "no"
    }
}
```

#### The `handler_result` Field

This field is only present when a step handler ran. It tells the frontend what happened:

| handler_result shape | Meaning | Frontend action |
|---|---|---|
| `{"step": "...", "action": "completed"}` | Handler ran successfully (non-decision step) | Show result popup |
| `{"step": "...", "auto_decision": "no"}` | Handler ran and auto-decided (decision step) | Show result popup |
| `{"step": "...", "error": "..."}` | Handler failed | Show error message |
| *(field absent)* | No handler for this step | Nothing extra |

**Use `handler_result.step` to determine which popup to show:**

| `handler_result.step` | Result type | Popup content |
|---|---|---|
| `EXTRACT_RISK_FACTORS` | Risk factors | R-factor, ULN multiples, risk profile |
| `RED_FLAG_ASSESSMENT` | Red flag debate | Verdict, clinical rationale, agent reasoning |
| `ANALYZE_LFT_PATTERN` | Pattern debate | Classification, R-factor, agent reasoning |

---

### 3. Get Step Result (for popups)

**`GET /api/v1/patient-status/{patient_id}/step-result/{step_name}`**

Fetches the full stored AI result for displaying in popups or re-viewing completed steps.

| `step_name` | What it returns |
|---|---|
| `risk_factors` | Risk factor extraction result |
| `red_flag` | Red flag debate result (agents, synthesis, verdict) |
| `pattern` | Pattern analysis debate result (agents, synthesis, classification) |

```javascript
const res = await fetch('/api/v1/patient-status/MK-0002/step-result/red_flag');
const result = await res.json();
```

#### Risk Factors Response

```json
{
    "scenario_id": "MK-0002",
    "module": "risk_factor_extractor",
    "timestamp": "...",
    "completeness": {
        "score": 1.0,
        "missing_fields": [],
        "warnings": []
    },
    "risk_factors": {
        "alcohol_risk": { "units_weekly": 4, "level": "low", "exceeds_guidelines": false },
        "bmi_category": { "value": 34.1, "category": "obese" },
        "diabetes_status": { "present": true, "type": "type_2" },
        "cancer_history": { "present": false, "types": [], "metastasis_risk": "none" },
        "symptom_severity": {
            "has_red_flag_symptoms": false,
            "jaundice": false,
            "weight_loss": false,
            "abdominal_mass": false,
            "dark_urine_pale_stools": false,
            "pain_severity": "none",
            "symptom_list": ["asymptomatic"]
        },
        "liver_disease_history": { "known_disease": false, "details": "none" }
    },
    "derived_metrics": {
        "r_factor": { "value": 11.3, "formula": "3.05 / 0.27", "zone": "hepatitic" },
        "uln_multiples": { "ALT": 3.05, "AST": 2.1, "ALP": 0.27, "Bilirubin": 0.75, "GGT": 3.1 },
        "ast_alt_ratio": { "value": 0.69, "interpretation": "AST:ALT <1.0 — suggests NAFLD over alcoholic liver disease" },
        "albumin_status": "normal",
        "overall_lab_severity": "moderately_elevated"
    },
    "processing_metadata": { ... }
}
```

#### Red Flag Response

```json
{
    "scenario_id": "MK-0002",
    "module": "red_flag_determinator",
    "timestamp": "...",
    "final_decision": "NO_RED_FLAG",
    "confidence_score": 0.97,
    "recommended_action": "Proceed to pattern analysis",
    "debate_summary": {
        "consensus_reached": true,
        "vote_tally": { "red_flag_present": 0, "no_red_flag": 3 },
        "key_arguments_for_red_flag": [],
        "key_arguments_against_red_flag": [
            "Patient is asymptomatic with no jaundice, weight loss, or palpable mass...",
            "..."
        ],
        "key_contention_points": [],
        "synthesis_rationale": "All three agents unanimously agreed on NO_RED_FLAG...",
        "agent_perspectives": [
            {
                "agent_id": "agent_safety_net",
                "agent_persona": "The Cautious Safety-Net",
                "verdict": "NO_RED_FLAG",
                "confidence": 0.95,
                "reasoning": "Despite significantly elevated LFTs, the patient is explicitly asymptomatic...",
                "key_factors_cited": ["No jaundice", "Asymptomatic", "No palpable mass"]
            },
            {
                "agent_id": "agent_guideline",
                "agent_persona": "The Guideline Adherent",
                "verdict": "NO_RED_FLAG",
                "confidence": 1.0,
                "reasoning": "Per NICE CG100/BSG guidelines, red flag criteria require specific symptoms...",
                "key_factors_cited": ["NICE CG100", "No urgent symptoms"]
            },
            {
                "agent_id": "agent_statistician",
                "agent_persona": "The Statistical Analyst",
                "verdict": "NO_RED_FLAG",
                "confidence": 0.97,
                "reasoning": "Statistical analysis of LFT values shows elevated transaminases but...",
                "key_factors_cited": ["ALT 3x ULN", "Normal bilirubin"]
            }
        ]
    },
    "processing_metadata": {
        "model_used": "gemini-2.5-flash",
        "total_agents": 3,
        "debate_rounds": 1,
        "processing_time_ms": 45000,
        "token_usage": { "input": 3200, "output": 900, "total": 4100 }
    }
}
```

#### Pattern Analysis Response

```json
{
    "scenario_id": "MK-0002",
    "module": "lft_pattern_analyzer",
    "timestamp": "...",
    "final_classification": "HEPATITIC",
    "confidence_score": 0.93,
    "r_factor": { "value": 11.3, "formula": "...", "zone": "hepatitic" },
    "recommended_action": "Investigate common causes of hepatitic injury...",
    "debate_summary": {
        "consensus_reached": true,
        "vote_tally": { "cholestatic": 0, "hepatitic": 3, "mixed": 0 },
        "key_arguments_for_primary": ["R-factor 11.3 strongly hepatitic...", "..."],
        "key_arguments_against_primary": [],
        "key_contention_points": [],
        "synthesis_rationale": "All three agents unanimously classified as HEPATITIC...",
        "agent_perspectives": [
            {
                "agent_id": "agent_safety_net",
                "agent_persona": "The Cautious Safety-Net",
                "classification": "HEPATITIC",
                "confidence": 0.90,
                "reasoning": "R-factor of 11.3 is unambiguously in the hepatitic zone (>7)...",
                "key_factors_cited": ["R-factor 11.3", "ALT 3x ULN"]
            }
        ]
    },
    "processing_metadata": { ... }
}
```

---

### 4. Get Next Options

**`GET /api/v1/patient-status/{patient_id}/next-options`**

Check if the current step needs a manual decision.

```javascript
const res = await fetch('/api/v1/patient-status/MK-0002/next-options');
const options = await res.json();
```

#### Regular Step (just click Advance)

```json
{
    "current_step": "PRESENT_TRIAGE_OPTIONS",
    "is_terminal": false,
    "is_decision": false,
    "next_step": "GENERATE_GP_LETTER"
}
```

#### Decision Step (show YES/NO buttons)

```json
{
    "current_step": "DIAGNOSTIC_DILEMMA_ASSESSMENT",
    "is_terminal": false,
    "is_decision": true,
    "options": [
        { "decision": "yes", "next_step": "RECOMMEND_MRI_BIOPSY_ESCALATE" },
        { "decision": "no", "next_step": "CONDUCT_CONSULTATION" }
    ]
}
```

#### Terminal Step

```json
{
    "current_step": "DISCHARGE_TO_GP",
    "is_terminal": true,
    "options": []
}
```

---

### 5. Get Patient Status

**`GET /api/v1/patient-status/{patient_id}`**

Returns the full current status with metadata and step history.

---

### 6. List All Patients

**`GET /api/v1/patient-status/`**

---

### 7. Delete Patient Status

**`DELETE /api/v1/patient-status/{patient_id}`**

---

## Steps with Automatic Handlers

These steps run pipeline functions automatically when advanced to:

| Step | What runs | Duration | Auto-decides? |
|---|---|---|---|
| `EXTRACT_RISK_FACTORS` | Deterministic risk factor extraction | <1s | No |
| `RED_FLAG_ASSESSMENT` | 3-agent red flag debate | 30-90s | Yes → `yes`/`no` |
| `ANALYZE_LFT_PATTERN` | 3-agent pattern debate | 30-90s | No |
| `LFT_PATTERN_CLASSIFICATION` | Reads stored pattern result | <1s | Yes → `cholestatic`/`hepatitic` |

All other steps are manual — the frontend just calls advance with no special handling.

---

## Manual Decision Steps

These steps require the user to provide a `decision` value:

| Step | Options | When to show |
|---|---|---|
| `DIAGNOSTIC_DILEMMA_ASSESSMENT` | `yes` / `no` | After pattern classification |
| `ONGOING_MONITORING_ASSESSMENT` | `yes` / `no` | Before terminal state |

Use the `/next-options` endpoint to detect these and show decision buttons.

---

## Frontend Flow

```
1. POST /create                           → Create tracker
2. POST /advance                          → GP_REFERRAL → INTAKE_DIGITIZATION
3. POST /advance                          → DASHBOARD_CONFIRMATION
4. POST /advance                          → EXTRACT_RISK_FACTORS (handler runs, show popup)
5. POST /advance                          → RED_FLAG_ASSESSMENT (handler runs 30-90s, auto-decides, show popup)
6. POST /advance                          → PRESENT_TRIAGE_OPTIONS → GENERATE_GP_LETTER
7. POST /advance                          → GENERATE_GP_LETTER → ANALYZE_LFT_PATTERN
8. POST /advance                          → ANALYZE_LFT_PATTERN (handler runs 30-90s, show popup)
9. POST /advance                          → LFT_PATTERN_CLASSIFICATION (auto-decides)
10. GET /next-options                     → is_decision: true (DIAGNOSTIC_DILEMMA)
11. POST /advance {decision: "no"}        → CONDUCT_CONSULTATION
12. POST /advance                         → CONFIRM_DIAGNOSIS_EDUCATION
13. GET /next-options                     → is_decision: true (ONGOING_MONITORING)
14. POST /advance {decision: "no"}        → DISCHARGE_TO_GP (is_archived: true)
```

### Showing Popups

After each advance call, check `handler_result`:

```javascript
const result = await advance();

if (result.handler_result) {
    const step = result.handler_result.step;

    // Map step to result type
    const resultTypes = {
        EXTRACT_RISK_FACTORS: 'risk_factors',
        RED_FLAG_ASSESSMENT: 'red_flag',
        ANALYZE_LFT_PATTERN: 'pattern',
    };

    const type = resultTypes[step];
    if (type) {
        // Fetch full result for popup
        const detail = await fetch(`/api/v1/patient-status/${patientId}/step-result/${type}`);
        const data = await detail.json();
        showPopup(type, data);
    }
}
```

### Key Popup Fields

**Risk Factors popup** — show from `step-result/risk_factors`:
- `derived_metrics.r_factor` — R-factor value and zone
- `derived_metrics.uln_multiples` — which enzymes are elevated
- `risk_factors.alcohol_risk`, `bmi_category`, `diabetes_status`
- `risk_factors.symptom_severity` — red flag symptom flags
- `derived_metrics.ast_alt_ratio` — clinical interpretation

**Red Flag popup** — show from `step-result/red_flag`:
- `final_decision` — `RED_FLAG_PRESENT` or `NO_RED_FLAG`
- `confidence_score`
- `debate_summary.synthesis_rationale` — clinical reasoning
- `debate_summary.key_arguments_for_red_flag` / `key_arguments_against_red_flag`
- `debate_summary.agent_perspectives[]` — each agent's verdict, reasoning, key_factors_cited

**Pattern popup** — show from `step-result/pattern`:
- `final_classification` — `CHOLESTATIC`, `HEPATITIC`, or `MIXED`
- `confidence_score`
- `r_factor` — value and zone
- `recommended_action`
- `debate_summary.synthesis_rationale`
- `debate_summary.agent_perspectives[]` — each agent's classification, reasoning, key_factors_cited

---

## GCS Storage Layout

All results are persisted per patient:

```
gs://milton-key-dev/
  pipeline_output/{patient_id}/record.json          ← extracted patient record
  patient_status/{patient_id}/status.json           ← current status + history
  patient_status/{patient_id}/enriched_payload.json ← payload with risk factors
  patient_status/{patient_id}/risk_factors_result.json
  patient_status/{patient_id}/red_flag_result.json
  patient_status/{patient_id}/pattern_result.json
```

---

## Pathway Map (Flowchart Node States)

**`GET /api/v1/patient-status/{patient_id}/pathway-map`**

Returns every step in the flowchart with its current state. Use this to render the flowchart visualization — greying out or crossing out ruled-out nodes, highlighting the active node, etc.

```javascript
const res = await fetch('/api/v1/patient-status/MK-0002/pathway-map');
const map = await res.json();
```

### Response

```json
{
    "patient_id": "MK-0002",
    "pathway": "standard_triage",
    "is_archived": false,
    "final_disposition": null,
    "nodes": [
        { "step": "GP_REFERRAL_RECEIVED", "state": "traversed" },
        { "step": "INTAKE_DIGITIZATION", "state": "traversed" },
        { "step": "DASHBOARD_CONFIRMATION", "state": "traversed" },
        { "step": "EXTRACT_RISK_FACTORS", "state": "traversed" },
        { "step": "RED_FLAG_ASSESSMENT", "state": "traversed" },
        { "step": "URGENT_CONSULTANT_PATHWAY", "state": "ruled_out" },
        { "step": "PRESENT_TRIAGE_OPTIONS", "state": "traversed" },
        { "step": "GENERATE_GP_LETTER", "state": "traversed" },
        { "step": "ANALYZE_LFT_PATTERN", "state": "traversed" },
        { "step": "LFT_PATTERN_CLASSIFICATION", "state": "traversed" },
        { "step": "CHOLESTATIC_PATTERN", "state": "ruled_out" },
        { "step": "HEPATITIC_PATTERN", "state": "current" },
        { "step": "DIAGNOSTIC_DILEMMA_ASSESSMENT", "state": "upcoming" },
        { "step": "RECOMMEND_MRI_BIOPSY_ESCALATE", "state": "upcoming" },
        { "step": "CONSULTANT_MDT_REVIEW", "state": "upcoming" },
        { "step": "CONSULTANT_REVIEW_SIGNOFF", "state": "upcoming" },
        { "step": "CONDUCT_CONSULTATION", "state": "upcoming" },
        { "step": "CONFIRM_DIAGNOSIS_EDUCATION", "state": "upcoming" },
        { "step": "ONGOING_MONITORING_ASSESSMENT", "state": "upcoming" },
        { "step": "AI_SURVEILLANCE_LOOP", "state": "upcoming" },
        { "step": "DISCHARGE_TO_GP", "state": "upcoming" }
    ]
}
```

### Node States

| State | Meaning | Suggested UI |
|-------|---------|-------------|
| `traversed` | Patient has passed through this step | Green / completed check |
| `current` | Patient is currently at this step | Blue / highlighted, pulsing |
| `upcoming` | Step is on the patient's path but not yet reached | Normal / default |
| `ruled_out` | Step is NOT on this patient's path (eliminated by a decision) | Grey / crossed out / hidden |

### How Nodes Get Ruled Out

| Decision Made | Steps Ruled Out |
|---|---|
| Red flag = NO | `URGENT_CONSULTANT_PATHWAY` |
| Red flag = YES | `PRESENT_TRIAGE_OPTIONS`, `GENERATE_GP_LETTER`, `ANALYZE_LFT_PATTERN`, `LFT_PATTERN_CLASSIFICATION`, `CHOLESTATIC_PATTERN`, `HEPATITIC_PATTERN`, `DIAGNOSTIC_DILEMMA_ASSESSMENT`, `CONDUCT_CONSULTATION`, `CONFIRM_DIAGNOSIS_EDUCATION`, `RECOMMEND_MRI_BIOPSY_ESCALATE`, `CONSULTANT_MDT_REVIEW`, `CONSULTANT_REVIEW_SIGNOFF` |
| LFT pattern = hepatitic | `CHOLESTATIC_PATTERN` |
| LFT pattern = cholestatic | `HEPATITIC_PATTERN` |
| Diagnostic dilemma = NO | `RECOMMEND_MRI_BIOPSY_ESCALATE`, `CONSULTANT_MDT_REVIEW`, `CONSULTANT_REVIEW_SIGNOFF` |
| Diagnostic dilemma = YES | `CONDUCT_CONSULTATION`, `CONFIRM_DIAGNOSIS_EDUCATION` |
| Monitoring = NO | `AI_SURVEILLANCE_LOOP` |
| Monitoring = YES | `DISCHARGE_TO_GP` |

### Frontend Usage

Call this endpoint after every advance to update the flowchart:

```javascript
async function updateFlowchart(patientId) {
    const res = await fetch(`/api/v1/patient-status/${patientId}/pathway-map`);
    const map = await res.json();

    for (const node of map.nodes) {
        const el = document.getElementById(`node-${node.step}`);
        if (!el) continue;

        // Reset classes
        el.className = 'flowchart-node';

        switch (node.state) {
            case 'traversed':
                el.classList.add('node-done');
                break;
            case 'current':
                el.classList.add('node-active');
                break;
            case 'upcoming':
                el.classList.add('node-upcoming');
                break;
            case 'ruled_out':
                el.classList.add('node-ruled-out');
                break;
        }
    }
}
```

---

## Error Handling

| Status | Meaning |
|--------|---------|
| 400 | Invalid request (missing decision for decision step, patient already exists) |
| 404 | Patient not found, or no result found for step |
| 429 | Rate limited (from the debate engine) |
| 500 | Server error |

---

## Test Page

`/static/status_pipeline_tester.html` — Interactive tester with step progression, popups, and decision buttons.
