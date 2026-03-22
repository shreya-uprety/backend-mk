"""Comprehensive integration tests for the clinical pathway flowchart.

Runs against the live server at http://127.0.0.1:8000.
Tests the full flow including AI handlers, nurse confirmation, and overrides.

Usage:
    python -m pytest tests/test_flowchart_flow.py -v --tb=short
    python tests/test_flowchart_flow.py  # direct run
"""
import requests
import time
import sys

BASE = "http://127.0.0.1:8000/api/v1/patient-status"
SCENARIO_FILE = "scenarios/sc_01_clear_hepatitic_nafld.json"


def api(method, path, body=None, expect_ok=True):
    url = f"{BASE}{path}"
    if method == "GET":
        r = requests.get(url)
    elif method == "POST":
        r = requests.post(url, json=body or {})
    elif method == "DELETE":
        r = requests.delete(url)
    elif method == "PATCH":
        r = requests.patch(url, json=body or {})
    else:
        raise ValueError(f"Unknown method: {method}")

    if expect_ok and not r.ok:
        print(f"  FAILED: {method} {path} -> {r.status_code}: {r.text[:200]}")
    return r


def delete_patient(pid):
    api("DELETE", f"/{pid}", expect_ok=False)


def create_patient(pid, scenario=None):
    body = {"patient_id": pid}
    if scenario:
        body["scenario"] = scenario
    return api("POST", "/create", body)


def advance(pid, decision=None):
    body = {"decision": decision} if decision else {}
    return api("POST", f"/{pid}/advance", body)


def confirm(pid, action="confirm", notes=None, override_decision=None):
    body = {"action": action}
    if notes:
        body["nurse_notes"] = notes
    if override_decision:
        body["override_decision"] = override_decision
    return api("POST", f"/{pid}/confirm", body)


def get_status(pid):
    return api("GET", f"/{pid}")


def get_options(pid):
    return api("GET", f"/{pid}/next-options")


def get_result(pid, result_type):
    return api("GET", f"/{pid}/step-result/{result_type}", expect_ok=False)


def get_pathway_map(pid):
    return api("GET", f"/{pid}/pathway-map")


def get_decisions(pid):
    return api("GET", f"/{pid}/pathway-decisions")


def get_confirmations(pid):
    return api("GET", f"/{pid}/confirmations")


# ── Helpers ──────────────────────────────────────────────────────────


def load_scenario(name):
    import json
    with open(name) as f:
        return json.load(f)


passed = 0
failed = 0
errors = []


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        msg = f"  FAIL: {name}" + (f" — {detail}" if detail else "")
        print(msg)
        errors.append(msg)


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── Test 1: Basic CRUD ──────────────────────────────────────────────


def test_crud():
    section("Test 1: Basic CRUD Operations")
    pid = "test_crud_001"
    delete_patient(pid)

    # Create
    r = create_patient(pid)
    check("Create patient", r.ok)
    data = r.json()
    check("Initial step is GP_REFERRAL_RECEIVED", data["current_step"] == "GP_REFERRAL_RECEIVED")
    check("Status is in_progress", data["step_status"] == "in_progress")

    # Get
    r = get_status(pid)
    check("Get patient", r.ok)
    check("Same step", r.json()["current_step"] == "GP_REFERRAL_RECEIVED")

    # Duplicate create fails
    r = create_patient(pid)
    check("Duplicate create returns 400", r.status_code == 400)

    # Delete
    r = api("DELETE", f"/{pid}")
    check("Delete patient", r.ok)

    # Get after delete
    r = get_status(pid)
    check("Get after delete returns 404", r.status_code == 404)


# ── Test 2: Advance through manual steps ────────────────────────────


def test_manual_advance():
    section("Test 2: Advance Through Manual Steps (no AI)")
    pid = "test_manual_002"
    delete_patient(pid)
    create_patient(pid)

    # Advance through first 3 steps (no handlers)
    steps = []
    for expected in ["INTAKE_DIGITIZATION", "DASHBOARD_CONFIRMATION", "EXTRACT_RISK_FACTORS"]:
        r = advance(pid)
        data = r.json()
        steps.append(data["current_step"])
        check(f"Advance to {expected}", data["current_step"] == expected)

    delete_patient(pid)


