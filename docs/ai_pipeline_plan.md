# AI Pipeline Plan: iPad Photos to Structured Patient Data

## Overview

Transform overlapping iPad photos of a Cerner EHR screen into a single, flexible structured JSON data object using Google Gemini Vision AI.

```
9 iPad Photos --> [Per-Image Extraction] --> [Deduplication & Merge] --> 1 Structured Patient JSON
```

## Configuration

### Google AI Studio API Key

- Stored in `backend/.env` as `GOOGLE_API_KEY`
- Generated from: https://aistudio.google.com/apikey
- GCP Project: `medforce-milton-key-pilot-dev`
- Model: `gemini-2.0-flash` (vision-capable, fast, cost-effective)

```env
# backend/.env
GOOGLE_API_KEY=<your-key-from-ai-studio>
```

### Python Dependencies

```
google-genai
python-dotenv
pydantic
Pillow
```

---

## Pipeline Architecture

### Directory Structure

```
backend/
  ai_pipeline/
    __init__.py
    config.py          # Load API key from .env
    extract.py         # Step 1: Per-image extraction via Gemini Vision
    merge.py           # Step 2: Deduplicate & merge partial extractions
    schema.py          # Pydantic models for the flexible data object
    pipeline.py        # Orchestrator: images in -> structured data out
  ipad_photos/         # Input: raw iPad photos (gitignored)
  pipeline_output/     # Output: generated structured JSON (gitignored)
  .env                 # API key (gitignored)
```

---

## Step 1: Per-Image Extraction

### Input
Each of the 9 iPad photos:
- `summary1.jpeg` - Ambulatory Summary (top): banner, sidebar, demographics, vitals
- `summary2.jpeg` - Ambulatory Summary (bottom): assessment & plan
- `referral1.jpeg` - Referral Letter (top): header, reason, HPI, PMHx
- `referral2.jpeg` - Referral Letter (bottom): alcohol, family hx, meds, sign-off
- `results.jpeg` - Results Review: full lab tables
- `notes1.jpeg` - Clinical Notes (top): consultation notes
- `notes2.jpeg` - Clinical Notes (bottom): questionnaire, assessment
- `orders.jpeg` - Orders/MAR: medication orders, allergies
- `imaging.jpeg` - Imaging: ultrasound + fibroscan reports

### Process
Send each image to Gemini Vision with a structured extraction prompt:

```python
import google.generativeai as genai
from PIL import Image

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-2.0-flash")

EXTRACTION_PROMPT = """
You are a medical data extraction system. Analyze this photo of a hospital EHR
(Electronic Health Record) screen and extract ALL visible medical data into structured JSON.

Rules:
1. Extract every piece of data you can see - names, dates, values, notes, medications, etc.
2. Identify which section type(s) are visible in this image.
3. For lab results, preserve the exact values, units, and reference ranges.
4. For medications, capture name, dose, frequency, and indication.
5. Flag any values marked as HIGH, CRITICAL, or abnormal.
6. If text is partially cut off at edges, extract what you can and mark with "[partial]".
7. Ignore UI chrome (buttons, toolbars) - only extract clinical data.

Return a JSON object with this structure:
{
  "sections_found": ["demographics", "vitals", "labs", ...],
  "patient_identifiers": {
    "name": "...",
    "dob": "...",
    "mrn": "...",
    "age": "...",
    "sex": "..."
  },
  "extracted_data": {
    // section-specific data, structured naturally
  },
  "confidence": "high" | "medium" | "low",
  "notes": "any issues with extraction"
}
"""

image = Image.open("ipad_photos/summary1.jpeg")
response = model.generate_content([EXTRACTION_PROMPT, image])
```

### Output
9 partial JSON extractions, each containing data visible in that photo.

---

## Step 2: Deduplication & Merge

### Problem
Photos overlap intentionally:
- Patient banner (name, DOB, MRN) appears in ALL 9 photos
- Sidebar (medications, vitals, labs summary) appears in most photos
- Assessment & Plan appears in both summary2 and notes2
- Some data is partially visible at photo edges

### Process
Send all 9 partial extractions to Gemini as a second LLM call:

```python
MERGE_PROMPT = """
You are a medical data merging system. Below are 9 JSON extractions from overlapping
photos of the SAME patient's EHR screen.

Your task:
1. DEDUPLICATE: Remove repeated data (e.g., patient banner appears in every photo)
2. MERGE: Combine partial data into complete sections (e.g., referral letter split across 2 photos)
3. RESOLVE CONFLICTS: If the same field has slightly different values, prefer the more complete/readable version
4. HANDLE PARTIALS: If a field was marked "[partial]" in one photo but complete in another, use the complete version
5. STRUCTURE: Output a single unified patient data object

Return the merged JSON following the Flexible Patient Data Object schema below.
"""
```

### Output
One unified, deduplicated patient data object.

---

## Step 3: Flexible Patient Data Object Schema

