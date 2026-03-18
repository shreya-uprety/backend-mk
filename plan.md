# Backend Implementation Plan — Nurse-Led Abnormal LFT Clinic Flowchart

Based on: `Nurse-Led Abnormal LFT Clinic flowchart.pdf`

---

## Current State vs Flowchart

### What we have (implemented with handlers)

| Flowchart Step | Status | Handler |
|---|---|---|
| GP Referral & LFT Received | Done | — |
| Intake & Digitize | Done | — |
| Extract Mandatory Risk Factors (AI) | Done | `handle_extract_risk_factors` |
| Red Flag Symptoms? (AI Decision) | Done | `handle_red_flag_assessment` (3-agent debate) |
| Urgent Consultant Pathway | Done | — (state only) |
| Analyze LFT Blood Test Pattern (AI) | Done | `handle_analyze_lft_pattern` (3-agent debate) |
| LFT Pattern Classification | Done | `handle_lft_pattern_classification` (auto-decides) |

### What we need to build

| Flowchart Step | Type | Priority | Description |
|---|---|---|---|
| Cholestatic → Hepatic Imaging CT/MRI (AI) | New handler | P1 | AI recommends specific imaging based on cholestatic pattern |
| Hepatitic → Wider Imaging + Full Liver Screen (AI) | New handler | P1 | AI recommends full liver screen and imaging for hepatitic pattern |
| Diagnostic Dilemma? (AI Decision) | New handler | P1 | AI assesses if case is complex or straightforward |
| AI Flags Complex Case | New handler | P2 | AI provides reasoning for why case is complex |
| MRI/Liver Biopsy (AI) | New handler | P2 | AI recommends specific biopsy/MRI protocol |
| Escalate to Consultant MDT | Existing step | P2 | No handler needed (manual consultant action) |
| Confirm Diagnosis (Nurse) | Existing step | P3 | No handler needed (manual nurse action) |
| Deliver Patient Education via App (Nurse) | New feature | P3 | Generate patient education content |
| Ongoing Monitoring Required? | New handler | P2 | AI recommends monitoring based on diagnosis |
| Set up 6-12 month AI Surveillance Loop | New feature | P2 | Configure automated monitoring schedule |
| Consultant Reviews AI Summary & Signs Off | New feature | P2 | Generate consultant-ready summary |
| Discharge to GP (Nurse) | Existing step | P3 | Generate GP discharge letter |

---

## Implementation Plan

### Phase 1: Investigation Recommendations (after pattern classification)

The flowchart shows two distinct investigation pathways after pattern classification:

**Cholestatic/Obstructive Pattern → Hepatic Imaging CT/MRI**
**Hepatitic/Inflammatory Pattern → Wider Imaging + Full Liver Screen**

#### What to build

A new debate module or AI function that takes the pattern result + patient data and recommends specific investigations.

**New file:** `backend/debate_engine/modules/investigation_recommender.py`

```
Input:
  - Enriched PatientPayload (with risk factors + derived metrics)
  - Pattern classification result (cholestatic/hepatitic/mixed)
  - Patient record (symptoms, history, medications)

Output:
  - recommended_investigations: list of specific tests/imaging
  - urgency: "routine" | "urgent" | "immediate"
  - reasoning: clinical justification for each recommendation
  - differential_diagnoses: list of conditions being investigated
```

**For cholestatic pattern:**
- Abdominal ultrasound (if not already done)
- CT/MRI abdomen (hepatic imaging)
- MRCP if biliary obstruction suspected
- AMA/ANA for PBC/PSC screening
- Tumour markers if malignancy suspected

**For hepatitic pattern:**
- Full liver screen (viral hepatitis serology, autoimmune markers, iron studies, caeruloplasmin, alpha-1 antitrypsin)
- Wider imaging (ultrasound + elastography)
- Drug/toxin review

**State machine change:** Add new steps between pattern classification and diagnostic dilemma:

