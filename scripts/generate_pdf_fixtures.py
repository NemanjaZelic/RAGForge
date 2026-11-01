"""Generate original deterministic PDF fixtures, never user documents."""

import io
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "pdf"


def generate() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / "structured.pdf"
    pdf = canvas.Canvas(str(target), pagesize=(595, 842), invariant=1, pageCompression=1)
    pdf.setTitle("RAGForge original PDF fixture")
    pdf.setAuthor("RAGForge test suite")
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(55, 785, "Transactions and recovery")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(55, 750, "A failed transaction rolls back all writes.")
    pdf.drawString(55, 731, "The connection remains usable after rollback.")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(55, 680, "Configuration table")
    for y, key, value in [
        (650, "Setting", "Value"),
        (625, "retry_limit", "3"),
        (600, "timeout_seconds", "30"),
    ]:
        pdf.setFont("Helvetica", 11)
        pdf.drawString(65, y, key)
        pdf.drawString(305, y, value)
        pdf.line(55, y - 8, 480, y - 8)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(55, 540, "Code example")
    pdf.setFont("Courier", 11)
    for y, line in [
        (511, "try:"),
        (493, "    transaction.commit()"),
        (475, "except ConflictError:"),
        (457, "    transaction.rollback()"),
    ]:
        pdf.drawString(55, y, line)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(55, 35, "Printed label i - physical PDF page 1")
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(55, 785, "Columns and deployment")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(55, 735, "Local mode")
    pdf.drawString(320, 735, "Shared mode")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(55, 704, "Local mode needs no server.")
    pdf.drawString(55, 685, "Read the index from disk.")
    pdf.drawString(320, 704, "Shared mode needs authentication.")
    pdf.drawString(320, 685, "Keep collection access isolated.")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(55, 35, "Printed label ii - physical PDF page 2")
    pdf.save()
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 60), "Raster-only evidence: OCR is deferred.", fill="black", font_size=28)
    raster = io.BytesIO()
    image.save(raster, format="PNG")
    raster.seek(0)
    pdf = canvas.Canvas(str(ROOT / "image-only.pdf"), pagesize=(595, 842), invariant=1)
    pdf.drawImage(ImageReader(raster), 45, 450, width=505, height=168)
    pdf.save()
    writer = PdfWriter()
    for name in ("structured.pdf", "image-only.pdf"):
        for page in PdfReader(ROOT / name).pages:
            writer.add_page(page)
    writer.write(ROOT / "mixed.pdf")


if __name__ == "__main__":
    generate()
