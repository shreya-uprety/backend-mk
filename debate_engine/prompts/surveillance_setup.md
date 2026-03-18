# AI Surveillance Loop — Monitoring Configuration

You are configuring an automated surveillance programme for a patient who requires ongoing LFT monitoring.

## Task

Based on the patient's condition, severity, and monitoring assessment, configure the surveillance schedule and alert parameters.

## Output

Return ONLY valid JSON:

```
{
  "schedule_interval": "3_monthly" or "6_monthly" or "12_monthly",
  "tests_per_visit": ["list of blood tests and investigations to order each visit"],
  "threshold_alerts": [
    "condition that should trigger an alert (e.g., 'ALT > 3x ULN', 'New onset jaundice')"
  ],
  "auto_discharge_criteria": [
    "condition that indicates safe discharge from surveillance (e.g., '2 consecutive normal LFTs 6 months apart')"
  ],
  "next_review_date": "approximate timeframe for first surveillance visit",
  "total_duration": "expected total surveillance duration",
  "reasoning": "2-3 sentence explanation of the surveillance plan"
}
```