```
CHOLESTATIC_PATTERN → CHOLESTATIC_INVESTIGATIONS (NEW)
HEPATITIC_PATTERN → HEPATITIC_INVESTIGATIONS (NEW)
CHOLESTATIC_INVESTIGATIONS → DIAGNOSTIC_DILEMMA_ASSESSMENT
HEPATITIC_INVESTIGATIONS → DIAGNOSTIC_DILEMMA_ASSESSMENT
```

**New handler:** `handle_cholestatic_investigations` / `handle_hepatitic_investigations`
- Calls investigation recommender AI
- Stores result in GCS: `patient_status/{id}/investigation_result.json`
- Shows popup with recommended investigations and reasoning

**Estimated effort:** 2-3 days

---

### Phase 2: Diagnostic Dilemma Assessment (AI Decision)

Currently `DIAGNOSTIC_DILEMMA_ASSESSMENT` is a manual decision step. The flowchart shows it as an **AI decision point**.

#### What to build

A new AI module that evaluates whether the case is straightforward or complex.

**New file:** `backend/debate_engine/modules/diagnostic_dilemma.py`

```
Input:
  - Enriched PatientPayload
  - Pattern classification result
  - Investigation recommendations
  - Full patient record

Output:
  - is_dilemma: true/false
  - confidence: 0.0-1.0
  - complexity_factors: list of reasons for complexity
  - reasoning: clinical justification
```

**Criteria for diagnostic dilemma (complex case):**
- Mixed pattern with R-factor 2-5 (ambiguous zone)
- Multiple competing differential diagnoses
- Conflicting lab values and clinical presentation
- Rare disease suspicion
- Atypical presentation for common conditions
- Prior inconclusive investigations

**Handler:** `handle_diagnostic_dilemma_assessment`
- Runs AI assessment
- Auto-decides "yes"/"no" based on `is_dilemma`
- Stores result: `patient_status/{id}/dilemma_result.json`

**Estimated effort:** 2-3 days

---

### Phase 3: Complex Case Path (Dilemma = YES)

When AI flags a diagnostic dilemma:

#### 3a. AI Flags Complex Case

**Handler:** `handle_recommend_mri_biopsy_escalate`
- AI generates specific recommendations for further investigation
- MRI protocol recommendations based on pattern
- Liver biopsy indication assessment
- Stores: `patient_status/{id}/complex_case_result.json`

```
Output:
  - recommended_procedure: "MRI" | "liver_biopsy" | "both"
  - mri_protocol: specific MRI type if applicable
  - biopsy_indication: clinical justification
  - urgency: "routine" | "urgent"
  - reasoning: why further investigation is needed
```

#### 3b. Escalate to Consultant MDT

No handler needed — this is a manual step where the consultant reviews. But we should generate a **consultant-ready summary**.

**New file:** `backend/debate_engine/modules/consultant_summary.py`

```
Input:
  - All previous results (risk factors, red flag, pattern, investigations, dilemma)
  - Full patient record

Output:
  - summary: structured clinical summary for MDT
  - key_findings: bullet points
  - questions_for_mdt: specific questions the AI wants addressed
  - suggested_differential: ranked differential diagnoses
```

**Estimated effort:** 3-4 days

---

### Phase 4: Straightforward Path (Dilemma = NO)

#### 4a. Confirm Diagnosis (Nurse)

Manual step. The nurse confirms the AI-suggested diagnosis. The AI should provide a **suggested diagnosis** to help.

**Handler:** `handle_conduct_consultation` (optional)
- AI suggests likely diagnosis based on all available data
- Nurse confirms or overrides
- Stores: `patient_status/{id}/diagnosis_result.json`

```
Output:
  - suggested_diagnoses: ranked list with confidence
  - primary_diagnosis: most likely
  - supporting_evidence: for each diagnosis
  - recommended_confirmatory_tests: if any
```

#### 4b. Deliver Patient Education via App (Nurse)

**New file:** `backend/debate_engine/modules/patient_education.py`

Generate patient-appropriate educational content based on their confirmed diagnosis.

