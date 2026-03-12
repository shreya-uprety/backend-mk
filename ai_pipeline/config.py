import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file")

GEMINI_MODEL = "gemini-2.5-flash"

DATA_DIR = BASE_DIR / "data"
IPAD_PHOTOS_DIR = DATA_DIR / "ipad_photos"
PIPELINE_OUTPUT_DIR = DATA_DIR / "pipeline_output"
GROUND_TRUTH_DIR = BASE_DIR / "synthetic_medical_records"

PIPELINE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
