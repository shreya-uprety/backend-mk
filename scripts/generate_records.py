import os
import json
# Ensure fpdf is installed: pip install fpdf
from fpdf import FPDF
import re

# =========================================
#  Configuration
# =========================================

OUTPUT_BASE_DIR = "synthetic_medical_records"


# =========================================
#  Professional PDF Generator Class
# =========================================

class MedicalPDF(FPDF):
    """Custom PDF class for professional medical documents."""

    HEADER_BG = (0, 51, 102)       # Dark navy
    HEADER_TEXT = (255, 255, 255)   # White
    ACCENT = (0, 102, 153)         # Teal accent
    LIGHT_BG = (240, 245, 250)     # Light blue-gray for alternating rows
    TEXT_COLOR = (33, 33, 33)       # Near-black
    MUTED = (100, 100, 100)        # Gray for secondary text

    def __init__(self, doc_title="", doc_subtitle=""):
        super().__init__()
        self.doc_title = doc_title
        self.doc_subtitle = doc_subtitle
        self.set_margins(20, 20, 20) # Standard margins

    def header(self):
        # Top accent bar
        self.set_fill_color(*self.HEADER_BG)
        # Full width rect at top
        self.rect(0, 0, 210, 28, 'F')

        # Title
        self.set_text_color(*self.HEADER_TEXT)
        self.set_font("Helvetica", "B", 14)
        self.set_xy(20, 8)
        self.cell(0, 8, self.doc_title, ln=True)

        # Subtitle
        if self.doc_subtitle:
            self.set_font("Helvetica", "", 9)
            self.set_xy(20, 16)
            self.cell(0, 6, self.doc_subtitle)

        # Thin accent line below header
        self.set_draw_color(*self.ACCENT)
        self.set_line_width(0.8)
        self.line(0, 28, 210, 28)
        
        # Reset position for body content
        self.set_xy(20, 35)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*self.MUTED)
        # Page number
        self.cell(0, 10, f"Page {self.page_no()}", align="R")
        # Disclaimer
        self.set_x(20)
        self.cell(0, 10, "CONFIDENTIAL PATIENT RECORD - SYNTHETIC DATA FOR TESTING", align="L")

    # --- Helper functions for content building ---

    def section_heading(self, text, underline=True):
        """Render a colored section heading."""
        self.ln(4)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*self.ACCENT)
        self.cell(0, 7, text, ln=True)
        if underline:
            self.set_draw_color(*self.ACCENT)
            self.set_line_width(0.3)
            # Draw line matching margins
            self.line(self.get_x(), self.get_y(), 210 - self.r_margin, self.get_y())
        self.ln(2)
        self.set_text_color(*self.TEXT_COLOR)

    def body_text(self, text):
        """Render normal body text using multi_cell for wrapping."""
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.TEXT_COLOR)
        # 0 width means extend to right margin
        self.multi_cell(0, 5, text)
        self.ln(1)

    def key_value(self, key, value):
        """Render a key: value pair with a fixed-width label column."""
        key_str = key + ": "
        value_str = str(value)
        label_w = 55  # fixed label column width
        page_w = 210 - self.l_margin - self.r_margin
        value_w = page_w - label_w

        x0 = self.l_margin
        y0 = self.get_y()

        # Draw key (bold)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*self.TEXT_COLOR)
        self.set_xy(x0, y0)
        self.cell(label_w, 6, key_str)

        # Draw value (normal), wrapping within the value column
        self.set_font("Helvetica", "", 10)
        self.set_xy(x0 + label_w, y0)
        self.multi_cell(value_w, 6, value_str)

        # Ensure we end up below whichever column was taller
        y_after_value = self.get_y()
        y_after_key = y0 + 6
        self.set_y(max(y_after_value, y_after_key))

    def render_table(self, headers, rows):
        """Render a specific table format with alternating colored rows."""
        # Calculate column width based on available space and number of columns
        available_width = 210 - self.l_margin - self.r_margin
        col_count = len(headers)
        col_w = available_width / col_count

        # Header row
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(*self.HEADER_BG)
        self.set_text_color(*self.HEADER_TEXT)
        for h in headers:
            # border=0, fill=True, align Center
            self.cell(col_w, 7, h, border=0, fill=True, align="C")
        self.ln()

        # Data rows
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.TEXT_COLOR)
        for i, row in enumerate(rows):
            # Alternate background color
            if i % 2 == 0:
                self.set_fill_color(*self.LIGHT_BG)
            else:
                self.set_fill_color(255, 255, 255)
                
            # Determine max height for this row based on content wrapping
            row_height = 6
            max_lines = 1
            for cell_content in row:
                # rough estimation of lines needed
                lines = int(self.get_string_width(str(cell_content)) / col_w) + 1
                if lines > max_lines: max_lines = lines
            
            current_row_height = row_height * max_lines

            # Save x,y position before rendering row
            x_start = self.get_x()
            y_start = self.get_y()

            # Render cells
            for j, cell_text in enumerate(row):
                 # Set position for current cell
                self.set_xy(x_start + (j * col_w), y_start)
                # Use multi_cell to handle text wrapping within grid
                # fill=True to apply background color
                self.multi_cell(col_w, row_height, str(cell_text), border=0, fill=True, align='L')
            
            # Move to next line below the tallest cell in this row
            self.set_xy(x_start, y_start + current_row_height)

        self.ln(3)

    def info_box(self, text, color="blue"):
        """Render a colored alert/info box."""
        if color == "red":
            bg = (255, 235, 235); border_c = (200, 50, 50)
        elif color == "yellow":
            bg = (255, 250, 230); border_c = (200, 170, 50)
        else:
            bg = (230, 242, 255); border_c = (0, 102, 153)

        self.set_fill_color(*bg)
        self.set_draw_color(*border_c)
        self.set_line_width(0.4)
        
        # Calculate height required
        self.set_font("Helvetica", "", 9)
        available_width = 210 - self.l_margin - self.r_margin - 4 # minus internal padding
        # Rough estimate of lines
        lines = len(text) / (available_width/1.8) 
        box_height = max(15, (int(lines) * 5) + 10)

        x = self.get_x()
        y = self.get_y()
        # Draw background rect
        self.rect(x, y, available_width + 4, box_height, 'DF')
        
        # Write text inside
        self.set_xy(x + 2, y + 3)
        self.set_text_color(*border_c)
        self.multi_cell(available_width, 5, text)
        
        # Reset position below box
        self.set_xy(x, y + box_height + 5)
        self.set_text_color(*self.TEXT_COLOR)