```
Input:
  - Confirmed diagnosis
  - Patient demographics (age, sex)
  - Risk factors (alcohol, BMI, etc.)

Output:
  - condition_explanation: plain-language description
  - lifestyle_recommendations: specific to patient
  - medication_guidance: if applicable
  - warning_signs: when to seek urgent help
  - follow_up_schedule: recommended monitoring
```

**Estimated effort:** 2-3 days

---

### Phase 5: Monitoring & Discharge

#### 5a. Ongoing Monitoring Required? (AI Decision)

Currently manual. Should be an **AI decision** based on diagnosis severity.

**Handler:** `handle_ongoing_monitoring_assessment`

```
Input:
  - All previous results
  - Diagnosis
  - Current lab severity

Output:
  - monitoring_required: true/false
  - reasoning: why monitoring is/isn't needed
  - if true:
    - monitoring_schedule: "3_monthly" | "6_monthly" | "12_monthly"
    - monitoring_tests: which tests to repeat
    - surveillance_duration: "6_months" | "12_months" | "indefinite"
    - escalation_criteria: when to re-escalate
```

#### 5b. Set up 6-12 Month AI Surveillance Loop

**New file:** `backend/debate_engine/modules/surveillance_setup.py`

Configure the automated monitoring:

```
Output:
  - schedule: specific dates for follow-up LFTs
  - tests_per_visit: which tests to order each time
  - threshold_alerts: when AI should flag deterioration
  - auto_discharge_criteria: when patient can be safely discharged
  - next_review_date: first surveillance appointment
```

#### 5c. Consultant Reviews AI Summary & Signs Off

**New file:** `backend/debate_engine/modules/consultant_signoff.py`

Generate a comprehensive summary for consultant sign-off:

```
Output:
  - clinical_summary: full narrative
  - pathway_taken: which flowchart path this patient followed
  - ai_decisions_made: list of all AI decisions with reasoning
  - risk_assessment: current risk level
  - recommended_plan: final management plan
  - gp_letter_draft: draft letter for GP
```

#### 5d. Discharge to GP

Generate a GP discharge letter summarising the entire pathway.

**Estimated effort:** 4-5 days

---

## State Machine Changes

### New Steps to Add

```python
# Investigation steps (after pattern classification)
CHOLESTATIC_INVESTIGATIONS = "CHOLESTATIC_INVESTIGATIONS"
HEPATITIC_INVESTIGATIONS = "HEPATITIC_INVESTIGATIONS"

# Education step
PATIENT_EDUCATION = "PATIENT_EDUCATION"

# Consultant summary
CONSULTANT_SUMMARY_SIGNOFF = "CONSULTANT_SUMMARY_SIGNOFF"
```

### Updated Transitions

```python
# After pattern classification → investigations
CHOLESTATIC_PATTERN → CHOLESTATIC_INVESTIGATIONS  # (currently → DIAGNOSTIC_DILEMMA)
HEPATITIC_PATTERN → HEPATITIC_INVESTIGATIONS      # (currently → DIAGNOSTIC_DILEMMA)
CHOLESTATIC_INVESTIGATIONS → DIAGNOSTIC_DILEMMA_ASSESSMENT
HEPATITIC_INVESTIGATIONS → DIAGNOSTIC_DILEMMA_ASSESSMENT

# After confirm diagnosis → education
CONFIRM_DIAGNOSIS_EDUCATION → PATIENT_EDUCATION   # (currently → ONGOING_MONITORING)
PATIENT_EDUCATION → ONGOING_MONITORING_ASSESSMENT

# Surveillance → consultant signoff → end
AI_SURVEILLANCE_LOOP → CONSULTANT_SUMMARY_SIGNOFF
CONSULTANT_SUMMARY_SIGNOFF → END (terminal)

# Discharge also gets consultant signoff
DISCHARGE_TO_GP remains terminal
```

### New Handlers

