"""Step 2: Deduplicate and merge partial extractions into one unified patient record."""

import json
from google import genai

from .config import GOOGLE_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GOOGLE_API_KEY)

MERGE_PROMPT = """You are a medical data merging system. Below are {count} JSON extractions from overlapping photos of the SAME patient's EHR (Electronic Health Record) screen.

Your task:
1. DEDUPLICATE: The photos overlap — patient banner, sidebar data (medications, vitals, labs) appear in multiple photos. Keep only ONE copy of each piece of data.
2. MERGE: Combine partial data into complete sections. For example, a referral letter split across 2 photos should become one complete referral section.
3. RESOLVE CONFLICTS: If the same field has slightly different values across photos (due to photo quality), prefer the more complete/readable version.
4. HANDLE PARTIALS: If a field was marked "[partial]" in one photo but complete in another, use the complete version.
5. ORGANIZE: Group all data into logical clinical sections.

Return ONLY valid JSON (no markdown, no code fences) with this exact structure:

{{
  "patient": {{
    "name": "full patient name",
    "dob": "date of birth",
    "mrn": "medical record number",
    "age": "age",
    "sex": "sex/gender"
  }},
  "sections": [
    {{
      "type": "demographics",
      "title": "Patient Profile",
      "data": {{ "key": "value pairs for demographics" }},
      "items": ["array items if applicable, e.g. social history"]
    }},
    {{
      "type": "social_history",
      "title": "Social History",
      "items": ["history item 1", "history item 2"]
    }},
    {{
      "type": "lifestyle",
      "title": "Lifestyle",
      "items": ["lifestyle item 1", "lifestyle item 2"]
    }},
    {{
      "type": "referral",
      "title": "GP Referral Letter",
      "date": "letter date",
      "data": {{
        "from": "referring doctor",
        "to": "receiving clinic",
        "reason": "reason for referral",
        "hpi": "history of presenting illness",
        "pmhx": "past medical history",
        "alcohol_intake": "...",
        "family_history": "...",
        "medications": "...",
        "allergies": "...",
        "investigations_note": "..."
      }}
    }},
    {{
      "type": "lab_results",
      "title": "Lab Panel Title",
      "date": "test date",
      "tables": [
        {{
          "name": "Table Name (e.g. Liver Biochemistry)",
          "headers": ["Test", "Result", "Ref Range"],
          "rows": [["Test Name", "Value with units", "Reference range with flag if abnormal"]]
        }}
      ]
    }},
    {{
      "type": "imaging",
      "title": "Imaging Study Title",
      "date": "study date",
      "indication": "reason for study",
      "findings": {{ "finding_name": "finding_value" }},
      "impression": ["impression line 1", "impression line 2"]
    }},
    {{
      "type": "medications",
      "title": "Current Medications",
      "items": [
        {{ "name": "drug name", "dose": "dose", "frequency": "freq", "indication": "reason" }}
      ],
      "data": {{ "allergies": ["allergy list"] }}
    }},
    {{
      "type": "vitals",
      "title": "Clinic Vitals",
      "date": "vitals date",
      "data": {{ "BP": "value", "HR": "value", "Temp": "value", "BMI": "value" }}
    }},
    {{
      "type": "consultation_notes",
      "title": "Consultation Notes",
      "date": "consult date",
      "data": {{
        "cc": "chief complaint",
        "hpi": "history of presenting illness",
        "exam": {{ "system": "finding" }},
        "assessment": "clinical assessment"
      }}
    }},
    {{
      "type": "questionnaire",
      "title": "Pre-Consultation Questionnaire",
      "qa": [["question", "answer"]]
    }},
    {{
      "type": "assessment_plan",
      "title": "Assessment & Plan",
      "diagnosis": "diagnosis text",
      "summary": "clinical summary",
      "plan": ["plan item 1", "plan item 2"]
    }}
  ],
  "confidence": "high" | "medium" | "low",
  "deduplication_notes": "brief notes on what was deduplicated"
}}

Only include section types that have actual data. If a section type doesn't apply, omit it entirely.
Multiple sections of the same type are allowed (e.g., two different imaging studies).

Here are the {count} extractions:

{extractions_json}"""


def merge_extractions(extractions: list[dict]) -> dict:
    """Merge multiple partial extractions into one unified patient record."""
    extractions_text = json.dumps(extractions, indent=2)

    prompt = MERGE_PROMPT.format(
        count=len(extractions),
        extractions_json=extractions_text,
    )

    print(f"Merging {len(extractions)} extractions...")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    result = json.loads(response.text)
    print(f"  -> Merged into {len(result.get('sections', []))} sections")
    print(f"  -> Confidence: {result.get('confidence', 'unknown')}")

    return result
