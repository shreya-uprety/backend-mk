#!/usr/bin/env python3
"""Upload local data to Google Cloud Storage.

Usage:
    python scripts/upload_to_gcs.py <BUCKET_NAME> [--dry-run]

Uploads:
    - data/red_flag_test/*.json  -> gs://BUCKET/scenarios/red_flag_test/
    - data/ipad_photos/          -> gs://BUCKET/ipad_photos/
    - data/pipeline_output/      -> gs://BUCKET/pipeline_output/
"""
import sys
import json
from pathlib import Path

# Resolve paths relative to this script
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


def upload_to_gcs(bucket_name: str, dry_run: bool = False):
    from google.cloud import storage as gcs_lib

    client = gcs_lib.Client()
    bucket = client.bucket(bucket_name)

    uploaded = 0

    def upload_file(local_path: Path, gcs_path: str):
        nonlocal uploaded
        if dry_run:
            print(f"  [DRY RUN] {local_path} -> gs://{bucket_name}/{gcs_path}")
        else:
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(str(local_path))
            print(f"  {local_path.name} -> gs://{bucket_name}/{gcs_path}")
        uploaded += 1

    # 1. Scenarios (red_flag_test -> scenarios/red_flag_test)
    scenarios_dir = DATA_DIR / "red_flag_test"
    if scenarios_dir.exists():
        print(f"\n=== Uploading scenarios ===")
        for f in sorted(scenarios_dir.glob("*.json")):
            upload_file(f, f"scenarios/red_flag_test/{f.name}")

    # 2. iPad photos
    ipad_dir = DATA_DIR / "ipad_photos"
    if ipad_dir.exists():
        print(f"\n=== Uploading iPad photos ===")
        for patient_dir in sorted(ipad_dir.iterdir()):
            if patient_dir.is_dir():
                for img in sorted(patient_dir.glob("*")):
                    if img.suffix.lower() in (".jpeg", ".jpg", ".png"):
                        upload_file(img, f"ipad_photos/{patient_dir.name}/{img.name}")

    # 3. Pipeline output
    output_dir = DATA_DIR / "pipeline_output"
    if output_dir.exists():
        print(f"\n=== Uploading pipeline output ===")
        for sub in sorted(output_dir.iterdir()):
            if sub.is_dir():
                for f in sorted(sub.glob("*.json")):
                    upload_file(f, f"pipeline_output/{sub.name}/{f.name}")

    action = "Would upload" if dry_run else "Uploaded"
    print(f"\n{action} {uploaded} files to gs://{bucket_name}/")


def setup_local_scenarios():
    """Copy scenarios to the local storage path (data/scenarios/red_flag_test/)
    so LocalBackend can serve them via the /api/scenarios endpoint.
    """
    src = DATA_DIR / "red_flag_test"
    dst = DATA_DIR / "scenarios" / "red_flag_test"

    if not src.exists():
        print("No local scenarios found in data/red_flag_test/")
        return

    dst.mkdir(parents=True, exist_ok=True)
    import shutil
    copied = 0
    for f in sorted(src.glob("*.json")):
        shutil.copy2(f, dst / f.name)
        copied += 1

    print(f"Copied {copied} scenarios to {dst}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/upload_to_gcs.py <BUCKET_NAME> [--dry-run]")
        print("       python scripts/upload_to_gcs.py --local-setup")
        sys.exit(1)

    if sys.argv[1] == "--local-setup":
        setup_local_scenarios()
    else:
        bucket = sys.argv[1]
        dry = "--dry-run" in sys.argv
        upload_to_gcs(bucket, dry_run=dry)
