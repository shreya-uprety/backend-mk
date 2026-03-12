# MedForce Milton Key - Frontend API Documentation

Base URL: `http://localhost:8000`

---

## 1. Upload Photos & Extract Patient Data

**`POST /pipeline/extract`**

This is the **primary endpoint** for the nurse workflow. Upload iPad photos of a patient's EHR screen and receive structured medical data.

### Request

- **Content-Type:** `multipart/form-data`
- **Field name:** `files` (multiple)
- **Accepted types:** `image/jpeg`, `image/jpg`, `image/png`
- **Max files:** 20
- **Max file size:** 10MB per file

### Example (JavaScript)

```javascript
const formData = new FormData();
// Append each photo file
files.forEach(file => formData.append('files', file));

const response = await fetch('http://localhost:8000/pipeline/extract', {
    method: 'POST',
    body: formData,
});
const data = await response.json();
```

### Success Response (200)

```json
{
    "status": "success",
    "session_id": "20260312_143022_a1b2c3",
    "validation": {
        "is_medical": true,
        "reason": "Images appear to be EHR screenshots",
        "valid_image_count": 5,
        "total_image_count": 5
    },
    "patient": {
        "name": "John Smith",
        "dob": "15/03/1970",
        "mrn": "MRN-7823456",
        "age": "56",
        "sex": "Male"
    },
    "sections_count": 8,
    "confidence": "high",
    "record": {
        "patient": { ... },
        "extraction_metadata": {
            "source_images": ["photo1.jpg", "photo2.jpg"],
            "extraction_date": "2026-03-12T14:30:22Z",
            "model_used": "gemini-2.5-flash",
            "confidence": "high"
        },
        "sections": [ ... ]
    }
}
```

### Error Responses

| Status | Meaning | Example |
|--------|---------|---------|
| 400 | Bad request (no files, too many files, wrong type, too large) | `{"detail": "No files uploaded"}` |
| 422 | Images are not medical records | `{"detail": {"message": "Uploaded images do not appear to be medical records", "validation": {...}}}` |
| 422 | Extraction confidence too low | `{"detail": {"message": "Extraction confidence too low: low"}}` |
| 500 | Server/pipeline error | `{"detail": "error message"}` |

### Processing Time

- **Typical:** 1-3 minutes for 4-9 photos
- Images are auto-resized (max 2000px) before processing to reduce payload
- Two Gemini API calls are made: validation + extraction

---

## 2. Run Pipeline for Stored Photos

**`POST /pipeline/run/{patient_id}`**

Trigger extraction for photos already stored on the server in `data/ipad_photos/{patient_id}/`.

### Request

- **Path parameter:** `patient_id` (string, e.g. `p0001`)

### Example

```javascript
const response = await fetch('http://localhost:8000/pipeline/run/p0001', {
    method: 'POST',
});
const data = await response.json();
```

### Success Response (200)

```json
{
    "status": "success",
    "patient": {
        "name": "Margaret Pendleton",
        "dob": "15/03/1970",
        "mrn": "MRN-7823456",
        "age": "54",
        "sex": "Female"
    },
    "sections_count": 10,
    "confidence": "high",
    "output_file": "data/pipeline_output/p0001/record.json"
}
```

### Error Responses

| Status | Meaning |
|--------|---------|
| 404 | No images found for that patient_id |
| 500 | Pipeline error |

---

## 3. Get Stored Extraction Result

**`GET /pipeline/result/{patient_id}`**

Retrieve a previously extracted patient record from disk.

### Request

- **Path parameter:** `patient_id` (string, e.g. `p0001`)

### Example

```javascript
const response = await fetch('http://localhost:8000/pipeline/result/p0001');
const data = await response.json();
```

### Success Response (200)

Returns the full `PatientRecord` object (same structure as `record` field in the extract endpoint).

### Error Responses

| Status | Meaning |
|--------|---------|
| 404 | No extraction result found for that patient_id |

---

## 4. Health Check

**`GET /health`**

### Response (200)

```json
{"status": "healthy"}
```

---

## Data Model: PatientRecord

The `record` object returned by the extract endpoint has this structure:

