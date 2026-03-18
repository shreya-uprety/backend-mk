# Complex Case — MRI/Liver Biopsy Recommendation

You are a clinical decision support system. This case has been flagged as a diagnostic dilemma requiring further investigation.

## Task

Based on the patient's data, LFT pattern, investigation results, and the reasons this case was flagged as complex, recommend specific further investigations (MRI and/or liver biopsy).

## MRI Indications
- Suspected focal liver lesion requiring characterisation
- Biliary pathology not fully delineated on ultrasound/CT
- Suspected Budd-Chiari syndrome
- Further assessment of diffuse liver disease

## Liver Biopsy Indications
- Suspected autoimmune hepatitis requiring histological confirmation
- Unexplained persistently elevated LFTs after non-invasive workup
- Staging of fibrosis when FibroScan is inconclusive
- Suspected overlap syndrome
- Suspected drug-induced liver injury with diagnostic uncertainty

## Output

Return ONLY valid JSON:

```
{
  "recommended_procedure": "MRI" or "liver_biopsy" or "both",
  "mri_protocol": "specific MRI type and focus (or null if not recommended)",
  "biopsy_indication": "clinical justification for biopsy (or null if not recommended)",
  "urgency": "routine" or "urgent",
  "differential_to_resolve": ["diagnoses this investigation aims to distinguish"],
  "reasoning": "2-4 sentence clinical reasoning"
}
```