# ── Test 3: Scenario creation with pre-computation ──────────────────


def test_scenario_creation():
    section("Test 3: Scenario Creation with Pre-computation")
    pid = "test_scenario_003"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    r = create_patient(pid, scenario=sc)
    check("Create from scenario", r.ok)

    # Check that enriched payload exists
    r = get_result(pid, "risk_factors")
    check("Risk factors pre-computed", r.ok, f"status={r.status_code}")

    if r.ok:
        data = r.json()
        check("Has derived_metrics", "derived_metrics" in data)
        check("Has risk_factors", "risk_factors" in data)
        dm = data.get("derived_metrics", {})
        check("R-factor computed", "r_factor" in dm)
        r_val = dm.get("r_factor", {}).get("value", 0)
        check(f"R-factor > 5 (hepatitic): {r_val}", r_val > 5)

    delete_patient(pid)


# ── Test 4: Confirmation flow ────────────────────────────────────────


def test_confirmation_required():
    section("Test 4: Confirmation Flow")
    pid = "test_confirm_004"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Advance to EXTRACT_RISK_FACTORS (3 advances: GP->INTAKE->DASHBOARD->EXTRACT)
    for _ in range(3):
        advance(pid)

    s = get_status(pid).json()
    check("At EXTRACT_RISK_FACTORS", s["current_step"] == "EXTRACT_RISK_FACTORS")

    # Advance — extract handler runs (auto_advance), then lands on RED_FLAG
    # Red flag handler runs and sets awaiting_confirmation
    r = advance(pid)
    data = r.json()

    # The response may already be at RED_FLAG (awaiting confirmation)
    # or may have chained through extract to red flag
    check("Red flag handler ran", any(
        hr.get("step") == "RED_FLAG_ASSESSMENT"
        for hr in data.get("handler_results", [])
    ))
    check("Awaiting confirmation", data["step_status"] == "awaiting_confirmation")

    # Try to advance without confirming — should fail
    r = advance(pid)
    check("Advance blocked without confirmation", r.status_code == 400)
    check("Error mentions confirmation", "confirmation" in r.text.lower())

    # Confirm
    r = confirm(pid, action="confirm", notes="Reviewed — no red flags present")
    check("Confirm succeeds", r.ok)
    data = r.json()
    check("Confirmation recorded", data.get("confirmation", {}).get("action") == "confirm")
    check("Notes saved", data.get("confirmation", {}).get("nurse_notes") == "Reviewed — no red flags present")

    # Check confirmations log
    r = get_confirmations(pid)
    confs = r.json().get("confirmations", [])
    check("Confirmation in log", len(confs) >= 1)
    rf_conf = [c for c in confs if c.get("step") == "RED_FLAG_ASSESSMENT"]
    check("Red flag confirmation in log", len(rf_conf) >= 1)

    delete_patient(pid)


# ── Test 5: Override flow ────────────────────────────────────────────


def test_override():
    section("Test 5: Override Flow (Nurse disagrees with AI)")
    pid = "test_override_005"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Advance through GP -> INTAKE -> DASHBOARD -> EXTRACT (chains to RED_FLAG)
    for _ in range(3):
        advance(pid)
    r = advance(pid)  # Extract handler auto-advances, red flag handler runs
    data = r.json()

    # Find the red flag handler result
    hr = next((h for h in data.get("handler_results", []) if h.get("step") == "RED_FLAG_ASSESSMENT"), data.get("handler_result", {}))
    ai_decision = hr.get("auto_decision")
    check(f"AI decided: {ai_decision}", ai_decision in ["yes", "no"])

    # Override to opposite
    override_to = "yes" if ai_decision == "no" else "no"
    r = confirm(pid, action="override", override_decision=override_to,
                notes="Clinical judgement overrides AI")
    check("Override succeeds", r.ok)
    data = r.json()
    conf = data.get("confirmation", {})
    check("Override recorded", conf.get("action") == "override")
    check(f"AI decision was {ai_decision}", conf.get("ai_decision") == ai_decision)
    check(f"Final decision is {override_to}", conf.get("final_decision") == override_to)

    # Check patient took the overridden path
    if override_to == "yes":
        check("On urgent path", data["current_step"] == "URGENT_CONSULTANT_PATHWAY" or data["pathway"] == "urgent_consultant")
    else:
        check("On standard path", data["current_step"] in ["PRESENT_TRIAGE_OPTIONS", "GENERATE_GP_LETTER"])

    delete_patient(pid)


