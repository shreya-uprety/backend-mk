from fastapi import APIRouter, HTTPException

from storage import get_storage

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

SCENARIOS_PREFIX = "scenarios/red_flag_test"


@router.get("/")
async def list_scenarios():
    """List all available test scenario files."""
    storage = get_storage()
    blobs = storage.list_blobs(SCENARIOS_PREFIX)
    files = [
        b.split("/")[-1]
        for b in blobs
        if b.endswith(".json")
    ]
    return {"scenarios": sorted(files)}


@router.get("/{filename}")
async def get_scenario(filename: str):
    """Return the JSON content of a specific scenario file."""
    if not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are supported")

    storage = get_storage()
    path = f"{SCENARIOS_PREFIX}/{filename}"

    if not storage.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{filename}' not found",
        )

    return storage.read_json(path)