# =========================================
#  Document Builder Functions
# =========================================

def build_patient_profile(pdf, data):
    pdf.section_heading("Demographics")
    for k, v in data["demographics"].items():
        pdf.key_value(k, v)
    pdf.section_heading("Social History")
    for item in data["social_history"]:
        pdf.body_text(" - " + item)
    pdf.section_heading("Lifestyle Factors")
    for item in data["lifestyle"]:
        pdf.body_text(" - " + item)

def build_referral_letter_structured(pdf, data):
    """Builds a referral letter with structured headings."""
    # Header block
    pdf.key_value("To", data["receiving_clinic"])
    pdf.key_value("From", data["referring_physician"])
    pdf.key_value("Date", data["date"])
    pdf.ln(4)

    # Salutation
    pdf.body_text("Dear Colleague,")
    pdf.ln(1)
    pdf.key_value("Re", f"{data['patient_name']}, DOB: {data['patient_dob']}")
    pdf.ln(2)
    pdf.body_text("Thank you for seeing this patient, whom I am referring for specialist hepatology assessment and management.")
    pdf.ln(3)

    # Structured sections
    pdf.section_heading("Reason for Referral", underline=False)
    pdf.body_text(data["reason_for_referral"])
    pdf.ln(1)

    pdf.section_heading("History of Presenting Complaint", underline=False)
    pdf.body_text(data["hpi"])
    pdf.ln(1)

    if data.get("pmhx") and data["pmhx"] != "None relevant.":
        pdf.section_heading("Relevant Past Medical History", underline=False)
        pdf.body_text(data["pmhx"])
        pdf.ln(1)

    pdf.section_heading("Alcohol Intake", underline=False)
    pdf.body_text(data["alcohol_intake"])
    pdf.ln(1)

    if data.get("family_history") and data["family_history"] != "Unknown.":
        pdf.section_heading("Family History", underline=False)
        pdf.body_text(data["family_history"])
        pdf.ln(1)

    pdf.section_heading("Current Medications & Allergies", underline=False)
    pdf.key_value("Medications", data["medications"])
    pdf.key_value("Allergies", data["allergies"])
    pdf.ln(2)

    if data.get("investigations_note"):
        pdf.section_heading("Recent Investigations (Results Attached)", underline=False)
        pdf.body_text(data["investigations_note"])
        pdf.ln(1)

    # Closing
    pdf.ln(4)
    pdf.body_text(data["sign_off"])


def build_questionnaire(pdf, data):
    if data.get("note"):
        pdf.info_box(data["note"], "yellow")
    for q, a in data["qa"]:
        pdf.section_heading(q)
        pdf.body_text(a)

def build_consultation_notes(pdf, data):
    pdf.key_value("Date", data["date"])
    if data.get("time"): pdf.key_value("Time", data["time"])
    pdf.ln(3)
    pdf.section_heading("Chief Complaint")
    pdf.body_text(data["cc"])
    pdf.section_heading("History of Present Illness")
    pdf.body_text(data["hpi"])
    pdf.section_heading("Physical Examination")
    for k, v in data["exam"].items():
        pdf.key_value(k, v)
    pdf.ln(2)
    pdf.section_heading("Assessment")
    pdf.body_text(data["assessment"])