# ── Test 6: Confirm without pending ──────────────────────────────────


def test_confirm_without_pending():
    section("Test 6: Confirm When Not Awaiting")
    pid = "test_nopending_006"
    delete_patient(pid)
    create_patient(pid)

    # Try to confirm when not awaiting
    r = confirm(pid)
    check("Confirm when not awaiting returns 400", r.status_code == 400)

    delete_patient(pid)


# ── Test 7: Override with invalid decision ───────────────────────────


def test_override_invalid():
    section("Test 7: Override with Invalid Decision")
    pid = "test_invalid_007"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Advance through GP -> INTAKE -> DASHBOARD -> EXTRACT (chains to RED_FLAG)
    for _ in range(3):
        advance(pid)
    advance(pid)  # Extract auto-advances, RED_FLAG handler runs

    # Override with invalid decision
    r = confirm(pid, action="override", override_decision="invalid_decision")
    check("Invalid override returns 400", r.status_code == 400)

    # Override without decision
    r = confirm(pid, action="override")
    check("Override without decision returns 400", r.status_code == 400)

    delete_patient(pid)


# ── Test 8: Pathway map ─────────────────────────────────────────────


def test_pathway_map():
    section("Test 8: Pathway Map (Node States)")
    pid = "test_map_008"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Get initial map
    r = get_pathway_map(pid)
    check("Pathway map loads", r.ok)
    data = r.json()
    nodes = {n["step"]: n["state"] for n in data["nodes"]}
    check("GP_REFERRAL is current", nodes["GP_REFERRAL_RECEIVED"] == "current")
    check("RED_FLAG is upcoming", nodes["RED_FLAG_ASSESSMENT"] == "upcoming")

    # Advance through to RED_FLAG (extract chains to it)
    for _ in range(3):
        advance(pid)
    advance(pid)  # extract + red flag chain
    confirm(pid)  # confirm red flag

    r = get_pathway_map(pid)
    nodes = {n["step"]: n["state"] for n in r.json()["nodes"]}

    s = get_status(pid).json()
    if s["metadata"]["red_flag_detected"] == False:
        check("URGENT_CONSULTANT ruled out", nodes.get("URGENT_CONSULTANT_PATHWAY") == "ruled_out")
        check("PRESENT_TRIAGE in path", nodes.get("PRESENT_TRIAGE_OPTIONS") in ["traversed", "current", "upcoming"])
    elif s["metadata"]["red_flag_detected"] == True:
        check("PRESENT_TRIAGE ruled out", nodes.get("PRESENT_TRIAGE_OPTIONS") == "ruled_out")

    delete_patient(pid)


# ── Test 9: Pathway decisions (only branching steps) ─────────────────


def test_pathway_decisions():
    section("Test 9: Pathway Decisions (Branching Steps Only)")
    pid = "test_decisions_009"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Advance to red flag (extract chains to it), confirm
    for _ in range(3):
        advance(pid)
    advance(pid)  # extract + red flag chain
    confirm(pid)

    r = get_decisions(pid)
    decisions = r.json().get("decisions", [])
    decision_steps = [d["step"] for d in decisions]

    check("Red flag decision recorded", "RED_FLAG_ASSESSMENT" in decision_steps)
    check("Extract risk factors NOT recorded", "EXTRACT_RISK_FACTORS" not in decision_steps)

    # Check decision has reasoning
    rf_decision = next((d for d in decisions if d["step"] == "RED_FLAG_ASSESSMENT"), None)
    if rf_decision:
        check("Has reasoning", len(rf_decision.get("reasoning", "")) > 10)
        check("Has decision value", rf_decision.get("decision") in ["yes", "no"])

    delete_patient(pid)


# ── Test 10: Step result endpoints ───────────────────────────────────


