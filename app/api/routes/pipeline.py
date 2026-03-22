from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from typing import List

from storage import get_storage

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png"}
MAX_FILES = 20
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file


@router.post("/extract")
async def extract_from_uploads(files: List[UploadFile] = File(...)):
    """Upload photos and extract structured patient data.

    This is the main endpoint for the nurse workflow:
    1. Nurse uploads iPad photos of a patient's EHR screen
    2. Pipeline validates they are medical records
    3. Extracts and merges all data into a structured patient record
    4. Returns the unified patient data object
    """
    # Validate file count
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Too many files. Maximum is {MAX_FILES}")

    # Validate file types and sizes, read bytes
    file_bytes_list = []
    for f in files:
        if f.content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type '{f.content_type}' for {f.filename}. Only JPEG and PNG allowed.",
            )
        data = await f.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File {f.filename} is too large ({len(data) // 1024 // 1024}MB). Maximum is 10MB.",
            )
        file_bytes_list.append((f.filename, data))

    # Run pipeline
    try:
        from ai_pipeline.pipeline import run_pipeline_from_uploads
        result = run_pipeline_from_uploads(file_bytes_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result["status"] == "rejected":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Uploaded images do not appear to be medical records",
                "validation": result["validation"],
            },
        )

    if result["status"] == "low_confidence":
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Extraction confidence too low: {result['confidence']}",
            },
        )

    return {
        "status": "success",
        "patient_id": result["patient_id"],
        "validation": result["validation"],
        "patient": result["record"]["patient"],
        "sections_count": len(result["record"]["sections"]),
        "confidence": result["record"]["extraction_metadata"]["confidence"],
        "record": result["record"],
    }


@router.post("/run/{patient_id}")
async def run_extraction_pipeline(patient_id: str = "p0001"):
    """Trigger the AI extraction pipeline for a given patient's stored photos."""
    storage = get_storage()

    # Check if patient images exist in storage
    image_blobs = [
        b for b in storage.list_blobs(f"ipad_photos/{patient_id}")
        if b.lower().endswith((".jpeg", ".jpg", ".png"))
    ]
    if not image_blobs:
        raise HTTPException(
            status_code=404,
            detail=f"No images found for patient {patient_id}",
        )

    try:
        from ai_pipeline.pipeline import run_pipeline
        record = run_pipeline(patient_id=patient_id)

        return {
            "status": "success",
            "patient": record.patient.model_dump(exclude_none=True),
            "sections_count": len(record.sections),
            "confidence": record.extraction_metadata.confidence,
            "output_path": f"pipeline_output/{patient_id}/record.json",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/result/{patient_id}")
async def get_pipeline_result(patient_id: str = "p0001"):
    """Retrieve the extracted patient record from storage."""
    storage = get_storage()
    path = f"pipeline_output/{patient_id}/record.json"

    if not storage.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"No extraction result found for {patient_id}. Run the pipeline first.",
        )

    return storage.read_json(path)


@router.put("/result/{patient_id}")
async def update_pipeline_result(patient_id: str, request: Request):
    """Update the extracted patient record with nurse edits.

    Accepts the full record JSON. Saves to GCS alongside the original,
    keeping an edit history.
    """
    from datetime import datetime, timezone

    storage = get_storage()
    record_path = f"pipeline_output/{patient_id}/record.json"

    if not storage.exists(record_path):
        raise HTTPException(
            status_code=404,
            detail=f"No extraction result found for {patient_id}.",
        )

    updated_record = await request.json()

    # Save the original as a backup (only on first edit)
    backup_path = f"pipeline_output/{patient_id}/record_original.json"
    if not storage.exists(backup_path):
        original = storage.read_json(record_path)
        storage.write_json(backup_path, original)

    # Track edit metadata
    now = datetime.now(timezone.utc).isoformat()
    edit_history_path = f"pipeline_output/{patient_id}/edit_history.json"
    history = storage.read_json(edit_history_path) if storage.exists(edit_history_path) else []
    history.append({"timestamp": now, "action": "record_updated"})
    storage.write_json(edit_history_path, history)

    # Save the updated record
    storage.write_json(record_path, updated_record)

    # Re-compute enriched payload so downstream handlers use edited data
    enriched_updated = False
    try:
        from debate_engine.modules.record_transformer import transform_record_to_payload
        from debate_engine.modules.risk_factor_extractor import extract_risk_factors
        from debate_engine.schemas import PatientPayload

        payload_dict = transform_record_to_payload(updated_record)
        payload = PatientPayload(**payload_dict)
        result = extract_risk_factors(payload)

        enriched = payload_dict.copy()
        enriched["risk_factors"] = result.risk_factors.model_dump()
        enriched["derived_metrics"] = result.derived_metrics.model_dump()

        prefix = f"patient_status/{patient_id}"
        storage.write_json(f"{prefix}/enriched_payload.json", enriched)
        storage.write_json(f"{prefix}/risk_factors_result.json", result.model_dump())
        enriched_updated = True
    except Exception:
        pass  # Patient may not have a status tracker yet — that's fine

    return {
        "status": "updated",
        "patient_id": patient_id,
        "timestamp": now,
        "edit_count": len(history),
        "enriched_payload_updated": enriched_updated,
    }


@router.get("/result/{patient_id}/original")
async def get_original_result(patient_id: str):
    """Retrieve the original (pre-edit) extracted record."""
    storage = get_storage()
    backup_path = f"pipeline_output/{patient_id}/record_original.json"

    if not storage.exists(backup_path):
        # No edits made yet — return the current record
        record_path = f"pipeline_output/{patient_id}/record.json"
        if not storage.exists(record_path):
            raise HTTPException(404, f"No record found for {patient_id}")
        return storage.read_json(record_path)

    return storage.read_json(backup_path)