```json
{
    "patient": {
        "name": "string | null",
        "dob": "string | null",
        "mrn": "string | null",
        "age": "string | null",
        "sex": "string | null"
    },
    "extraction_metadata": {
        "source_images": ["filename1.jpg", "filename2.jpg"],
        "extraction_date": "ISO 8601 timestamp",
        "model_used": "gemini-2.5-flash",
        "confidence": "high | medium | low"
    },
    "sections": [
        {
            "type": "string (e.g. demographics, lab_results, medications, etc.)",
            "title": "string",
            "date": "string | null",
            "data": "object | null — key-value pairs for structured fields",
            "items": "array | null — list items",
            "tables": "array | null — [{name, headers, rows}]",
            "findings": "object | null — {finding_name: finding_value}",
            "impression": "array | null — list of impression strings",
            "diagnosis": "string | null",
            "summary": "string | null",
            "rationale": "string | null — treatment rationale",
            "immediate_issues": "array | null — urgent issues",
            "plan": "array | null — plan items",
            "qa": "array | null — [[question, answer]]"
        }
    ]
}
```

### Section Types

Sections are **flexible** — different patients will have different section types depending on their clinical data. Common types include:

`demographics`, `social_history`, `lifestyle`, `referral`, `lab_results`, `imaging`, `medications`, `vitals`, `consultation_notes`, `questionnaire`, `assessment_plan`, `procedure`, `surgical_notes`, `nursing_notes`, `discharge_summary`, `pathology`, `radiology`, `echocardiography`, `endoscopy`, `biopsy`, `progress_notes`, `orders`

But any descriptive string is valid. **Do not hardcode section types** — render them dynamically.

### Section Fields

All fields in a section (except `type` and `title`) are **optional**. Only fields with actual data are included. Your frontend should check for each field's existence before rendering.

---

---

## 5. AI Decision Pipeline — Multi-Agent Debate Loop

Three endpoints that run the clinical decision pipeline: extract risk factors, check for red flags, and classify the LFT pattern.

### 5.1 Extract Risk Factors (Module 0)

**`POST /api/v1/decisions/extract-risk-factors`**

Deterministic risk factor extraction — no AI call, runs in <10ms. Must be called first to enrich the payload for Modules A and B.

#### Request

```javascript
const payload = {
    scenario_id: "patient_001",
    patient_demographics: { age: 54, sex: "male" },
    referral_summary: {
        symptoms: ["asymptomatic - elevated liver enzymes found on routine screening"],
        urgency_requested: "routine"
    },
    lft_blood_results: {
        ALT_IU_L: 122,
        AST_IU_L: 84,
        ALP_IU_L: 35,
        Bilirubin_umol_L: 15,
        Albumin_g_L: 42,
        GGT_IU_L: 155
    },
    history_risk_factors: {
        alcohol_units_weekly: 4,
        bmi: 34.1,
        known_liver_disease: false,
        comorbidities: ["Type 2 Diabetes", "Hypertension"]
    }
};

const response = await fetch('http://localhost:8000/api/v1/decisions/extract-risk-factors', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
});
const data = await response.json();
```

#### Success Response (200)

```json
{
    "scenario_id": "patient_001",
    "module": "risk_factor_extractor",
    "timestamp": "2026-03-12T15:42:05Z",
    "completeness": {
        "score": 1.0,
        "missing_fields": [],
        "warnings": ["Alcohol intake at 18.0 units/week exceeds UK guideline of 14 units"]
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
            "symptom_list": ["asymptomatic - elevated liver enzymes found on routine screening"]
        },
        "liver_disease_history": { "known_disease": false, "details": "none" }
    },
    "derived_metrics": {
        "r_factor": { "value": 11.3, "formula": "(ALT/ULN) / (ALP/ULN) = ...", "zone": "hepatitic" },
        "uln_multiples": { "ALT": 3.05, "AST": 2.1, "ALP": 0.27, "Bilirubin": 0.75, "GGT": 3.1 },
        "ast_alt_ratio": { "value": 0.69, "interpretation": "AST:ALT <1.0 — suggests NAFLD over alcoholic liver disease" },
        "albumin_status": "normal",
        "overall_lab_severity": "moderately_elevated"
    },
    "processing_metadata": {
        "model_used": "deterministic",
        "processing_time_ms": 0,
        "token_usage": { "input": 0, "output": 0, "total": 0 }
    }
}
```

