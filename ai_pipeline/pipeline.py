"""Orchestrator: runs the full pipeline from images to structured data."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import GEMINI_MODEL, IPAD_PHOTOS_DIR, PIPELINE_OUTPUT_DIR
from .extract import (
    extract_and_merge,
    extract_and_merge_from_images,
    load_images_from_bytes,
    load_images_from_storage,
    validate_images,
)
from .schema import PatientRecord, ExtractionMetadata, PatientIdentifiers
from storage import get_storage

CONFIDENCE_THRESHOLD = "low"  # reject only if below this
CONFIDENCE_LEVELS = {"high": 3, "medium": 2, "low": 1}


def _build_record(merged: dict, source_images: list[str]) -> PatientRecord:
    """Validate and build a PatientRecord from raw Gemini output."""
    # Backfill missing titles from section type
    for section in merged.get("sections", []):
        if not section.get("title"):
            section["title"] = section.get("type", "Unknown").replace("_", " ").title()

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


def _save_record(record: PatientRecord, output_prefix: str, raw: dict) -> str:
    """Save raw response and final record to storage."""
    storage = get_storage()
    storage.write_json(f"{output_prefix}/raw_response.json", raw)
    record_path = f"{output_prefix}/record.json"
    storage.write_json(record_path, record.model_dump(exclude_none=True))
    return record_path


def run_pipeline(
    images_dir: Path | None = None,
    output_dir: Path | None = None,
    patient_id: str = "p0001",
) -> PatientRecord:
    """Run pipeline from stored images (for batch/CLI use).

    If images_dir is given, reads from local disk (legacy).
    Otherwise, reads from storage backend (GCS or local data/).
    """
    print("=" * 60)
    print(f"AI PIPELINE: {patient_id} — iPad Photos -> Structured Patient Data")
    print("=" * 60)

    print(f"\n[{patient_id}] Processing images...")

    if images_dir:
        # Legacy local path mode
        merged = extract_and_merge(images_dir)
    else:
        # Storage-backed mode
        images, filenames = load_images_from_storage(patient_id)
        print(f"  Loaded {len(images)} images from storage")
        print(f"  Sending to Gemini in one call...")
        merged = extract_and_merge_from_images(images)
        merged["source_images"] = filenames

    source_images = merged.pop("source_images", [])
    record = _build_record(merged, source_images)

    output_prefix = f"pipeline_output/{patient_id}"
    record_path = _save_record(record, output_prefix, merged)

    print(f"\n  DONE — {len(record.sections)} sections | Patient: {record.patient.name} | Confidence: {record.extraction_metadata.confidence}")
    print(f"  Output: {record_path}")

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
    from concurrent.futures import ThreadPoolExecutor

    # Load images
    images, filenames = load_images_from_bytes(file_bytes_list)

    # Run validation and extraction in PARALLEL (saves 30-60s)
    with ThreadPoolExecutor(max_workers=2) as executor:
        val_future = executor.submit(validate_images, images)
        ext_future = executor.submit(extract_and_merge_from_images, images)

        validation = val_future.result()
        if not validation.get("is_medical", False):
            ext_future.cancel()
            return {
                "status": "rejected",
                "validation": validation,
                "record": None,
                "session_id": None,
            }

        merged = ext_future.result()

    # Check confidence
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

    # Build record
    record = _build_record(merged, filenames)

    # Save to storage using MRN as patient_id
    mrn = record.patient.mrn or ""
    if mrn:
        patient_id = mrn
    else:
        patient_name = (record.patient.name or "unknown").replace(" ", "_").lower()
        patient_id = patient_name

    output_prefix = f"pipeline_output/{patient_id}"
    _save_record(record, output_prefix, merged)

    return {
        "status": "success",
        "validation": validation,
        "record": record.model_dump(exclude_none=True),
        "patient_id": patient_id,
        "output_prefix": output_prefix,
    }


def run_all_patients():
    """Run pipeline for all patient folders in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    storage = get_storage()
    blobs = storage.list_blobs("ipad_photos")

    # Extract unique patient_id prefixes
    patient_ids = sorted({
        b.split("/")[1]
        for b in blobs
        if len(b.split("/")) >= 2 and b.split("/")[1]
    })

    if not patient_ids:
        print(f"No patient folders found in ipad_photos/")
        return

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