def build_lab_results(pdf, data):
    pdf.key_value("Collection Date", data["date"])
    if data.get("time"): pdf.key_value("Time", data["time"])
    pdf.ln(3)
    for section in data["sections"]:
        pdf.section_heading(section["title"])
        pdf.render_table(section["headers"], section["rows"])

def build_imaging_report(pdf, data):
    pdf.key_value("Date", data["date"])
    if data.get("indication"):
        pdf.ln(2)
        pdf.key_value("Indication", data["indication"])
    pdf.section_heading("Findings")
    for k, v in data["findings"].items():
        pdf.key_value(k, v)
        pdf.ln(1)
    pdf.section_heading("Impression")
    for item in data["impression"]:
        pdf.body_text(" - " + item)

def build_medication_list(pdf, data):
    if data.get("note"):
        pdf.info_box(data["note"], "yellow")
        pdf.ln(3)
    if data.get("current"):
        pdf.section_heading("Current Medications")
        pdf.render_table(["Medication", "Dose", "Frequency", "Indication"], data["current"])
    if data.get("allergies"):
        pdf.section_heading("Allergies")
        for a in data["allergies"]: pdf.body_text(" - " + a)
    if data.get("inpatient"):
        pdf.section_heading("Inpatient Orders")
        for item in data["inpatient"]: pdf.body_text(" - " + item)

def build_vitals(pdf, data):
    pdf.key_value("Date", data["date"])
    if data.get("time"): pdf.key_value("Time", data["time"])
    pdf.ln(3)
    pdf.section_heading("Vital Signs")
    for k, v in data["vitals"].items():
        pdf.key_value(k, v)

def build_assessment_plan(pdf, data):
    pdf.key_value("Patient", data["patient"])
    pdf.ln(3)
    pdf.section_heading("Diagnosis")
    pdf.body_text(data["diagnosis"])
    if data.get("summary"):
        pdf.section_heading("Summary")
        pdf.body_text(data["summary"])
    if data.get("immediate_issues"):
        pdf.section_heading("Immediate Issues")
        for i, issue in enumerate(data["immediate_issues"], 1):
            pdf.body_text(f"{i}. {issue}")
    if data.get("rationale"):
        pdf.section_heading("Rationale for Treatment")
        pdf.body_text(data["rationale"])
    pdf.section_heading("Plan")
    for i, step in enumerate(data["plan"], 1):
        pdf.body_text(f"{i}. {step}")

# =========================================
#  PDF Builder Dispatcher
# =========================================

BUILDERS = {
    "patient_profile": build_patient_profile,
    "referral_letter": build_referral_letter_structured, # Pointed to new structured builder
    "questionnaire": build_questionnaire,
    "consultation_notes": build_consultation_notes,
    "lab_results": build_lab_results,
    "imaging": build_imaging_report,
    "medication_list": build_medication_list,
    "vitals": build_vitals,
    "assessment_plan": build_assessment_plan,
}

def create_pdf(file_path, doc_type, title, subtitle, data):
    # Ensure directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    pdf = MedicalPDF(doc_title=title, doc_subtitle=subtitle)
    pdf.add_page()
    
    builder_func = BUILDERS.get(doc_type)
    if builder_func:
        builder_func(pdf, data)
    else:
        print(f"Warning: No builder found for doc_type '{doc_type}'")
        pdf.body_text(str(data))

    try:
        pdf.output(file_path)
    except Exception as e:
        print(f"Error saving PDF {file_path}: {e}")

# =========================================
#  Data Serialization Helper
# =========================================

def _serialize_data(data):
    """Recursively convert data structures to JSON-safe formats."""
    if isinstance(data, dict):
        return {k: _serialize_data(v) for k, v in data.items() if v is not None}
    if isinstance(data, (list, tuple)):
        return [_serialize_data(item) for item in data]
    # Handle potential non-serializable types if added later (like datetimes)
    return data

# =========================================
#  Patient Case Data (Structured)
# =========================================