---

### 5.2 Red Flag Check (Module A)

**`POST /api/v1/decisions/red-flag-check`**

Runs a 3-agent debate to determine if red flag symptoms are present. Send the **enriched payload** (original + `risk_factors` + `derived_metrics` from Module 0).

#### Request

```javascript
// Enrich the original payload with Module 0's output
const enrichedPayload = {
    ...originalPayload,
    risk_factors: module0Response.risk_factors,
    derived_metrics: module0Response.derived_metrics,
};

const response = await fetch('http://localhost:8000/api/v1/decisions/red-flag-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(enrichedPayload),
});
const data = await response.json();
```

#### Success Response (200)

```json
{
    "scenario_id": "patient_001",
    "timestamp": "2026-03-12T15:42:08Z",
    "final_decision": "NO_RED_FLAG",
    "confidence_score": 0.97,
    "recommended_action": "Proceed to pattern analysis",
    "debate_summary": {
        "consensus_reached": true,
        "vote_tally": { "red_flag_present": 0, "no_red_flag": 3 },
        "key_arguments_for_red_flag": [],
        "key_arguments_against_red_flag": ["Patient is asymptomatic...", "..."],
        "key_contention_points": [],
        "synthesis_rationale": "All three agents unanimously agreed...",
        "agent_perspectives": [
            {
                "agent_id": "agent_safety_net",
                "agent_persona": "The Cautious Safety-Net",
                "verdict": "NO_RED_FLAG",
                "confidence": 0.95,
                "reasoning": "No acute symptoms present...",
                "key_factors_cited": ["No jaundice", "Asymptomatic", "..."]
            }
        ]
    },
    "processing_metadata": {
        "model_used": "gemini-2.5-flash",
        "total_agents": 3,
        "debate_rounds": 1,
        "processing_time_ms": 91700,
        "short_circuited": true,
        "token_usage": { "input": 3200, "output": 900, "total": 4100 }
    }
}
```

#### Key Fields

| Field | Values | Meaning |
|-------|--------|---------|
| `final_decision` | `RED_FLAG_PRESENT` / `NO_RED_FLAG` | Whether urgent pathway is needed |
| `confidence_score` | 0.0 - 1.0 | How confident the system is |
| `short_circuited` | true/false | If true, all agents agreed and synthesizer was skipped |

**If `RED_FLAG_PRESENT`:** Stop here — patient needs urgent specialist review. Do NOT call Module B.

**If `NO_RED_FLAG`:** Proceed to Module B (Pattern Analysis).

---

### 5.3 Pattern Analysis (Module B)

**`POST /api/v1/decisions/pattern-analysis`**

Runs a 3-agent debate to classify the LFT pattern. Only call this if Module A returned `NO_RED_FLAG`.

#### Request

```javascript
// Same enriched payload as Module A
const response = await fetch('http://localhost:8000/api/v1/decisions/pattern-analysis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(enrichedPayload),
});
const data = await response.json();
```

#### Success Response (200)

```json
{
    "scenario_id": "patient_001",
    "timestamp": "2026-03-12T15:42:14Z",
    "final_classification": "HEPATITIC",
    "confidence_score": 0.90,
    "r_factor": { "value": 11.3, "formula": "...", "zone": "hepatitic" },
    "recommended_action": "Investigate common causes of hepatitic injury...",
    "debate_summary": {
        "consensus_reached": true,
        "vote_tally": { "cholestatic": 0, "hepatitic": 3, "mixed": 0 },
        "key_arguments_for_primary": ["R-factor 11.3 strongly hepatitic...", "..."],
        "key_arguments_against_primary": [],
        "key_contention_points": [],
        "synthesis_rationale": "All three agents unanimously classified as HEPATITIC...",
        "agent_perspectives": [...]
    },
    "processing_metadata": {
        "model_used": "gemini-2.5-flash",
        "total_agents": 3,
        "debate_rounds": 1,
        "processing_time_ms": 99700,
        "short_circuited": true,
        "token_usage": { "input": 3400, "output": 950, "total": 4350 }
    }
}
```

#### Key Fields

