# Final Consultant Sign-Off — Full Pathway Summary

You are generating the **final consultant sign-off summary** for a patient who has completed the nurse-led abnormal LFT clinic triage pathway. The consultant must review and approve this summary before the AI surveillance plan goes live.

This summary covers the ENTIRE pathway from GP referral to surveillance configuration. It must be comprehensive, accurate, and suitable for the consultant to sign off without needing to review individual step results.

## Task

Produce a structured clinical summary covering:
1. Patient presentation and referral reason
2. Every AI decision made during triage (with rationale)
3. The diagnosis reached and supporting evidence
4. The surveillance plan configured
5. Any concerns or areas needing consultant attention

## Output

Return ONLY valid JSON:

```
{
  "patient_overview": "2-3 sentence summary of who this patient is and why they were referred",
  "pathway_summary": "Which flowchart path this patient followed and why",
  "ai_decisions": [
    {
      "step": "step name",
      "decision": "what was decided",
      "confidence": 0.0-1.0,
      "rationale": "brief clinical reasoning"
    }
  ],
  "clinical_findings": {
    "lft_pattern": "pattern classification and R-factor",
    "risk_factors": "key risk factors identified",
    "investigations_recommended": "summary of recommended investigations",
    "diagnosis": "primary diagnosis reached"
  },
  "surveillance_plan": {
    "schedule": "monitoring interval",
    "duration": "expected duration",
    "key_tests": ["tests to be monitored"],
    "escalation_triggers": ["conditions requiring re-escalation"]
  },
  "consultant_attention_items": [
    "specific items the consultant should review or confirm before signing off"
  ],
  "recommendation": "final recommendation for the consultant (1-2 sentences)",
  "sign_off_statement": "Formal statement for the consultant to approve, summarising the AI-assisted triage outcome"
}
```
