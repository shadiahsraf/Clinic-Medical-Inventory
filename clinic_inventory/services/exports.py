"""Excel (openpyxl) and PDF (ReportLab + arabic_reshaper + bidi) exports."""
import os
import arabic_reshaper
from bidi.algorithm import get_display
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_FONT_NAME = "ArabicFont"
_FONT_CANDIDATES = [  # bundled font first (assets/fonts), then common system fallbacks
    # ReportLab needs a font containing Arabic *presentation forms* (reshaper output);
    # Tajawal/Cairo lack them (they rely on OpenType shaping), so PDFs use DejaVu Sans.
    os.path.join(os.path.dirname(__file__), "..", "assets", "pdf_fonts", "DejaVuSans.ttf"),
    "C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font():
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        for p in _FONT_CANDIDATES:
            if os.path.exists(p):
                pdfmetrics.registerFont(TTFont(_FONT_NAME, p)); break
        else:
            raise RuntimeError("no Arabic-capable font found")
    return _FONT_NAME


def ar(text) -> str:
    """Shape + reorder Arabic for ReportLab (which has no built-in shaping)."""
    return get_display(arabic_reshaper.reshape(str(text)))


def export_excel(path: str, title: str, headers, rows):
    wb = Workbook(); ws = wb.active; ws.title = title[:30]
    ws.sheet_view.rightToLeft = True
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="2F6F73")
        c.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append(list(r))
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(40, max(12, max(len(str(c.value or "")) for c in col) + 2))
    wb.save(path)


def export_pdf(path: str, title: str, headers, rows):
    f = _font()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=28, bottomMargin=24)
    ts = ParagraphStyle("t", fontName=f, fontSize=16, alignment=1, leading=24)
    data = [[ar(h) for h in reversed(headers)]] + [[ar(c) for c in reversed(list(r))] for r in rows]  # RTL column order
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), f), ("FONTSIZE", (0, 0), (-1, -1), 10),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F6F73")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F6")])]))
    doc.build([Paragraph(ar(title), ts), Spacer(1, 12), t])


def export_issue_voucher_pdf(path: str, voucher: dict, clinic_name: str = "المركز الطبي - قسم المستلزمات الطبية"):
    from ..money import fmt_egp
    f = _font()
    doc = SimpleDocTemplate(path, pagesize=A4, rightMargin=24, leftMargin=24, topMargin=28, bottomMargin=24)
    title_style = ParagraphStyle("vt", fontName=f, fontSize=17, alignment=1, leading=24)
    sub_style = ParagraphStyle("vs", fontName=f, fontSize=12, alignment=1, leading=18)
    cell_style = ParagraphStyle("vc", fontName=f, fontSize=9, alignment=1, leading=13)
    hdr_style = ParagraphStyle("vh", fontName=f, fontSize=9, alignment=1, leading=13, textColor=colors.white)

    elements = []
    elements.append(Paragraph(ar(clinic_name), sub_style))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(ar(f"سند صرف مستلزمات طبية ({voucher['number']})"), title_style))
    elements.append(Spacer(1, 12))

    info_data = [
        [ar(f"تاريخ الصرف: {voucher['issued_at'].strftime('%Y-%m-%d %H:%M')}"), ar(f"العيادة / القسم: {voucher['department_name']}")],
        [ar(f"مسؤول الصرف: {voucher['created_by_name']}"), ar(f"المستلم: {voucher['recipient']}")],
        [ar(f"ملاحظات: {voucher['notes']}"), ar(f"المرجع: {voucher['reference']}")]
    ]
    t_info = Table(info_data, colWidths=[270, 270])
    t_info.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D9E3E3")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFA"))
    ]))
    elements.append(t_info)
    elements.append(Spacer(1, 12))

    headers = ["م", "الكود", "اسم الصنف", "الوحدة", "الكمية", "متوسط التكلفة", "إجمالي التكلفة"]
    table_data = [[Paragraph(ar(h), hdr_style) for h in reversed(headers)]]
    for idx, line in enumerate(voucher["lines"], 1):
        row = [
            str(idx),
            line["item_code"],
            line["item_name"],
            line["unit_name"],
            str(line["quantity"]),
            fmt_egp(line["unit_cost"]),
            fmt_egp(line["cost"])
        ]
        table_data.append([Paragraph(ar(c), cell_style) for c in reversed(row)])

    tot_row = ["", "", "الإجمالي العام لتكلفة الصرف", "", "", "", fmt_egp(voucher["total_cost"])]
    table_data.append([Paragraph(ar(c), cell_style) for c in reversed(tot_row)])

    t_items = Table(table_data, colWidths=[80, 70, 50, 60, 180, 70, 30])
    t_items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F6F73")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F6F6")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E4EEEE")),
    ]))
    elements.append(t_items)
    elements.append(Spacer(1, 28))

    sig_data = [
        [ar("توقيع المستلم: .............................."),
         ar("توقيع مسؤول الصرف: .............................."),
         ar("اعتماد أمين المخزن: ..............................")]
    ]
    t_sig = Table(sig_data, colWidths=[180, 180, 180])
    t_sig.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), f),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER")
    ]))
    elements.append(t_sig)

    doc.build(elements)

