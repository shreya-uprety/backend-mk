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

## CORS

CORS is enabled for all origins (`*`), so you can call these endpoints from any frontend.

---

## Test Page

A test HTML page is available at `http://localhost:8000/static/upload_test.html` for manually testing the upload workflow.