patient_cases = [
    # ==================== CASE 1 (p0001 - MASLD) ====================
    {
        "folder": "p0001",
        "files": [
            {
                "filename": "1_patient_profile.pdf",
                "type": "patient_profile",
                "title": "PATIENT PROFILE",
                "subtitle": "Arthur Pendelton  |  DOB: 12/05/1969  |  MRN: MK-0001",
                "data": {
                    "demographics": {
                        "Full Name": "Arthur Pendelton", "Age": "54", "Gender": "Male",
                        "Occupation": "Logistics Manager (Sedentary)", "Height": "178 cm",
                        "Weight": "108 kg", "BMI": "34.1 (Obese Class I)",
                    },
                    "social_history": [
                        "Alcohol: Occasional social use. Max 4 units per week.",
                        "Smoking: Ex-smoker, quit 10 years ago (15 pack-year history).",
                    ],
                    "lifestyle": [
                        "Diet: High intake of processed foods/refined carbs. Irregular meals.",
                        "Exercise: Minimal due to long work hours.",
                    ],
                },
            },
            {
                # REFACTORED STRUCTURE FOR REFERRAL LETTER
                "filename": "2_gp_referral_letter.pdf",
                "type": "referral_letter",
                "title": "GP REFERRAL",
                "subtitle": "Hepatology Services Referral",
                "data": {
                    "referring_physician": "Dr. S. Mehta, Oakwood Family Practice",
                    "receiving_clinic": "Hepatology Department, St. Mary's Hospital",
                    "date": "October 15, 2023",
                    "patient_name": "Arthur Pendelton",
                    "patient_dob": "12/05/1969",
                    # Structured content based on the image format
                    "reason_for_referral": "Evaluation of unexpectedly elevated liver transaminases found during routine insurance medical in a patient with metabolic risk factors, to rule out non-alcoholic fatty liver disease and stage potential fibrosis.",
                    "hpi": "Patient is currently asymptomatic. Denies jaundice, abdominal pain, or fatigue. The issue was found incidentally on routine blood work.",
                    "pmhx": "Type 2 Diabetes Mellitus (diagnosed 3 years ago, poorly controlled, HbA1c 8.2%); Hypertension; Obesity (BMI 34.1).",
                    "alcohol_intake": "Occasional social use only. Denies significant consumption (max 4 units/week).",
                    "family_history": "No known family history of liver disease.",
                    "medications": "Metformin 1000mg BID, Ramipril 10mg OD, Atorvastatin 20mg OD, Fish Oil supplements.",
                    "allergies": "No Known Drug Allergies.",
                    "investigations_note": "Routine bloods attached showing ALT 115 U/L, AST 78 U/L, GGT 145 U/L.",
                    "sign_off": "Sincerely,\nDr. S. Mehta"
                },
            },
            {
                "filename": "3_patient_questionnaire.pdf",
                "type": "questionnaire",
                "title": "PRE-CONSULTATION QUESTIONNAIRE",
                "subtitle": "Arthur Pendelton  |  Self-reported",
                "data": {
                    "note": None,
                    "qa": [
                        ("Main Symptoms", "None really. Maybe feel a bit tired in the afternoons."),
                        ("Alcohol Intake", "< 5 drinks a week total. Beer/wine on weekends."),
                        ("Medications / Supplements", "Metformin, Ramipril, ibuprofen (occasional), multivitamin, fish oil."),
                        ("Family History of Liver Disease", "No."),
                        ("Metabolic Risk Factors", "Yes: Type 2 diabetes, high blood pressure, overweight."),
                    ],
                },
            },
            {
                "filename": "4_consultation_notes.pdf",
                "type": "consultation_notes",
                "title": "HEPATOLOGY CONSULTATION NOTES",
                "subtitle": "Arthur Pendelton  |  Outpatient Clinic",
                "data": {
                    "date": "November 2, 2023", "time": "10:30",
                    "cc": "Elevated liver enzymes on screening.",
                    "hpi": "54M, asymptomatic. Confirms low alcohol use. Reports difficulty managing diet due to work stress.",
                    "exam": {
                        "General": "Well-appearing, obese male.",
                        "Abdomen": "Soft, obese, non-tender. Liver edge palpable 2cm below costal margin, smooth/firm. Spleen not palpable.",
                        "Skin": "No stigmata of chronic liver disease.",
                    },
                    "assessment": "Highly suggestive of MASLD given metabolic syndrome and ALT>AST pattern. Need to stage fibrosis.",
                },
            },
            {
                "filename": "5_liver_lab_results.pdf",
                "type": "lab_results",
                "title": "LIVER BLOOD TEST PANEL",
                "subtitle": "Arthur Pendelton  |  MRN: MK-0001",
                "data": {
                    "date": "October 30, 2023",
                    "sections": [
                        {"title": "Liver Biochemistry", "headers": ["Test", "Result", "Ref Range"], "rows": [
                            ["ALT", "122 U/L", "7-56 (HIGH)"], ["AST", "84 U/L", "10-40 (HIGH)"],
                            ["ALP", "95 U/L", "44-147"], ["GGT", "155 U/L", "9-48 (HIGH)"],
                            ["Bilirubin Tot", "0.9 mg/dL", "0.1-1.2"], ["Albumin", "4.2 g/dL", "3.4-5.4"],
                            ["Platelets", "245 x10^9/L", "150-450"],
                        ]},
                        {"title": "Screening", "headers": ["Test", "Result", ""], "rows": [
                            ["HBsAg", "Negative", ""], ["Anti-HCV", "Negative", ""],
                        ]},
                    ],
                },
            },
            {
                "filename": "6_ultrasound_report.pdf",
                "type": "imaging",
                "title": "DIAGNOSTIC ULTRASOUND - ABDOMEN",
                "subtitle": "Arthur Pendelton",
                "data": {
                    "date": "November 2, 2023",
                    "findings": {
                        "Liver": "Diffusely enlarged (18.5cm). Diffusely increased echogenicity causing posterior attenuation.",
                        "Spleen": "Normal size (11 cm).", "Ascites": "None.",
                    },
                    "impression": ["Severe diffuse hepatic steatosis and hepatomegaly.", "No evidence of cirrhosis."],
                },
            },
            {
                "filename": "7_fibroscan_report.pdf",
                "type": "imaging",
                "title": "TRANSIENT ELASTOGRAPHY (FIBROSCAN)",
                "subtitle": "Arthur Pendelton",
                "data": {
                    "date": "November 2, 2023",
                    "findings": {"LSM (Stiffness)": "8.9 kPa", "CAP (Steatosis)": "365 dB/m", "IQR/Med": "15%"},
                    "impression": ["LSM 8.9 kPa suggests significant fibrosis (F2-F3).", "CAP 365 dB/m indicates severe steatosis (S3)."],
                },
            },
            {
                "filename": "8_medication_list.pdf",
                "type": "medication_list",
                "title": "CURRENT MEDICATIONS",
                "subtitle": "Arthur Pendelton",
                "data": {
                    "current": [
                        ["Metformin", "1000mg", "BID", "T2DM"], ["Ramipril", "10mg", "OD", "HTN"],
                        ["Atorvastatin", "20mg", "OD", "Lipids"],
                    ],
                    "allergies": ["NKDA"],
                },
            },
            {
                "filename": "9_vitals_report.pdf",
                "type": "vitals",
                "title": "CLINIC VITALS",
                "subtitle": "Arthur Pendelton",
                "data": {
                    "date": "November 2, 2023",
                    "vitals": {"BP": "142/88", "HR": "78", "Temp": "36.8 C", "BMI": "34.1"},
                },
            },
            {
                "filename": "10_hepatologist_assessment.pdf",
                "type": "assessment_plan",
                "title": "HEPATOLOGY ASSESSMENT & PLAN",
                "subtitle": "Arthur Pendelton",
                "data": {
                    "patient": "Arthur Pendelton",
                    "diagnosis": "MASLD with severe steatosis and significant fibrosis (F2-F3).",
                    "summary": "54M with metabolic syndrome. Labs show hepatocellular injury. Fibroscan indicates bridging fibrosis likely.",
                    "plan": [
                        "Lifestyle modification (aim 7-10% weight loss). Dietitian referral.",
                        "Optimize T2DM control (discussed GLP-1 with GP).",
                        "Repeat labs/Fibroscan in 6 months.",
                    ],
                },
            },
        ],
    },
    # ==================== CASE 2 (p0002 - Cirrhosis) ====================
    {
        "folder": "p0002",
        "files": [
             {
                "filename": "1_patient_profile.pdf",
                "type": "patient_profile",
                "title": "PATIENT PROFILE",
                "subtitle": "Sarah Jenkins  |  DOB: 04/02/1982  |  MRN: MK-0002",
                "data": {
                    "demographics": {
                        "Full Name": "Sarah Jenkins", "Age": "42", "Gender": "Female",
                        "Occupation": "Unemployed", "Height": "162 cm", "Weight": "55 kg (fluid influenced)",
                    },
                    "social_history": [
                        "Alcohol: Chronic heavy use. ~750ml vodka daily for 8 years.",
                        "Smoking: 1 pack/day.", "Support: Limited, lives alone.",
                    ],
                    "lifestyle": ["Poor nutritional intake; often skips meals for alcohol."],
                },
            },
            {
                # REFACTORED STRUCTURE FOR REFERRAL LETTER
                "filename": "2_gp_referral_letter.pdf",
                "type": "referral_letter",
                "title": "URGENT GP REFERRAL",
                "subtitle": "Priority: Red Flag / Emergency",
                "data": {
                    "referring_physician": "Dr. A. Petrova, City Centre Clinic",
                    "receiving_clinic": "On-Call Hepatologist / Emergency Admissions",
                    "date": "January 10, 2024",
                    "patient_name": "Sarah Jenkins",
                    "patient_dob": "04/02/1982",
                    # Structured content
                    "reason_for_referral": "URGENT evaluation for suspected decompensated alcohol-related liver disease with jaundice, tense ascites, and confusion.",
                    "hpi": "Presented brought by neighbor. Visibly jaundiced and confused. Examination reveals tense abdominal distension. Reports dark urine/pale stools for 1 week.",
                    "pmhx": "None relevant.",
                    "alcohol_intake": "Known history of significant chronic alcohol excess (approx. 1 bottle spirits daily).",
                    "family_history": "Unknown.",
                    "medications": "None known.",
                    "allergies": "Not recorded.",
                    "investigations_note": "Clinic Vitals: BP 100/60, HR 110. Patient sent directly to ED.",
                    "sign_off": "Dr. A. Petrova"
                },
            },
            {
                "filename": "3_patient_questionnaire.pdf",
                "type": "questionnaire",
                "title": "PRE-CONSULTATION QUESTIONNAIRE",
                "subtitle": "Sarah Jenkins  |  Assisted by neighbor",
                "data": {
                    "note": "Filled out with assistance due to patient confusion.",
                    "qa": [
                        ("Main Symptoms", "Belly swollen/tight. Yellow eyes. Foggy/sleepy. Bruising."),
                        ("Alcohol Intake", "Daily \"hard liquor\"."),
                    ],
                },
            },
            {
                "filename": "4_consultation_notes.pdf",
                "type": "consultation_notes",
                "title": "INPATIENT ADMISSION NOTE",
                "subtitle": "Sarah Jenkins  |  Emergency Dept",
                "data": {
                    "date": "January 10, 2024", "time": "14:30",
                    "cc": "Jaundice, ascites, confusion.",
                    "hpi": "42F with heavy alcohol use admits with subacute decompensation. Grade 1-2 hepatic encephalopathy present.",
                    "exam": {
                        "General": "Ill-appearing, sarcopenic, icteric.", "Cardio": "Tachycardic.",
                        "Abdomen": "Grossly distended, tense ascites. Caput medusae. Spleen palpable.",
                        "Skin": "Spider angiomas, palmar erythema, ecchymoses.", "Neuro": "Asterixis positive.",
                    },
                    "assessment": "Decompensated Alcohol-Related Liver Disease (Child-Pugh C).",
                },
            },
            {
                "filename": "5_liver_lab_results.pdf",
                "type": "lab_results",
                "title": "URGENT BLOOD PANEL",
                "subtitle": "Sarah Jenkins  |  MRN: MK-0002",
                "data": {
                    "date": "Jan 10, 2024", "time": "13:00",
                    "sections": [
                        {"title": "Chemistry/Coag", "headers": ["Test", "Result", "Ref Range"], "rows": [
                            ["ALT", "85", "7-56"], ["AST", "210", "10-40"],
                            ["Bilirubin Tot", "8.5 mg/dL", "0.1-1.2 (CRIT)"], ["Albumin", "2.1 g/dL", "3.4-5.4 (LOW)"],
                            ["INR", "2.4", "0.8-1.1 (HIGH)"], ["Creatinine", "1.4 mg/dL", "0.6-1.1"],
                        ]},
                        {"title": "Hematology", "headers": ["Test", "Result", "Ref"], "rows": [
                            ["Platelets", "65", "150-450 (LOW)"], ["Hb", "9.8", "12-15.5"],
                        ]},
                    ],
                },
            },
            {
                "filename": "6_ultrasound_report.pdf",
                "type": "imaging",
                "title": "URGENT ABDOMINAL ULTRASOUND",
                "subtitle": "Sarah Jenkins",
                "data": {
                    "date": "Jan 10, 2024",
                    "findings": {
                        "Liver": "Shrunken, coarse, nodular surface consistent with advanced cirrhosis.",
                        "Portal Vein": "Dilated (15mm), slow flow.", "Spleen": "Enlarged (17.5 cm).",
                        "Abdomen": "Massive free fluid (ascites).",
                    },
                    "impression": ["End-stage liver cirrhosis morphology.", "Significant portal hypertension.", "Massive ascites."],
                },
            },
            {
                "filename": "7_ct_scan_report.pdf",
                "type": "imaging",
                "title": "CT ABDOMEN/PELVIS (CONTRAST)",
                "subtitle": "Sarah Jenkins  |  Day 2 Admission",
                "data": {
                    "date": "Jan 11, 2024", "indication": "Evaluate for HCC and varices.",
                    "findings": {
                        "Liver": "Small, cirrhotic, nodular. No suspicious lesions for HCC.",
                        "Portal System": "Extensive collaterals. Large esophageal/gastric varices.",
                    },
                    "impression": ["Decompensated cirrhosis with varices, splenomegaly, ascites.", "No HCC identified."],
                },
            },
            {
                "filename": "8_medication_list.pdf",
                "type": "medication_list",
                "title": "MEDICATION RECORD",
                "subtitle": "Sarah Jenkins",
                "data": {
                    "note": "No prescribed medications on admission.",
                    "inpatient": ["Thiamine IV TDS", "Lactulose QDS", "Rifaximin BID", "Spironolactone OD (pending renal function)"],
                },
            },
            {
                "filename": "9_vitals_report.pdf",
                "type": "vitals",
                "title": "ADMISSION VITALS",
                "subtitle": "Sarah Jenkins",
                "data": {
                    "date": "Jan 10, 2024", "vitals": {"BP": "98/55 (Hypotensive)", "HR": "108 (Tachy)", "Temp": "37.9 C", "O2 Sat": "94% RA"},
                },
            },
            {
                "filename": "10_hepatologist_assessment.pdf",
                "type": "assessment_plan",
                "title": "HEPATOLOGY IMPRESSION & PLAN",
                "subtitle": "Sarah Jenkins",
                "data": {
                    "patient": "Sarah Jenkins",
                    "diagnosis": "Decompensated Alcohol-Related Cirrhosis (Child-Pugh C, MELD 28).",
                    "immediate_issues": ["Tense Ascites (respiratory compromise)", "Hepatic Encephalopathy (Grade 2)", "Coagulopathy", "AKI (hepatorenal vs dehydration)", "Suspected SBP"],
                    "plan": ["Diagnostic Paracentesis ASAP (rule out SBP).", "Empiric IV antibiotics.", "Lactulose/Rifaximin for HE.", "Hold diuretics pending AKI resolution."],
                },
            },
        ],
    },
    # ==================== CASE 3 (p0003 - Hep B) ====================
    {
        "folder": "p0003",
        "files": [
            {
                "filename": "1_patient_profile.pdf",
                "type": "patient_profile",
                "title": "PATIENT PROFILE",
                "subtitle": "Kenji Tanaka  |  DOB: 15/08/1988  |  MRN: MK-0003",
                "data": {
                    "demographics": {
                        "Full Name": "Kenji Tanaka", "Age": "35", "Gender": "Male",
                        "Occupation": "Software Engineer", "Origin": "Migrated from Japan 5 years ago",
                    },
                    "social_history": ["Alcohol: Rare (<1/month).", "Smoking: Never."],
                    "lifestyle": ["Active, jogs 3x week. Balanced diet."],
                },
            },
            {
                # REFACTORED STRUCTURE FOR REFERRAL LETTER
                "filename": "2_gp_referral_letter.pdf",
                "type": "referral_letter",
                "title": "GP REFERRAL LETTER",
                "subtitle": "Hepatitis B Notification",
                "data": {
                    "referring_physician": "Dr. B. Williams, Downtown Medical Associates",
                    "receiving_clinic": "Hepatology Clinic",
                    "date": "March 1, 2024",
                    "patient_name": "Kenji Tanaka",
                    "patient_dob": "15/08/1988",
                    # Structured content
                    "reason_for_referral": "Management of newly diagnosed, asymptomatic Hepatitis B identified during routine insurance screening.",
                    "hpi": "Patient is asymptomatic. No history of jaundice, RUQ pain, or fatigue. Denies IV drug use.",
                    "pmhx": "None relevant.",
                    "alcohol_intake": "Minimal / Rare.",
                    "family_history": "Uncle died of liver cancer (Japan). Mother's status unknown.",
                    "medications": "None.",
                    "allergies": "Penicillin (rash).",
                    "investigations_note": "Initial screening labs showed HBsAg Positive and mildly elevated ALT (88 U/L). Full viral serology panel pending.",
                    "sign_off": "Sincerely,\nDr. B. Williams"
                },
            },
            {
                "filename": "3_patient_questionnaire.pdf",
                "type": "questionnaire",
                "title": "PRE-CONSULTATION QUESTIONNAIRE",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "qa": [
                        ("Main Symptoms", "None. I feel fine."),
                        ("Family History", "Uncle had liver cancer. Mother might be Hep B carrier."),
                        ("Risk Factors", "Born in Japan. Unsure of childhood vaccination."),
                    ],
                },
            },
            {
                "filename": "4_consultation_notes.pdf",
                "type": "consultation_notes",
                "title": "HEPATOLOGY CLINIC NOTE",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "date": "March 20, 2024",
                    "cc": "Evaluation of Hepatitis B positive status.",
                    "hpi": "35M, asymptomatic HBsAg+. Family history of HCC (uncle).",
                    "exam": {
                        "General": "Healthy appearing male.",
                        "Abdomen": "Soft, non-tender. No hepatosplenomegaly.",
                        "Skin": "No stigmata of chronic liver disease.",
                    },
                    "assessment": "Chronic Hepatitis B, Immune-Active phase (HBsAg+, high ALT). Needs fibrosis staging and consideration for antivirals.",
                },
            },
            {
                "filename": "5_liver_lab_results.pdf",
                "type": "lab_results",
                "title": "HEPATITIS B PANEL & CHEMISTRY",
                "subtitle": "Kenji Tanaka  |  MRN: MK-0003",
                "data": {
                    "date": "March 15, 2024",
                    "sections": [
                        {"title": "Biochemistry", "headers": ["Test", "Result", "Ref"], "rows": [
                            ["ALT", "92", "7-56 (HIGH)"], ["AST", "65", "10-40 (HIGH)"],
                            ["Albumin", "4.5", "3.4-5.4"], ["Platelets", "210", "150-450"],
                        ]},
                        {"title": "Viral Serology", "headers": ["Test", "Result", "Interpretation"], "rows": [
                            ["HBsAg", "POSITIVE", "Active Infection"],
                            ["HBsAb", "NEGATIVE", "No Immunity"],
                            ["HBeAg", "POSITIVE", "High Infectivity"],
                            ["HBV DNA", "2,500,000 IU/mL", "Very High Viral Load"],
                        ]},
                    ],
                },
            },
            {
                "filename": "6_ultrasound_report.pdf",
                "type": "imaging",
                "title": "ABDOMINAL ULTRASOUND",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "date": "March 20, 2024",
                    "findings": {
                        "Liver": "Normal size (14 cm), homogeneous echotexture. smooth contour.",
                        "Spleen": "Normal size (10.5 cm).",
                    },
                    "impression": ["Normal appearance of liver.", "No sonographic evidence of cirrhosis. (Note: US insensitive for early fibrosis)."],
                },
            },
            {
                "filename": "7_fibroscan_report.pdf",
                "type": "imaging",
                "title": "TRANSIENT ELASTOGRAPHY (FIBROSCAN)",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "date": "March 20, 2024",
                    "findings": {"LSM": "7.8 kPa", "CAP": "210 dB/m", "IQR/Med": "12%"},
                    "impression": ["LSM 7.8 kPa suggests moderate fibrosis (F2) in HBV context.", "CAP 210 dB/m is normal (no steatosis)."],
                },
            },
            {
                "filename": "8_medication_list.pdf",
                "type": "medication_list",
                "title": "CURRENT MEDICATIONS",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "note": "No current prescription medications.",
                    "allergies": ["Penicillin (Rash)."],
                },
            },
            {
                "filename": "9_vitals_report.pdf",
                "type": "vitals",
                "title": "CLINIC VITALS",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "date": "March 20, 2024",
                    "vitals": {"BP": "118/76", "HR": "68", "Temp": "36.6 C", "BMI": "22.9"},
                },
            },
            {
                "filename": "10_hepatologist_assessment.pdf",
                "type": "assessment_plan",
                "title": "HEPATOLOGY ASSESSMENT",
                "subtitle": "Kenji Tanaka",
                "data": {
                    "patient": "Kenji Tanaka",
                    "diagnosis": "Chronic Hepatitis B, HBeAg-positive immune-active phase, moderate fibrosis (F2).",
                    "rationale": "Treatment indicated due to active inflammation (elevated ALT), high viral load, F2 fibrosis, and family history of HCC.",
                    "plan": ["Initiate Entecavir 0.5mg daily.", "Counsel on transmission prevention.", "HCC Surveillance (US + AFP every 6 months)."],
                },
            },
        ],
    },
]

