"""把比赛提交用的 Markdown 文档排版成 PDF。

用法：python tools/build_submission_docs.py
输出：materials/智能体版-提交材料/*.pdf
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
MATERIALS = ROOT / "materials" / "智能体版-提交材料"

FONT_REGULAR = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_NAME = "MSYH"
FONT_BOLD_NAME = "MSYH-Bold"

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 1.9 * cm
AVAILABLE_WIDTH = PAGE_WIDTH - 2 * MARGIN


def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_REGULAR, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, FONT_BOLD, subfontIndex=0))
    pdfmetrics.registerFontFamily(
        FONT_NAME,
        normal=FONT_NAME,
        bold=FONT_BOLD_NAME,
        italic=FONT_NAME,
        boldItalic=FONT_BOLD_NAME,
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCN",
            parent=base["Title"],
            fontName=FONT_BOLD_NAME,
            fontSize=20,
            leading=30,
            alignment=TA_CENTER,
            spaceAfter=6,
            textColor=colors.HexColor("#124f3d"),
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCN",
            parent=base["Normal"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#61766d"),
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "H1CN",
            parent=base["Heading1"],
            fontName=FONT_BOLD_NAME,
            fontSize=15,
            leading=23,
            spaceBefore=14,
            spaceAfter=7,
            textColor=colors.HexColor("#124f3d"),
        ),
        "h2": ParagraphStyle(
            "H2CN",
            parent=base["Heading2"],
            fontName=FONT_BOLD_NAME,
            fontSize=12.5,
            leading=20,
            spaceBefore=11,
            spaceAfter=5,
            textColor=colors.HexColor("#146c50"),
        ),
        "body": ParagraphStyle(
            "BodyCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=17,
            spaceAfter=5,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "BulletCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=10,
            leading=17,
            leftIndent=14,
            bulletIndent=4,
            spaceAfter=3,
            wordWrap="CJK",
        ),
        "quote": ParagraphStyle(
            "QuoteCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=9.5,
            leading=16,
            leftIndent=12,
            rightIndent=8,
            textColor=colors.HexColor("#5c6f66"),
            backColor=colors.HexColor("#f3f7f3"),
            borderPadding=6,
            spaceBefore=4,
            spaceAfter=6,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "CodeCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=8.6,
            leading=13,
            leftIndent=8,
            rightIndent=8,
            backColor=colors.HexColor("#f4f7f4"),
            borderPadding=4,
            spaceAfter=1,
            wordWrap="CJK",
        ),
        "cell": ParagraphStyle(
            "CellCN",
            parent=base["BodyText"],
            fontName=FONT_NAME,
            fontSize=8.4,
            leading=12.5,
            wordWrap="CJK",
        ),
        "cell_header": ParagraphStyle(
            "CellHeaderCN",
            parent=base["BodyText"],
            fontName=FONT_BOLD_NAME,
            fontSize=8.6,
            leading=12.5,
            textColor=colors.HexColor("#124f3d"),
            wordWrap="CJK",
        ),
    }


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    text = _escape(text.strip())
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font backColor="#eef4ef" color="#315747">\1</font>', text)
    return text


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def _table_flowable(lines: list[str], styles: dict[str, ParagraphStyle]) -> LongTable:
    rows = [_split_table_row(line) for line in lines]
    header = rows[0]
    body = [row for row in rows[1:] if not _is_separator(row)]
    ncols = max(len(row) for row in rows)
    header += [""] * (ncols - len(header))
    body = [row + [""] * (ncols - len(row)) for row in body]

    if ncols == 2:
        widths = [AVAILABLE_WIDTH * 0.30, AVAILABLE_WIDTH * 0.70]
    elif ncols == 3:
        widths = [AVAILABLE_WIDTH * 0.22, AVAILABLE_WIDTH * 0.30, AVAILABLE_WIDTH * 0.48]
    else:
        widths = [AVAILABLE_WIDTH / ncols] * ncols

    data = [[Paragraph(_inline(cell), styles["cell_header"]) for cell in header]]
    for row in body:
        data.append([Paragraph(_inline(cell), styles["cell"]) for cell in row])

    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf5ef")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#124f3d")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cfe0d5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbfdfb")]),
            ]
        )
    )
    return table


def markdown_to_flowables(text: str, styles: dict[str, ParagraphStyle]) -> list:
    lines = text.replace("\r\n", "\n").split("\n")
    flowables: list = []
    index = 0
    title_done = False

    while index < len(lines):
        raw = lines[index]
        line = raw.strip()

        if not line:
            index += 1
            continue

        if line.startswith("```"):
            index += 1
            code_lines = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index].rstrip())
                index += 1
            index += 1
            if code_lines:
                flowables.append(Paragraph("<br/>".join(_escape(c) for c in code_lines), styles["code"]))
                flowables.append(Spacer(1, 4))
            continue

        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            flowables.append(_table_flowable(table_lines, styles))
            flowables.append(Spacer(1, 6))
            continue

        if line.startswith("# "):
            style = "title" if not title_done else "h1"
            flowables.append(Paragraph(_inline(line[2:]), styles[style]))
            title_done = True
            index += 1
            continue
        if line.startswith("## "):
            flowables.append(Paragraph(_inline(line[3:]), styles["h1"]))
            index += 1
            continue
        if line.startswith("### "):
            flowables.append(Paragraph(_inline(line[4:]), styles["h2"]))
            index += 1
            continue

        if line.startswith(">"):
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            flowables.append(Paragraph(_inline(" ".join(quote_lines)), styles["quote"]))
            continue

        bullet_match = re.match(r"^([-*])\s+(.*)$", line)
        if bullet_match:
            content = bullet_match.group(2)
            if content.startswith("[ ]"):
                bullet = "☐"
                content = content[3:].strip()
            elif content.lower().startswith("[x]"):
                bullet = "☑"
                content = content[3:].strip()
            else:
                bullet = "•"
            flowables.append(Paragraph(_inline(content), styles["bullet"], bulletText=bullet))
            index += 1
            continue

        numbered_match = re.match(r"^(\d+)[.、]\s+(.*)$", line)
        if numbered_match:
            flowables.append(
                Paragraph(_inline(numbered_match.group(2)), styles["bullet"], bulletText=f"{numbered_match.group(1)}.")
            )
            index += 1
            continue

        flowables.append(Paragraph(_inline(line), styles["body"]))
        index += 1

    return flowables


def build_pdf(source: Path, target: Path) -> None:
    styles = _styles()
    text = source.read_text(encoding="utf-8")
    flowables = markdown_to_flowables(text, styles)

    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title=source.stem,
        author="田诊卫士项目组",
    )

    def on_page(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor("#7a8c83"))
        canvas.drawString(MARGIN, 1.0 * cm, "田诊卫士 · 智能体版 · 比赛提交材料")
        canvas.drawRightString(PAGE_WIDTH - MARGIN, 1.0 * cm, f"第 {doc_obj.page} 页")
        canvas.restoreState()

    doc.build(flowables, onFirstPage=on_page, onLaterPages=on_page)
    print(f"OK {target.name}  {target.stat().st_size / 1024:.1f} KB")


def main() -> None:
    _register_fonts()
    sources = [
        "00-提交清单.md",
        "01-团队分工说明.md",
        "02-AI工具与开发说明.md",
        "03-原创承诺书-填写说明.md",
        "04-作品说明-智能体版.md",
    ]
    for name in sources:
        source = MATERIALS / name
        if not source.exists():
            print(f"SKIP {name} (missing)")
            continue
        build_pdf(source, source.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
