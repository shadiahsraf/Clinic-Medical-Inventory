"""Barcode generation, printing (single & sheet labels), and Code128 decoding."""
import os
import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.barcode.code128 import Code128
from .exports import _font, ar


def decode_code128_symbols(symbols: list[int]) -> str:
    """Decodes a list of Code128 encoded symbol indices back into text."""
    if not symbols or len(symbols) < 3:
        raise ValueError("Invalid symbol sequence")
    start = symbols[0]
    mode = {103: 'A', 104: 'B', 105: 'C'}.get(start)
    if not mode:
        raise ValueError(f"Unknown start code: {start}")
    out = []
    i = 1
    # symbols[-2] is checksum, symbols[-1] is stop code (106)
    while i < len(symbols) - 2:
        c = symbols[i]
        if mode == 'C':
            if c == 100:
                mode = 'B'
            elif c == 101:
                mode = 'A'
            elif c <= 99:
                out.append(f"{c:02d}")
        elif mode == 'B':
            if c == 99:
                mode = 'C'
            elif c == 101:
                mode = 'A'
            elif c == 98:
                i += 1
                sc = symbols[i]
                out.append(chr(sc + 32) if sc < 64 else chr(sc - 64))
            elif c <= 95:
                out.append(chr(c + 32))
        elif mode == 'A':
            if c == 99:
                mode = 'C'
            elif c == 100:
                mode = 'B'
            elif c <= 95:
                out.append(chr(c + 32) if c < 64 else chr(c - 64))
        i += 1
    return "".join(out)


def verify_code128_encodable(text: str) -> bool:
    try:
        b = Code128(text)
        b.validate()
        b.encode()
        decoded = decode_code128_symbols(b.encoded)
        return decoded == text
    except Exception:
        return False


def get_barcode_drawing(value: str, width: float = 140, height: float = 35):
    """Creates a standard Code128 barcode drawing suitable for USB scanners."""
    drawing = createBarcodeDrawing(
        'Code128',
        value=value,
        barWidth=1.0,
        barHeight=height,
        humanReadable=False
    )
    return drawing


def generate_single_label_pdf(path: str, item: dict, clinic_name: str = "مخزن المستلزمات الطبية"):
    """Generates a compact label (e.g. 70mm x 40mm) for a thermal printer or single sticker."""
    f = _font()
    # 70mm x 45mm in points (1 mm ~ 2.83465 pt)
    w_pt, h_pt = 70 * 2.83465, 45 * 2.83465
    doc = SimpleDocTemplate(
        path, pagesize=(w_pt, h_pt),
        leftMargin=6, rightMargin=6, topMargin=6, bottomMargin=6
    )

    name_style = ParagraphStyle("ln", fontName=f, fontSize=11, alignment=1, leading=14)
    code_style = ParagraphStyle("lc", fontName=f, fontSize=10, alignment=1, leading=13)
    clinic_style = ParagraphStyle("lh", fontName=f, fontSize=8, alignment=1, leading=10, textColor=colors.HexColor("#555555"))

    code_to_encode = item.get("barcode") or item["code"]
    drawing = get_barcode_drawing(code_to_encode, height=28)

    elements = [
        Paragraph(ar(clinic_name), clinic_style),
        Spacer(1, 2),
        Paragraph(ar(item["name"]), name_style),
        Spacer(1, 4),
        drawing,
        Spacer(1, 2),
        Paragraph(f"{item['code']}", code_style)
    ]
    doc.build(elements)


def generate_sheet_labels_pdf(path: str, items: list[dict], copies_per_item: int = 1,
                              clinic_name: str = "مخزن المستلزمات الطبية"):
    """Generates an A4 sheet with 24 labels (3 columns x 8 rows) containing Arabic name, code & barcode."""
    f = _font()
    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18
    )

    name_style = ParagraphStyle("sn", fontName=f, fontSize=9, alignment=1, leading=12)
    code_style = ParagraphStyle("sc", fontName=f, fontSize=8, alignment=1, leading=10)
    clinic_style = ParagraphStyle("sh", fontName=f, fontSize=7, alignment=1, leading=9, textColor=colors.HexColor("#666666"))

    all_labels = []
    for it in items:
        for _ in range(copies_per_item):
            code_to_encode = it.get("barcode") or it["code"]
            drawing = get_barcode_drawing(code_to_encode, height=22)
            cell_elements = [
                Paragraph(ar(clinic_name), clinic_style),
                Spacer(1, 1),
                Paragraph(ar(it["name"]), name_style),
                Spacer(1, 2),
                drawing,
                Spacer(1, 1),
                Paragraph(f"{it['code']}", code_style)
            ]
            all_labels.append(cell_elements)

    # Grid 3 columns
    cols = 3
    table_data = []
    for i in range(0, len(all_labels), cols):
        chunk = all_labels[i:i + cols]
        while len(chunk) < cols:
            chunk.append([])
        # RTL order for columns
        table_data.append(list(reversed(chunk)))

    col_width = (A4[0] - 36) / cols
    t = Table(table_data, colWidths=[col_width] * cols)
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0BEC5")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    doc.build([t])
