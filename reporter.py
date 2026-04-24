from fpdf import FPDF

def create_pdf_report(dq_results, bias_score):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, "Governance-Sentinel Audit Report", ln=True, align='C')
    pdf.set_font("Arial", size=12)
    pdf.ln(10)
    pdf.cell(200, 10, "1. BCBS 239 DQ Audit:", ln=True)
    for dim, status in dq_results.items():
        pdf.cell(200, 10, f"- {dim}: {'PASS' if status else 'FAIL'}", ln=True)
    pdf.ln(5)
    pdf.cell(200, 10, f"2. AI Bias Score: {bias_score:.2f}", ln=True)
    pdf.output("Audit_Report.pdf")