### Design Principles
- **Section-based**: Each piece of clinical data is a "section" with a `type` field
- **Flexible**: Different patients have different sections (e.g., one has biopsy results, another has endoscopy)
- **Self-describing**: Each section declares its type so the UI knows how to render it
- **No fixed schema**: The `sections` array grows/shrinks per patient

### Schema

```json
{
  "patient": {
    "name": "string",
    "dob": "string",
    "mrn": "string",
    "age": "string",
    "sex": "string"
  },
  "extraction_metadata": {
    "source_images": ["summary1.jpeg", "summary2.jpeg", ...],
    "extraction_date": "ISO date",
    "model_used": "gemini-2.0-flash",
    "confidence": "high | medium | low"
  },
  "sections": [
    {
      "type": "demographics",
      "title": "Patient Profile",
      "data": {
        "key": "value"
      }
    },
    {
      "type": "social_history",
      "title": "Social History",
      "items": ["string array of history items"]
    },
    {
      "type": "referral",
      "title": "GP Referral Letter",
      "date": "string",
      "data": {
        "from": "string",
        "to": "string",
        "reason": "string",
        "hpi": "string",
        "pmhx": "string",
        "alcohol_intake": "string",
        "family_history": "string",
        "medications": "string",
        "allergies": "string",
        "investigations_note": "string"
      }
    },
    {
      "type": "lab_results",
      "title": "string (e.g., Liver Blood Test Panel)",
      "date": "string",
      "tables": [
        {
          "name": "string (e.g., Liver Biochemistry)",
          "headers": ["Test", "Result", "Ref Range"],
          "rows": [["ALT", "122 U/L", "7-56 (HIGH)"]]
        }
      ]
    },
    {
      "type": "imaging",
      "title": "string (e.g., Ultrasound, Fibroscan, CT, MRI)",
      "date": "string",
      "indication": "string",
      "findings": { "key": "value" },
      "impression": ["string array"]
    },
    {
      "type": "medications",
      "title": "Current Medications",
      "items": [
        {
          "name": "string",
          "dose": "string",
          "frequency": "string",
          "indication": "string"
        }
      ],
      "allergies": ["string array"]
    },
    {
      "type": "vitals",
      "title": "Clinic Vitals",
      "date": "string",
      "data": { "BP": "value", "HR": "value", ... }
    },
    {
      "type": "consultation_notes",
      "title": "string",
      "date": "string",
      "data": {
        "cc": "string",
        "hpi": "string",
        "exam": { "system": "finding" },
        "assessment": "string"
      }
    },
    {
      "type": "questionnaire",
      "title": "string",
      "qa": [["question", "answer"]]
    },
    {
      "type": "assessment_plan",
      "title": "string",
      "diagnosis": "string",
      "summary": "string",
      "plan": ["string array of plan items"]
    }
  ]
}
```

### Flexibility Examples

A **different patient** (e.g., Chronic Hep B) might have these sections instead:
```json
"sections": [
  { "type": "demographics", ... },
  { "type": "referral", ... },
  { "type": "lab_results", "title": "Hepatitis B Serology", ... },
  { "type": "lab_results", "title": "Liver Function Tests", ... },
  { "type": "imaging", "title": "CT Abdomen", ... },
  { "type": "imaging", "title": "Fibroscan", ... },
  { "type": "biopsy", "title": "Liver Biopsy Report", ... },
  { "type": "medications", ... },
  { "type": "vitals", ... },
  { "type": "procedure", "title": "Upper GI Endoscopy", ... }
]
```

New section types can appear without breaking the schema. The UI renders each section based on its `type`.

---

## Pipeline Flow (End to End)

```
1. Load images from backend/ipad_photos/
         |
2. For each image, call Gemini Vision (parallel)
   -> 9 partial JSON extractions
         |
3. Pass all 9 extractions to Gemini for merge
   -> 1 unified JSON (with deduplication)
         |
4. Validate against Pydantic schema
         |
5. Save to backend/pipeline_output/p0001_extracted.json
         |
6. (Optional) Compare against ground truth in
   backend/synthetic_medical_records/p0001/structured_data/
   to measure extraction accuracy
```

---

## Evaluation (Ground Truth Comparison)

Since we have the original structured JSON files, we can measure accuracy:

| Metric | Description |
|--------|-------------|
| Field Coverage | % of ground truth fields successfully extracted |
| Value Accuracy | % of extracted values matching ground truth exactly |
| Deduplication | No duplicate sections in merged output |
| Structural Match | Output sections map to ground truth file types |

---

## Next Steps

1. Set up `backend/ai_pipeline/` module structure
2. Implement `extract.py` with Gemini Vision calls
3. Implement `merge.py` with deduplication logic
4. Define Pydantic models in `schema.py`
5. Build `pipeline.py` orchestrator
6. Run on p0001 iPad photos and compare with ground truth
7. Iterate on prompts based on extraction quality
8. Run on p0002, p0003 photos (once captured)