| Step | Handler | AI? | Duration |
|---|---|---|---|
| `CHOLESTATIC_INVESTIGATIONS` | `handle_cholestatic_investigations` | Yes (Gemini) | 10-30s |
| `HEPATITIC_INVESTIGATIONS` | `handle_hepatitic_investigations` | Yes (Gemini) | 10-30s |
| `DIAGNOSTIC_DILEMMA_ASSESSMENT` | `handle_diagnostic_dilemma` | Yes (debate) | 30-90s |
| `RECOMMEND_MRI_BIOPSY_ESCALATE` | `handle_complex_case` | Yes (Gemini) | 10-30s |
| `CONDUCT_CONSULTATION` | `handle_suggest_diagnosis` | Yes (Gemini) | 10-30s |
| `PATIENT_EDUCATION` | `handle_patient_education` | Yes (Gemini) | 10-30s |
| `ONGOING_MONITORING_ASSESSMENT` | `handle_monitoring_decision` | Yes (Gemini) | 10-30s |
| `AI_SURVEILLANCE_LOOP` | `handle_surveillance_setup` | Yes (Gemini) | 10-30s |
| `CONSULTANT_SUMMARY_SIGNOFF` | `handle_consultant_summary` | Yes (Gemini) | 10-30s |

---

## New Debate Modules vs Single AI Calls

Not every step needs a full 3-agent debate. The debate pattern (3 agents + synthesizer) is best for **contested clinical decisions** where different perspectives matter:

| Step | Approach | Why |
|---|---|---|
| Investigation recommendations | Single Gemini call | Guideline-driven, low ambiguity |
| Diagnostic dilemma assessment | 3-agent debate | Subjective, benefits from multiple perspectives |
| Complex case reasoning | Single Gemini call | Summarisation task |
| Suggested diagnosis | Single Gemini call | Based on established criteria |
| Patient education | Single Gemini call | Content generation |
| Monitoring decision | Single Gemini call | Rule-based with AI refinement |
| Surveillance setup | Deterministic + Gemini | Schedule is rule-based, parameters need AI |
| Consultant summary | Single Gemini call | Summarisation task |

---

## Config-Driven Architecture

Thanks to the registry refactor, adding new modules requires:

1. Add prompt file in `debate_engine/prompts/`
2. Add handler function in `app/services/step_handlers.py`
3. Add step to `ProcessStep` enum and `TRANSITIONS` in `patient_status.py`
4. For debate modules: add entry to `MODULES` in `debate_engine/config.py`

No changes needed to the orchestrator, agent base class, or API routes.

---

## Implementation Priority

| Phase | What | Effort | Depends on |
|---|---|---|---|
| **Phase 1** | Investigation recommendations | 2-3 days | — |
| **Phase 2** | Diagnostic dilemma AI assessment | 2-3 days | Phase 1 |
| **Phase 3** | Complex case + consultant summary | 3-4 days | Phase 2 |
| **Phase 4** | Diagnosis suggestion + patient education | 2-3 days | Phase 2 |
| **Phase 5** | Monitoring + surveillance + discharge | 4-5 days | Phase 3 & 4 |

**Total estimated: 13-18 days**

---

## Files to Create

```
backend/
  debate_engine/
    modules/
      investigation_recommender.py    # Phase 1
      diagnostic_dilemma.py           # Phase 2
      consultant_summary.py           # Phase 3
      diagnosis_suggester.py          # Phase 4
      patient_education.py            # Phase 4
      surveillance_setup.py           # Phase 5
    prompts/
      investigation_cholestatic.md    # Phase 1
      investigation_hepatitic.md      # Phase 1
      diagnostic_dilemma_*.md         # Phase 2 (3 agent + synthesizer if debate)
      consultant_summary.md           # Phase 3
      diagnosis_suggestion.md         # Phase 4
      patient_education.md            # Phase 4
      monitoring_assessment.md        # Phase 5
      surveillance_config.md          # Phase 5
```

## Files to Modify

```
backend/
  app/
    models/patient_status.py          # New steps + transitions
    services/step_handlers.py         # New handlers
  debate_engine/
    config.py                         # New MODULES entry if using debate pattern
```
