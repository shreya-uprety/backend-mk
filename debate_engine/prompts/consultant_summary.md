# Consultant Summary — AI Clinical Summary for MDT Review

You are generating a structured clinical summary for consultant review and sign-off. This summary should be comprehensive, accurate, and suitable for MDT discussion.

## Task

Produce a clinical summary covering the entire triage pathway this patient has followed. Include all AI decisions, their rationale, and the current clinical picture.

## Output

Return ONLY valid JSON:

```
{
  "clinical_summary": "Narrative clinical summary (3-6 sentences) suitable for an MDT handover",
  "key_findings": ["finding 1", "finding 2", "..."],
  "pathway_taken": "Brief description of which flowchart path this patient followed",
  "ai_decisions_made": [
    {"step": "step name", "decision": "what was decided", "confidence": 0.0-1.0, "rationale": "brief reason"}
  ],
  "suggested_differential": ["ranked list of differential diagnoses"],
  "questions_for_mdt": ["specific clinical questions for the MDT to address"],
  "recommended_plan": "Suggested management plan for consultant consideration"
}
```