| Field | Values | Meaning |
|-------|--------|---------|
| `final_classification` | `CHOLESTATIC` / `HEPATITIC` / `MIXED` | The LFT pattern |
| `r_factor.value` | number | <2 cholestatic, 2-5 mixed, >5 hepatitic |
| `r_factor.zone` | string | Which zone the R-factor falls in |

---

### 5.4 Full Workflow (Frontend Implementation)

The frontend should call the three endpoints sequentially:

```javascript
async function runFullPipeline(patientPayload) {
    const BASE = 'http://localhost:8000/api/v1/decisions';

    // Step 1: Extract Risk Factors (instant)
    const m0Res = await fetch(`${BASE}/extract-risk-factors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patientPayload),
    });
    const m0Data = await m0Res.json();

    // Enrich payload with risk factors
    const enriched = {
        ...patientPayload,
        risk_factors: m0Data.risk_factors,
        derived_metrics: m0Data.derived_metrics,
    };

    // Step 2: Red Flag Check (~60-90s)
    const rfRes = await fetch(`${BASE}/red-flag-check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(enriched),
    });
    const rfData = await rfRes.json();

    if (rfData.final_decision === 'RED_FLAG_PRESENT') {
        return { riskFactors: m0Data, redFlag: rfData, pattern: null };
    }

    // Step 3: Pattern Analysis (~60-100s)
    const paRes = await fetch(`${BASE}/pattern-analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(enriched),
    });
    const paData = await paRes.json();

    return { riskFactors: m0Data, redFlag: rfData, pattern: paData };
}
```

---

### 5.5 Request Payload Schema

All three endpoints accept the same base payload:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario_id` | string | Yes | Unique identifier for the patient/scenario |
| `patient_demographics.age` | integer | Yes | Patient age |
| `patient_demographics.sex` | string | Yes | `"male"` or `"female"` |
| `referral_summary.symptoms` | string[] | Yes | List of presenting symptoms |
| `referral_summary.urgency_requested` | string | Yes | `"immediate"`, `"urgent"`, or `"routine"` |
| `lft_blood_results.ALT_IU_L` | number | Yes | ALT in IU/L |
| `lft_blood_results.AST_IU_L` | number | Yes | AST in IU/L |
| `lft_blood_results.ALP_IU_L` | number | Yes | ALP in IU/L |
| `lft_blood_results.Bilirubin_umol_L` | number | Yes | Bilirubin in µmol/L |
| `lft_blood_results.Albumin_g_L` | number | Yes | Albumin in g/L |
| `lft_blood_results.GGT_IU_L` | number | Yes | GGT in IU/L |
| `history_risk_factors.alcohol_units_weekly` | number | Yes | Alcohol units per week |
| `history_risk_factors.bmi` | number | Yes | Body Mass Index |
| `history_risk_factors.known_liver_disease` | boolean | Yes | Known liver disease |
| `history_risk_factors.comorbidities` | string[] | Yes | List of comorbidities |
| `risk_factors` | object | No | Pre-computed by Module 0 (optional on input) |
| `derived_metrics` | object | No | Pre-computed by Module 0 (optional on input) |

---

### 5.6 Error Responses

| Status | Meaning |
|--------|---------|
| 429 | Rate limited — too many requests. Retry after cooldown. |
| 500 | Server error — check `detail` field for message |

---

### 5.7 Processing Times

| Module | Typical Time | Notes |
|--------|-------------|-------|
| Module 0 (Extract) | <10ms | Deterministic, no AI call |
| Module A (Red Flag) | 60-100s | 3 parallel AI agents + optional synthesizer |
| Module B (Pattern) | 60-100s | 3 parallel AI agents + optional synthesizer |
| **Full Pipeline** | 120-200s | Depends on Gemini API latency |

The frontend should show loading states for Modules A and B as they take significant time.

---

## CORS

CORS is enabled for all origins (`*`), so you can call these endpoints from any frontend.

---

## Test Pages

| Page | URL | Purpose |
|------|-----|---------|
| Upload Tester | `http://localhost:8000/static/upload_test.html` | Test photo upload + extraction |
| Debate Tester | `http://localhost:8000/static/debate_tester.html` | Test AI debate pipeline with pre-built scenarios |
