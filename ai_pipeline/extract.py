"""Extraction: send images to Gemini Vision, get structured patient data."""

import json
from google import genai
from PIL import Image
from pathlib import Path
from io import BytesIO

from .config import GOOGLE_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GOOGLE_API_KEY)

MAX_IMAGE_DIMENSION = 1500  # px — cap longest side to reduce payload


def _resize_image(img: Image.Image) -> Image.Image:
    """Downscale image so its longest side is at most MAX_IMAGE_DIMENSION."""
    w, h = img.size
    if max(w, h) <= MAX_IMAGE_DIMENSION:
        return img
    scale = MAX_IMAGE_DIMENSION / max(w, h)
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, Image.LANCZOS)

# ── Photo Validation Prompt ──────────────────────────────────────────────

VALIDATION_PROMPT = """Look at these images. Are they photos of a medical record, Electronic Health Record (EHR) screen, clinical document, or patient chart?

Answer with ONLY valid JSON (no markdown):
{
  "is_medical": true or false,
  "reason": "brief explanation",
  "valid_image_count": number of images that appear to be medical records,
  "total_image_count": number of total images
}"""

# ── Main Extraction Prompt (open-ended) ──────────────────────────────────

EXTRACTION_PROMPT = """You are a medical data extraction system. You are given photos of a patient's medical records. These could be from ANY Electronic Health Record system (Cerner, Epic, MEDITECH, etc.), paper charts, printed reports, or handwritten notes.

Your task:
1. EXTRACT all clinical data visible across ALL images.
2. DEDUPLICATE — photos may overlap (same data visible in multiple photos). Keep only ONE copy.
3. MERGE — combine partial data split across photos into complete sections.
4. RESOLVE CONFLICTS — if the same field differs across photos, prefer the more complete/readable version.
5. Ignore UI elements (buttons, toolbars, scrollbars) — only extract clinical data.

IMPORTANT GUIDELINES:
- Do NOT force data into predefined categories. Use whatever section types naturally fit the data.
- Common section types include (but are NOT limited to): demographics, social_history, lifestyle, referral, lab_results, imaging, medications, vitals, consultation_notes, questionnaire, assessment_plan, procedure, surgical_notes, nursing_notes, discharge_summary, pathology, radiology, echocardiography, endoscopy, biopsy, progress_notes, orders
- Use descriptive type names for anything that doesn't fit the above.
- For lab results, preserve EXACT values, units, and reference ranges. Flag abnormal values.
- For medications, capture name, dose, frequency, and indication where visible.
- If text is partially cut off, extract what you can and mark with "[partial]".

For the assessment_plan section specifically:
- "summary" is for general clinical summaries
- "rationale" is a SEPARATE field for treatment justification. Do NOT merge into summary.
- "immediate_issues" is a SEPARATE array for acute/urgent problems. Do NOT merge into summary or diagnosis.

Return ONLY valid JSON (no markdown, no code fences):

{
  "patient": {
    "name": "full patient name",
    "dob": "date of birth if visible",
    "mrn": "medical record number if visible",
    "age": "age if visible",
    "sex": "sex/gender if visible"
  },
  "sections": [
    {
      "type": "section_type",
      "title": "descriptive title",
      "date": "date if applicable",
      "data": { "key": "value pairs for structured fields" },
      "items": ["list items if applicable"],
      "tables": [
        {
          "name": "table name",
          "headers": ["col1", "col2"],
          "rows": [["val1", "val2"]]
        }
      ],
      "findings": { "finding_name": "finding_value" },
      "impression": ["impression items"],
      "diagnosis": "diagnosis if applicable",
      "summary": "summary if applicable",
      "rationale": "treatment rationale if applicable",
      "immediate_issues": ["urgent issues if applicable"],
      "plan": ["plan items if applicable"],
      "qa": [["question", "answer"]]
    }
  ],
  "confidence": "high" | "medium" | "low",
  "source_image_count": <number>,
  "notes": "any issues with extraction or data quality"
}

Only include fields that have actual data. Omit null/empty fields.
Use whatever section types naturally fit what you see — do not force data into categories that don't match.
"""


def validate_images(images: list[Image.Image]) -> dict:
    """Check if the uploaded images are medical records."""
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[VALIDATION_PROMPT] + images,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=500,
        ),
    )
    return json.loads(response.text)


def extract_and_merge_from_images(images: list[Image.Image]) -> dict:
    """Send pre-loaded PIL images to Gemini and get merged patient record."""
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[EXTRACTION_PROMPT] + images,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=genai.types.ThinkingConfig(thinking_budget=1024),
            max_output_tokens=8000,
        ),
    )
    return json.loads(response.text)


def load_images_from_dir(images_dir: Path) -> list[Image.Image]:
    """Load all JPEG/JPG/PNG images from a directory."""
    patterns = ["*.jpeg", "*.jpg", "*.png"]
    image_files = []
    for p in patterns:
        image_files.extend(sorted(images_dir.glob(p)))
    if not image_files:
        raise FileNotFoundError(f"No images found in {images_dir}")
    return [_resize_image(Image.open(f)) for f in image_files], [f.name for f in image_files]


def load_images_from_bytes(file_bytes_list: list[tuple[str, bytes]]) -> list[Image.Image]:
    """Load PIL images from raw bytes (for upload endpoint)."""
    images = []
    filenames = []
    for filename, data in file_bytes_list:
        img = _resize_image(Image.open(BytesIO(data)))
        images.append(img)
        filenames.append(filename)
    return images, filenames


def load_images_from_storage(patient_id: str) -> tuple[list[Image.Image], list[str]]:
    """Load patient images from storage backend (GCS or local)."""
    from concurrent.futures import ThreadPoolExecutor
    from storage import get_storage

    storage = get_storage()
    blobs = storage.list_blobs(f"ipad_photos/{patient_id}")
    image_blobs = sorted(
        b for b in blobs
        if b.lower().endswith((".jpeg", ".jpg", ".png"))
    )
    if not image_blobs:
        raise FileNotFoundError(f"No images found for patient {patient_id}")

    # Download images in parallel to avoid latency stacking
    def _load_one(blob_path: str) -> tuple[Image.Image, str]:
        data = storage.read_bytes(blob_path)
        img = _resize_image(Image.open(BytesIO(data)))
        filename = blob_path.split("/")[-1]
        return img, filename

    images, filenames = [], []
    with ThreadPoolExecutor(max_workers=min(len(image_blobs), 8)) as executor:
        for img, name in executor.map(_load_one, image_blobs):
            images.append(img)
            filenames.append(name)

    return images, filenames


# ── Legacy function for backward compat ──────────────────────────────

def extract_and_merge(images_dir: Path) -> dict:
    """Send all images from a directory in a single Gemini call."""
    images, filenames = load_images_from_dir(images_dir)
    print(f"  Loaded {len(images)} images")
    print(f"  Sending to Gemini in one call...")
    result = extract_and_merge_from_images(images)
    result["source_images"] = filenames
    return result