# =========================================
#  Main Execution
# =========================================

def generate_datasets():
    print(f"Starting generation in: {OUTPUT_BASE_DIR}")

    for case in patient_cases:
        # Create unstructured (PDF) and structured (JSON) output folders
        pdf_folder = os.path.join(OUTPUT_BASE_DIR, case["folder"], "unstructured_data")
        json_folder = os.path.join(OUTPUT_BASE_DIR, case["folder"], "structured_data")
        os.makedirs(pdf_folder, exist_ok=True)
        os.makedirs(json_folder, exist_ok=True)
        
        print(f"\nProcessing Case: {case['folder']}...")

        for doc in case["files"]:
            # 1. Generate PDF
            pdf_path = os.path.join(pdf_folder, doc["filename"])
            create_pdf(pdf_path, doc["type"], doc["title"], doc["subtitle"], doc["data"])
            print(f"  -> Generated PDF: {doc['filename']}")

            # 2. Generate corresponding JSON (ground truth)
            json_filename = doc["filename"].replace(".pdf", ".json")
            json_path = os.path.join(json_folder, json_filename)
            
            # Construct JSON content (flat format matching original)
            json_content = {
                "document_type": doc["type"],
                "title": doc["title"],
                **_serialize_data(doc["data"]),
            }
            
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(json_content, f, indent=2, ensure_ascii=False)
            except Exception as e:
                 print(f"  !! Error saving JSON {json_filename}: {e}")

    print(f"\nGeneration complete! Output directory: {os.path.abspath(OUTPUT_BASE_DIR)}")

if __name__ == "__main__":
    generate_datasets()