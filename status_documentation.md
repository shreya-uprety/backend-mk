# Patient Status Tracking — Frontend API Documentation

Base URL: Use relative paths (e.g. `/api/v1/patient-status`).

---

## Overview

Tracks a patient's progress through the MedForce MK clinical pathway. Each patient has a `current_step`, a `pathway` (standard or urgent), and clinical `metadata` that gets populated at decision points. Status is persisted in GCS.

### Pathway Flow

```
GP Referral → Intake → Dashboard → Extract Risk Factors → Red Flag?
  ├─ YES → Urgent Consultant Pathway → Monitoring?
  └─ NO  → Triage Options → GP Letter → Analyze LFT → LFT Pattern?
             ├─ Cholestatic → Diagnostic Dilemma?
             └─ Hepatitic   → Diagnostic Dilemma?
                               ├─ YES → MRI/Biopsy → MDT Review → Consultant Signs Off → Monitoring?
                               └─ NO  → Consultation → Diagnosis & Education → Monitoring?
                                                                                 ├─ YES → AI Surveillance Loop
                                                                                 └─ NO  → Discharge to GP
```

---

## Endpoints

### 1. Create Patient Status

**`POST /api/v1/patient-status/create`**

```javascript
const res = await fetch('/api/v1/patient-status/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patient_id: 'MK-0001' }),
});
```

Returns the full `PatientStatus` object. Starts at `GP_REFERRAL_RECEIVED`.

---

### 2. Get Patient Status

**`GET /api/v1/patient-status/{patient_id}`**

```javascript
const res = await fetch('/api/v1/patient-status/MK-0001');
const status = await res.json();
```

#### Response

```json
{
    "patient_id": "MK-0001",
    "current_step": "RED_FLAG_ASSESSMENT",
    "step_status": "in_progress",
    "pathway": "standard_triage",
    "started_at": "2026-03-16T10:00:00Z",
    "updated_at": "2026-03-16T10:05:00Z",
    "metadata": {
        "red_flag_detected": null,
        "red_flag_confidence": null,
        "triage_probability": null,
        "lft_pattern": null,
        "lft_pattern_confidence": null,
        "diagnostic_dilemma": null,
        "monitoring_required": null
    },
    "step_history": [
        {
            "step": "GP_REFERRAL_RECEIVED",
            "status": "completed",
            "entered_at": "2026-03-16T10:00:00Z",
            "completed_at": "2026-03-16T10:00:05Z",
            "metadata": {}
        }
    ],
    "is_archived": false,
    "final_disposition": null
}
```

---

### 3. Advance to Next Step

**`POST /api/v1/patient-status/{patient_id}/advance`**

For regular steps, send an empty body. For decision steps, send the `decision` value.

```javascript
// Regular step (no decision needed)
await fetch('/api/v1/patient-status/MK-0001/advance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
});

// Decision step (e.g. red flag)
await fetch('/api/v1/patient-status/MK-0001/advance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision: 'no' }),
});
```

Returns the updated `PatientStatus` object.

---

### 4. Get Next Options

**`GET /api/v1/patient-status/{patient_id}/next-options`**

Use this to determine if the current step is a decision point and what the options are.

```javascript
const res = await fetch('/api/v1/patient-status/MK-0001/next-options');
const options = await res.json();
```

#### Response — Regular Step

```json
{
    "current_step": "INTAKE_DIGITIZATION",
    "is_terminal": false,
    "is_decision": false,
    "next_step": "DASHBOARD_CONFIRMATION"
}
```

#### Response — Decision Step

```json
{
    "current_step": "RED_FLAG_ASSESSMENT",
    "is_terminal": false,
    "is_decision": true,
    "options": [
        { "decision": "yes", "next_step": "URGENT_CONSULTANT_PATHWAY" },
        { "decision": "no", "next_step": "PRESENT_TRIAGE_OPTIONS" }
    ]
}
```

#### Response — Terminal Step

```json
{
    "current_step": "DISCHARGE_TO_GP",
    "is_terminal": true,
    "options": []
}
```

---

### 5. Update Metadata

**`PATCH /api/v1/patient-status/{patient_id}/metadata`**

Set confidence/probability values before advancing through a decision step.

```javascript
await fetch('/api/v1/patient-status/MK-0001/metadata', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        red_flag_confidence: 0.97,
        triage_probability: 0.70
    }),
});
```

---

### 6. List All Patients

**`GET /api/v1/patient-status/`**

```json
{
    "patients": [
        {
            "patient_id": "MK-0001",
            "current_step": "ANALYZE_LFT_PATTERN",
            "step_status": "in_progress",
            "pathway": "standard_triage",
            "is_archived": false
        }
    ]
}
```

---

### 7. Delete Patient Status

**`DELETE /api/v1/patient-status/{patient_id}`**

---

## Decision Points Reference

| Step | Decision Values | Side Effects |
|------|----------------|--------------|
| `RED_FLAG_ASSESSMENT` | `yes` / `no` | `yes` switches pathway to `urgent_consultant` |
| `LFT_PATTERN_CLASSIFICATION` | `cholestatic` / `hepatitic` | Sets `metadata.lft_pattern` |
| `DIAGNOSTIC_DILEMMA_ASSESSMENT` | `yes` / `no` | Sets `metadata.diagnostic_dilemma` |
| `ONGOING_MONITORING_ASSESSMENT` | `yes` / `no` | `yes` → archived as `surveillance`, `no` → archived as `discharged` |

---

## All Process Steps

| Step | Type |
|------|------|
| `GP_REFERRAL_RECEIVED` | Entry |
| `INTAKE_DIGITIZATION` | Regular |
| `DASHBOARD_CONFIRMATION` | Regular |
| `EXTRACT_RISK_FACTORS` | Regular |
| `RED_FLAG_ASSESSMENT` | Decision |
| `URGENT_CONSULTANT_PATHWAY` | Regular (urgent path) |
| `PRESENT_TRIAGE_OPTIONS` | Regular |
| `GENERATE_GP_LETTER` | Regular |
| `ANALYZE_LFT_PATTERN` | Regular |
| `LFT_PATTERN_CLASSIFICATION` | Decision |
| `CHOLESTATIC_PATTERN` | Regular |
| `HEPATITIC_PATTERN` | Regular |
| `DIAGNOSTIC_DILEMMA_ASSESSMENT` | Decision |
| `RECOMMEND_MRI_BIOPSY_ESCALATE` | Regular |
| `CONSULTANT_MDT_REVIEW` | Regular |
| `CONSULTANT_REVIEW_SIGNOFF` | Regular |
| `CONDUCT_CONSULTATION` | Regular |
| `CONFIRM_DIAGNOSIS_EDUCATION` | Regular |
| `ONGOING_MONITORING_ASSESSMENT` | Decision |
| `AI_SURVEILLANCE_LOOP` | Terminal |
| `DISCHARGE_TO_GP` | Terminal |

---

## Key Fields for UI

| Field | Use |
|-------|-----|
| `current_step` | Show which stage the patient is at |
| `step_status` | `pending`, `in_progress`, `completed`, `escalated`, `skipped` |
| `pathway` | `standard_triage` or `urgent_consultant` — use for visual styling (e.g. red banner for urgent) |
| `metadata` | Show confidence scores, LFT pattern, flags in the patient detail view |
| `step_history` | Render as a timeline of completed steps |
| `is_archived` | Hide from active patient list, show in archive |
| `final_disposition` | `surveillance` or `discharged` — show as final outcome |
