"""Orchestrator: runs the full pipeline from images to structured data."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import GEMINI_MODEL, IPAD_PHOTOS_DIR, PIPELINE_OUTPUT_DIR
from .extract import (
    extract_and_merge,
    extract_and_merge_from_images,
    load_images_from_bytes,
    validate_images,
)
from .schema import PatientRecord, ExtractionMetadata, PatientIdentifiers

CONFIDENCE_THRESHOLD = "low"  # reject only if below this
CONFIDENCE_LEVELS = {"high": 3, "medium": 2, "low": 1}


def _build_record(merged: dict, source_images: list[str]) -> PatientRecord:
    """Validate and build a PatientRecord from raw Gemini output."""
    return PatientRecord(
        patient=PatientIdentifiers(**(merged.get("patient", {}))),
        extraction_metadata=ExtractionMetadata(
            source_images=source_images,
            extraction_date=datetime.now(timezone.utc).isoformat(),
            model_used=GEMINI_MODEL,
            confidence=merged.get("confidence", "medium"),
        ),
        sections=merged.get("sections", []),
    )


def _save_record(record: PatientRecord, output_dir: Path, raw: dict) -> Path:
    """Save raw response and final record to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "raw_response.json", "w") as f:
        json.dump(raw, f, indent=2)

    output_path = output_dir / "record.json"
    with open(output_path, "w") as f:
        json.dump(record.model_dump(exclude_none=True), f, indent=2)

    return output_path


def run_pipeline(
    images_dir: Path | None = None,
    output_dir: Path | None = None,
    patient_id: str = "p0001",
) -> PatientRecord:
    """Run pipeline from a directory of images (for batch/CLI use)."""
    images_dir = images_dir or (IPAD_PHOTOS_DIR / patient_id)
    patient_output_dir = (output_dir or PIPELINE_OUTPUT_DIR) / patient_id

    print("=" * 60)
    print(f"AI PIPELINE: {patient_id} — iPad Photos -> Structured Patient Data")
    print("=" * 60)

    print(f"\n[{patient_id}] Processing images...")
    merged = extract_and_merge(images_dir)
    source_images = merged.pop("source_images", [])

    record = _build_record(merged, source_images)
    output_path = _save_record(record, patient_output_dir, merged)

    print(f"\n  DONE — {len(record.sections)} sections | Patient: {record.patient.name} | Confidence: {record.extraction_metadata.confidence}")
    print(f"  Output: {output_path}")

    return record


def run_pipeline_from_uploads(
    file_bytes_list: list[tuple[str, bytes]],
) -> dict:
    """Run pipeline from uploaded file bytes (for API use).

    Args:
        file_bytes_list: List of (filename, bytes) tuples from uploaded files.

    Returns:
        dict with keys: record, validation, session_id
    """
    # Load images
    images, filenames = load_images_from_bytes(file_bytes_list)

    # Step 1: Validate
    validation = validate_images(images)
    if not validation.get("is_medical", False):
        return {
            "status": "rejected",
            "validation": validation,
            "record": None,
            "session_id": None,
        }

    # Step 2: Extract and merge
    merged = extract_and_merge_from_images(images)

    # Step 3: Check confidence
    confidence = merged.get("confidence", "medium")
    conf_level = CONFIDENCE_LEVELS.get(confidence, 0)
    threshold_level = CONFIDENCE_LEVELS.get(CONFIDENCE_THRESHOLD, 1)

    if conf_level < threshold_level:
        return {
            "status": "low_confidence",
            "validation": validation,
            "confidence": confidence,
            "record": None,
            "session_id": None,
        }

    # Step 4: Build record
    record = _build_record(merged, filenames)

    # Step 5: Save
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    patient_name = (record.patient.name or "unknown").replace(" ", "_").lower()
    output_dir = PIPELINE_OUTPUT_DIR / f"upload_{patient_name}_{session_id}"
    _save_record(record, output_dir, merged)

    return {
        "status": "success",
        "validation": validation,
        "record": record.model_dump(exclude_none=True),
        "session_id": session_id,
        "output_dir": str(output_dir),
    }


def run_all_patients():
    """Run pipeline for all patient folders in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    patient_dirs = sorted(d for d in IPAD_PHOTOS_DIR.iterdir() if d.is_dir())
    if not patient_dirs:
        print(f"No patient folders found in {IPAD_PHOTOS_DIR}")
        return

    patient_ids = [d.name for d in patient_dirs]
    print(f"\nFound {len(patient_ids)} patients: {patient_ids}")
    print(f"Running all in parallel...\n")

    results = {}
    with ThreadPoolExecutor(max_workers=len(patient_ids)) as executor:
        futures = {
            executor.submit(run_pipeline, patient_id=pid): pid
            for pid in patient_ids
        }
        for future in as_completed(futures):
            pid = futures[future]
            try:
                record = future.result()
                results[pid] = record
                print(f"\n  [{pid}] Complete — {record.patient.name}")
            except Exception as e:
                print(f"\n  [{pid}] ERROR: {e}")

    print("\n" + "=" * 60)
    print(f"ALL DONE — {len(results)}/{len(patient_ids)} patients processed")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_pipeline(patient_id=sys.argv[1])
    else:
        run_all_patients()
