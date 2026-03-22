"""
Test script for the SVG Dashboard integration.

Tests:
1. Import verification
2. POST /svg-dashboard/generate with raw JSON (the example_patientprofile.json)
3. Endpoint availability check

Usage:
    cd backend
    python tests/test_svg_dashboard.py
"""

import json
import sys
import asyncio
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed = 0
failed = 0


def ok(msg):
    global passed
    passed += 1
    print(f"  {GREEN}✅ {msg}{RESET}")


def fail(msg, err=None):
    global failed
    failed += 1
    print(f"  {RED}❌ {msg}{RESET}")
    if err:
        print(f"     {RED}{err}{RESET}")


# ─────────────────────────────────────────────
# Test 1: Import Checks
# ─────────────────────────────────────────────
print(f"\n{BOLD}{'='*60}")
print("TEST 1: Import Verification")
print(f"{'='*60}{RESET}\n")

try:
    from app.api.routes.svg_dashboard import router
    ok(f"svg_dashboard route imported — prefix: {router.prefix}")
except Exception as e:
    fail("svg_dashboard route import", e)

try:
    from app.services.svg_dashboard_service import generate_svg_dashboard
    ok("svg_dashboard_service imported")
except Exception as e:
    fail("svg_dashboard_service import", e)

try:
    from dynamic_svg.workflow_parallel import build_mash_workflow
    ok("workflow_parallel imported")
except Exception as e:
    fail("workflow_parallel import", e)

try:
    from dynamic_svg.core.state_manager import StateManager, AgentState
    ok("StateManager imported")
except Exception as e:
    fail("StateManager import", e)


# ─────────────────────────────────────────────
# Test 2: StateManager initialization
# ─────────────────────────────────────────────
print(f"\n{BOLD}{'='*60}")
print("TEST 2: StateManager Initialization")
print(f"{'='*60}{RESET}\n")

sample_data = None
try:
    example_path = BACKEND_DIR / "dynamic_svg" / "example_patientprofile.json"
    with open(example_path, "r") as f:
        content = f.read()

    # Try JSON first, fall back to wrapping plain text
    try:
        sample_data = json.loads(content)
    except json.JSONDecodeError:
        sample_data = {"raw_text": content}
        ok(f"Loaded example as plain text ({len(content)} chars)")

    raw = [sample_data] if isinstance(sample_data, dict) else sample_data
    state = StateManager.initialize_state(raw)
    ok(f"State initialized with {len(state.get('raw_patient_data', []))} data items")
    ok(f"State keys: {list(state.keys())}")
except Exception as e:
    fail("StateManager.initialize_state", e)


# ─────────────────────────────────────────────
# Test 3: Workflow builds without error
# ─────────────────────────────────────────────
print(f"\n{BOLD}{'='*60}")
print("TEST 3: Workflow Build")
print(f"{'='*60}{RESET}\n")

try:
    app = build_mash_workflow()
    ok(f"Workflow compiled successfully — type: {type(app).__name__}")
except Exception as e:
    fail("build_mash_workflow()", e)


# ─────────────────────────────────────────────
# Test 4: HTTP endpoint check (requires running server)
# ─────────────────────────────────────────────
print(f"\n{BOLD}{'='*60}")
print("TEST 4: HTTP Endpoint Availability (requires server on :8000)")
print(f"{'='*60}{RESET}\n")

try:
    import httpx

    with httpx.Client(base_url="http://localhost:8000", timeout=5.0) as client:
        # Check OpenAPI
        r = client.get("/openapi.json")
        if r.status_code == 200:
            paths = r.json().get("paths", {})
            svg_routes = [p for p in paths if "svg-dashboard" in p]
            ok(f"Server is up — found {len(svg_routes)} svg-dashboard routes: {svg_routes}")
        else:
            fail(f"OpenAPI returned {r.status_code}")

        # Test POST /svg-dashboard/generate with sample data
        print(f"\n  {YELLOW}⏳ Sending test request to POST /svg-dashboard/generate ...{RESET}")
        print(f"  {YELLOW}   (This runs the full AI pipeline — may take 30-120s){RESET}")

        answer = input(f"\n  {BOLD}Run the full pipeline test? [y/N]: {RESET}").strip().lower()
        if answer == "y":
            payload = sample_data if isinstance(sample_data, dict) else {"data": sample_data}
            if payload is None:
                payload = {"raw_text": "test"}
            r = client.post(
                "/svg-dashboard/generate",
                json=payload,
                timeout=300.0,
            )
            if r.status_code == 200:
                result = r.json()
                svg_size = result.get("svg_size_chars", 0)
                exec_time = result.get("execution_time_seconds", 0)
                status = result.get("approval_status", "Unknown")
                ok(f"Pipeline completed! SVG: {svg_size:,} chars, Time: {exec_time}s, Status: {status}")

                # Save the SVG for visual inspection
                svg_code = result.get("svg_code", "")
                if svg_code:
                    out_path = BACKEND_DIR / "tests" / "test_output_dashboard.svg"
                    with open(out_path, "w") as f:
                        f.write(svg_code)
                    ok(f"SVG saved to: {out_path}")
            else:
                fail(f"Pipeline returned {r.status_code}: {r.text[:200]}")
        else:
            print(f"  {YELLOW}⏭️  Skipped full pipeline test{RESET}")

except ImportError:
    print(f"  {YELLOW}⚠️  httpx not available — skipping HTTP tests{RESET}")
except httpx.ConnectError:
    fail("Server not running on localhost:8000 — start with: python -m uvicorn app.main:app --reload --port 8000")
except Exception as e:
    fail("HTTP endpoint test", e)


# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
print(f"\n{BOLD}{'='*60}")
print(f"SUMMARY: {GREEN}{passed} passed{RESET}, {RED if failed else GREEN}{failed} failed{RESET}")
print(f"{'='*60}{RESET}\n")

sys.exit(1 if failed else 0)
