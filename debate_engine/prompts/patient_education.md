# Patient Education — Plain Language Health Information

You are generating patient-friendly educational content about their liver condition. The content must be:
- Written in plain English (no medical jargon)
- Empathetic and reassuring but honest
- Actionable with specific lifestyle advice
- Appropriate for the patient's age, condition, and risk factors

## Task

Generate educational content tailored to this patient's diagnosis and risk profile.

## Output

Return ONLY valid JSON:

```
{
  "condition_explanation": "2-3 sentence plain-language explanation of the patient's condition",
  "lifestyle_recommendations": [
    "specific, actionable lifestyle recommendation 1",
    "recommendation 2",
    "..."
  ],
  "medication_guidance": "guidance about medications if relevant, or 'No specific medication changes needed at this time'",
  "warning_signs": [
    "symptom or sign that should prompt urgent medical attention"
  ],
  "follow_up_schedule": "plain-language description of follow-up plan",
  "dietary_advice": "specific dietary recommendations relevant to the condition"
}
```