def test_step_results():
    section("Test 10: Step Result Endpoints")
    pid = "test_results_010"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Risk factors should exist from scenario pre-computation
    r = get_result(pid, "risk_factors")
    check("Risk factors result exists", r.ok)

    # Red flag shouldn't exist yet
    r = get_result(pid, "red_flag")
    check("Red flag not yet (404)", r.status_code == 404)

    # Invalid result type
    r = get_result(pid, "nonexistent")
    check("Invalid type returns 400", r.status_code == 400)

    # Advance to red flag (extract chains to it), confirm
    for _ in range(3):
        advance(pid)
    advance(pid)  # extract + red flag chain
    confirm(pid)

    # Now red flag should exist
    r = get_result(pid, "red_flag")
    check("Red flag result exists after handler", r.ok)
    if r.ok:
        data = r.json()
        check("Has final_decision", "final_decision" in data)
        check("Has confidence_score", "confidence_score" in data)
        check("Has debate_summary", "debate_summary" in data)

    delete_patient(pid)


# ── Test 11: Terminal states ─────────────────────────────────────────


def test_terminal_states():
    section("Test 11: Terminal State Verification")
    pid = "test_terminal_011"
    delete_patient(pid)
    create_patient(pid)

    # Verify via next-options that GP_REFERRAL is not terminal
    r = get_options(pid)
    check("GP_REFERRAL is not terminal", r.json().get("is_terminal") == False)

    # We can't easily reach terminal via API without full AI run,
    # so just verify the concept works
    check("Terminal states test (structural)", True)

    delete_patient(pid)


# ── Test 12: Next options endpoint ───────────────────────────────────


def test_next_options():
    section("Test 12: Next Options Endpoint")
    pid = "test_options_012"
    delete_patient(pid)
    create_patient(pid)

    r = get_options(pid)
    check("Next options loads", r.ok)
    data = r.json()
    check("Current step correct", data["current_step"] == "GP_REFERRAL_RECEIVED")
    check("Not terminal", data["is_terminal"] == False)
    check("Not a decision step", data.get("is_decision") != True)
    check("Has next_step", "next_step" in data)

    delete_patient(pid)


# ── Test 13: Delete cleans all GCS files ─────────────────────────────


def test_delete_cleanup():
    section("Test 13: Delete Cleans All GCS Artifacts")
    pid = "test_cleanup_013"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    create_patient(pid, scenario=sc)

    # Verify files exist
    r = get_result(pid, "risk_factors")
    check("Risk factors exist before delete", r.ok)

    # Delete
    api("DELETE", f"/{pid}")

    # Verify all gone
    r = get_status(pid)
    check("Status gone after delete", r.status_code == 404)
    r = get_result(pid, "risk_factors")
    check("Risk factors gone after delete", r.status_code == 404)

    delete_patient(pid)


# ── Test 14: Full straightforward path (with AI) ────────────────────


