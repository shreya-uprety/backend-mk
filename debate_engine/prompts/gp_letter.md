# GP Acknowledgement Letter

You are generating a formal GP acknowledgement letter for the nurse-led abnormal LFT clinic. This letter acknowledges receipt of the GP referral, summarises the initial assessment findings, and outlines the clinic's next steps.

## Task

Generate a professional GP letter based on the patient's data and initial assessment findings.

## Output

Return ONLY valid JSON:

```
{
  "letter_date": "today's date in DD/MM/YYYY format",
  "gp_salutation": "Dear Dr [GP name if available, otherwise 'Dear Doctor']",
  "patient_name": "patient's full name",
  "patient_dob": "patient's date of birth",
  "patient_nhs": "NHS number if available",
  "subject_line": "Re: Abnormal Liver Function Tests — [Patient Name]",
  "opening_paragraph": "Thank you for referring [patient name]... 2-3 sentences acknowledging the referral and reason",
  "assessment_summary": "2-4 sentences summarising the initial risk factor assessment, R-factor, LFT pattern, and key findings from the triage",
  "plan_paragraph": "2-3 sentences outlining what the clinic will do next — investigations, follow-up timeline, expected pathway",
  "closing_paragraph": "1-2 sentences with standard closing — will keep GP updated, contact details for queries",
  "signatory": "Nurse-Led Abnormal LFT Clinic, [Hospital Name]",
  "cc": "Patient's medical records"
}
```