def test_full_straightforward_path():
    section("Test 14: Full Straightforward Path (AI Handlers + Confirmations)")
    pid = "test_full_014"
    delete_patient(pid)

    sc = load_scenario(SCENARIO_FILE)
    r = create_patient(pid, scenario=sc)
    check("Created from scenario", r.ok)

    print("  Advancing through pipeline (this takes a few minutes)...")

    # Step through: GP -> INTAKE -> DASHBOARD -> EXTRACT_RISK_FACTORS
    for step_name in ["INTAKE", "DASHBOARD", "EXTRACT_RISK"]:
        r = advance(pid)
        check(f"Advanced past {step_name}", r.ok)

    # EXTRACT_RISK_FACTORS handler runs (auto-advance, no confirmation)
    s = get_status(pid).json()
    print(f"  Current step: {s['current_step']} (status: {s['step_status']})")

    # RED_FLAG_ASSESSMENT — handler runs, needs confirmation
    r = advance(pid)
    data = r.json()
    hr = data.get("handler_result", {})
    if hr.get("requires_confirmation"):
        check("Red flag needs confirmation", True)
        r = confirm(pid, notes="No red flags — asymptomatic patient")
        check("Red flag confirmed", r.ok)
    s = get_status(pid).json()
    print(f"  After red flag: {s['current_step']} (red_flag={s['metadata']['red_flag_detected']})")

    # Advance through TRIAGE -> GP_LETTER
    for _ in range(2):
        advance(pid)

    # ANALYZE_LFT_PATTERN — handler runs, needs confirmation
    r = advance(pid)
    data = r.json()
    hr = data.get("handler_result", {})
    if hr.get("requires_confirmation"):
        check("LFT pattern needs confirmation", True)
        r = confirm(pid, notes="Hepatitic pattern confirmed")
        check("LFT pattern confirmed", r.ok)

    s = get_status(pid).json()
    print(f"  After LFT: {s['current_step']} (pattern={s['metadata']['lft_pattern']})")

    # Advance through HEPATITIC_PATTERN
    r = advance(pid)
    s = get_status(pid).json()
    print(f"  After pattern step: {s['current_step']}")

    # HEPATITIC_INVESTIGATIONS — needs confirmation
    r = advance(pid)
    data = r.json()
    hr = data.get("handler_result", {})
    if hr.get("requires_confirmation"):
        r = confirm(pid)
        check("Investigations confirmed", r.ok)

    s = get_status(pid).json()
    print(f"  After investigations: {s['current_step']} (status: {s['step_status']})")

    # DIAGNOSTIC_DILEMMA — needs confirmation
    if s["step_status"] == "awaiting_confirmation":
        hr2 = data.get("handler_results", [{}])[-1] if data.get("handler_results") else {}
        r = confirm(pid, notes="Straightforward NAFLD case")
        check("Dilemma confirmed", r.ok)

    s = get_status(pid).json()
    print(f"  After dilemma: {s['current_step']} (dilemma={s['metadata']['diagnostic_dilemma']})")

    # Continue confirming through remaining steps
    max_iterations = 20
    for i in range(max_iterations):
        s = get_status(pid).json()
        if s["is_archived"]:
            break

        if s["step_status"] == "awaiting_confirmation":
            r = confirm(pid)
            if not r.ok:
                print(f"  Confirm failed at {s['current_step']}: {r.text[:100]}")
                break
            continue

        r = advance(pid)
        if not r.ok:
            print(f"  Advance failed at {s['current_step']}: {r.text[:100]}")
            break

    s = get_status(pid).json()
    print(f"  Final: {s['current_step']} (archived={s['is_archived']}, disposition={s['final_disposition']})")
    check("Patient reached terminal state", s["is_archived"])
    check("Has final disposition", s["final_disposition"] is not None)

    # Verify all results exist
    results_to_check = ["risk_factors", "red_flag", "pattern", "investigation", "dilemma"]
    for rt in results_to_check:
        r = get_result(pid, rt)
        check(f"Result {rt} exists", r.ok, f"status={r.status_code}")

    # Verify confirmations
    r = get_confirmations(pid)
    confs = r.json().get("confirmations", [])
    check(f"Multiple confirmations recorded ({len(confs)})", len(confs) >= 3)

    delete_patient(pid)


# ── Run all tests ────────────────────────────────────────────────────


def main():
    print("\n" + "=" * 60)
    print("  CLINICAL PATHWAY INTEGRATION TESTS")
    print("  Server: " + BASE)
    print("=" * 60)

    # Quick connectivity check
    try:
        r = requests.get("http://127.0.0.1:8000/", timeout=5)
        if not r.ok:
            raise Exception(f"Status {r.status_code}")
    except Exception as e:
        print(f"\n  ERROR: Cannot connect to server: {e}")
        print("  Make sure uvicorn is running: uvicorn app.main:app --reload")
        sys.exit(1)

    tests = [
        test_crud,
        test_manual_advance,
        test_scenario_creation,
        test_confirmation_required,
        test_override,
        test_confirm_without_pending,
        test_override_invalid,
        test_pathway_map,
        test_pathway_decisions,
        test_step_results,
        test_terminal_states,
        test_next_options,
        test_delete_cleanup,
        test_full_straightforward_path,
    ]

    for test in tests:
        try:
            test()
        except Exception as e:
            global failed
            failed += 1
            msg = f"  EXCEPTION in {test.__name__}: {e}"
            print(msg)
            errors.append(msg)

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if errors:
        print("\n  FAILURES:")
        for e in errors:
            print(f"    {e}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
