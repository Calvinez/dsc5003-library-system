"""Render the database design Markdown and measured-result appendices into PDF.

The Markdown files are the only body-text sources. No measured value is copied
into this renderer. PDF export needs optional reportlab; PNG QA needs Poppler.
Fonts default to the Windows Microsoft YaHei TrueType collections; use --font
and --bold-font for other CJK TrueType fonts. Run from any working directory.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, Image, KeepTogether, LongTable, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, TableStyle,
)


NAVY = colors.HexColor("#122942")
TEAL = colors.HexColor("#087E83")
INK = colors.HexColor("#253C50")
MUTED = colors.HexColor("#566D7D")
BORDER = colors.HexColor("#D4DFE7")
PALE = colors.HexColor("#F0F6FA")
PAGE_W, PAGE_H = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 43, 49, 46
# SimpleDocTemplate's default Frame has a 6 pt inset on each horizontal edge.
BODY_W = PAGE_W - MARGIN_X * 2 - 12


def inline(value: str) -> str:
    """Escape input first, then support a deliberately small inline subset."""
    escaped = html.escape(value, quote=False)
    placeholders = []

    def code(match):
        placeholders.append('<font name="YaHei" color="#087E83">' + match.group(1) + "</font>")
        return f"\x01{len(placeholders) - 1}\x02"

    escaped = re.sub(r"`([^`]+)`", code, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        lambda match: '<link href="' + html.escape(html.unescape(match.group(2)), quote=True)
        + '" color="#087E83">' + match.group(1) + "</link>", escaped,
    )
    # Raw reference URLs are clickable. Avoid reprocessing an existing tag.
    parts = re.split(r"(<[^>]+>)", escaped)
    inside_link = False
    for i, part in enumerate(parts):
        if part.startswith("<link "):
            inside_link = True
        elif part == "</link>":
            inside_link = False
        elif not part.startswith("<") and not inside_link:
            parts[i] = re.sub(
                r"https?://[^\s<]+",
                lambda match: '<link href="' + html.escape(html.unescape(match.group()), quote=True)
                + '" color="#087E83">' + match.group() + "</link>", part,
            )
    escaped = "".join(parts)
    for index, value in enumerate(placeholders):
        escaped = escaped.replace(f"\x01{index}\x02", value)
    return escaped


def styles():
    common = dict(fontName="YaHei", textColor=INK, alignment=TA_LEFT,
                  wordWrap="CJK", splitLongWords=1, allowWidows=0, allowOrphans=0)
    result = {
        "body": ParagraphStyle("Body", fontSize=10, leading=16.2, spaceAfter=8, **common),
        "title": ParagraphStyle("Title", fontName="YaHei-Bold", fontSize=23, leading=31,
                                textColor=NAVY, spaceAfter=16, keepWithNext=True,
                                wordWrap="CJK", splitLongWords=1),
        "appendix_title": ParagraphStyle("AppendixTitle", fontName="YaHei-Bold", fontSize=19.5,
                                         leading=27, textColor=NAVY, spaceAfter=15,
                                         keepWithNext=True, wordWrap="CJK", splitLongWords=1),
        "h2": ParagraphStyle("Heading2", fontName="YaHei-Bold", fontSize=15.2, leading=22,
                             textColor=NAVY, spaceBefore=15, spaceAfter=9,
                             keepWithNext=True, wordWrap="CJK", splitLongWords=1),
        "h3": ParagraphStyle("Heading3", fontName="YaHei-Bold", fontSize=12, leading=18,
                             textColor=TEAL, spaceBefore=12, spaceAfter=7,
                             keepWithNext=True, wordWrap="CJK", splitLongWords=1),
        "bullet": ParagraphStyle("Bullet", fontSize=9.8, leading=16, spaceAfter=5,
                                 leftIndent=13, firstLineIndent=0, bulletIndent=0,
                                 bulletFontName="YaHei", bulletFontSize=8, **common),
        "table": ParagraphStyle("TableBody", fontSize=8.1, leading=12.2, spaceAfter=0, **common),
        "table_header": ParagraphStyle("TableHeader", fontName="YaHei-Bold", fontSize=8.3,
                                       leading=12.3, textColor=colors.white,
                                       wordWrap="CJK", splitLongWords=1),
        "caption": ParagraphStyle("Caption", fontName="YaHei", fontSize=8.5, leading=13, textColor=MUTED,
                                  spaceBefore=6, spaceAfter=10, wordWrap="CJK"),
    }
    return result


class CodeBlock(Flowable):
    """A measured, splittable code panel: long identifiers cannot overrun a page."""
    def __init__(self, raw=None, lines=None, width=BODY_W):
        super().__init__()
        self.raw = raw
        self.lines = lines
        self.width = width
        self.font = "Courier"
        self.size = 8.5
        self.leading = 12
        self.padding = 10
        self.spaceBefore = 4
        self.spaceAfter = 10

    def wrap(self, available_width, available_height):
        self.width = available_width
        if self.lines is None:
            lines = []
            for raw_line in self.raw.expandtabs(4).split("\n"):
                line = ""
                for character in raw_line:
                    if line and pdfmetrics.stringWidth(line + character, self.font, self.size) > self.width - 2 * self.padding:
                        lines.append(line)
                        line = ""
                    line += character
                lines.append(line)
            self.lines = lines
        self.height = self.leading * len(self.lines) + 2 * self.padding
        return self.width, self.height

    def split(self, available_width, available_height):
        self.wrap(available_width, available_height)
        count = int((available_height - 2 * self.padding) / self.leading)
        if count < 1 or count >= len(self.lines):
            return []
        return [CodeBlock(lines=self.lines[:count], width=available_width),
                CodeBlock(lines=self.lines[count:], width=available_width)]

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(PALE)
        canvas.setStrokeColor(BORDER)
        canvas.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)
        canvas.setFillColor(INK)
        canvas.setFont(self.font, self.size)
        for i, line in enumerate(self.lines):
            canvas.drawString(self.padding, self.height - self.padding - self.size - i * self.leading, line)


def table_cells(line):
    return [part.strip().replace(r"\|", "|") for part in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def table_widths(headers):
    count = len(headers)
    if count == 4 and headers[:2] == ["表", "字段"]:
        fractions = [0.15, 0.26, 0.31, 0.28]
    elif count == 3 and headers[0] == "索引":
        fractions = [0.38, 0.33, 0.29]
    elif count == 7 and "reader_id" in headers:
        fractions = [0.18, 0.105, 0.12, 0.23, 0.09, 0.14, 0.135]
    elif count == 4 and any("中位" in header for header in headers):
        fractions = [0.34, 0.22, 0.22, 0.22]
    else:
        # Conservative compact defaults for measured-results summary tables.
        fractions = {2: [0.3, 0.7], 3: [0.25, 0.25, 0.5],
                     4: [0.25, 0.15, 0.15, 0.45],
                     5: [0.2, 0.16, 0.16, 0.16, 0.32]}.get(count, [1 / count] * count)
    return [BODY_W * fraction for fraction in fractions]


def make_table(rows, sty):
    headers = rows[0]
    n = len(headers)
    if any(len(row) != n for row in rows):
        raise ValueError("Malformed Markdown table: different column counts")
    data = [[Paragraph(inline(cell), sty["table_header" if i == 0 else "table"])
             for cell in row] for i, row in enumerate(rows)]
    table = LongTable(data, colWidths=table_widths(headers), repeatRows=1,
                      hAlign="LEFT", splitByRow=1, spaceBefore=5, spaceAfter=12)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, NAVY),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, BORDER),
    ]
    for i in range(1, len(data)):
        if i % 2:
            commands.append(("BACKGROUND", (0, i), (-1, i), PALE))
    table.setStyle(TableStyle(commands))
    return table


def er_figure(root: Path, sty):
    path = root / "docs" / "er-diagram.png"
    if not path.exists():
        return []
    width, height = ImageReader(str(path)).getSize()
    image = Image(str(path), width=BODY_W, height=BODY_W * height / width)
    caption = Paragraph("图 A-1　数据库物理 ER 图。全部字段及约束的可放大版本另见 er-diagram.svg / er-diagram.pdf。", sty["caption"])
    return [KeepTogether([Spacer(1, 5), image, caption])]


def parse_markdown(source: str, sty, root: Path, insert_er=False, appendix_prefix=""):
    """Preserve prose, headings, bullets, fenced code and pipe tables."""
    lines = source.splitlines()
    output, paragraph = [], []
    inside_section_two = False
    er_inserted = False
    references_start = None

    def flush():
        if paragraph:
            output.append(Paragraph(inline(" ".join(paragraph)), sty["body"]))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            flush()
            i += 1
            continue
        if line.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("Unterminated fenced code block")
            output.append(CodeBlock("\n".join(code)))
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            flush()
            level, value = len(heading.group(1)), heading.group(2)
            if insert_er and inside_section_two and level <= 2 and not er_inserted:
                output.extend(er_figure(root, sty))
                er_inserted = True
                inside_section_two = False
            if insert_er and level == 2 and re.match(r"2[.、\s]", value):
                inside_section_two = True
            if value == "参考文献":
                references_start = len(output)
            style = "title" if level == 1 else "h2" if level == 2 else "h3"
            if level == 1 and appendix_prefix:
                value = appendix_prefix + value
                style = "appendix_title"
            output.append(Paragraph(inline(value), sty[style]))
            i += 1
            continue
        if line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = table_cells(lines[i])
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    rows.append(cells)
                i += 1
            output.append(make_table(rows, sty))
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        ordered = re.match(r"^(\d+)[.]\s+(.*)$", line)
        if bullet or ordered:
            flush()
            text = bullet.group(1) if bullet else ordered.group(2)
            marker = "•" if bullet else ordered.group(1) + "."
            output.append(Paragraph(inline(text), sty["bullet"], bulletText=marker))
            i += 1
            continue
        paragraph.append(line)
        i += 1
    flush()
    if insert_er and inside_section_two and not er_inserted:
        output.extend(er_figure(root, sty))
    if references_start is not None:
        # This short bibliography fits one page; keep its heading and entries
        # together rather than leaving only the first citation on a prior page.
        output[references_start:] = [KeepTogether(output[references_start:])]
    return output


def page_chrome(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_X, PAGE_H - 33, PAGE_W - MARGIN_X, PAGE_H - 33)
    canvas.setFillColor(MUTED)
    canvas.setFont("YaHei", 8)
    canvas.drawString(MARGIN_X, PAGE_H - 25, "LIBRARY DATABASE  /  PART A")
    canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 25, "数据库设计与实测材料")
    canvas.line(MARGIN_X, 32, PAGE_W - MARGIN_X, 32)
    canvas.drawString(MARGIN_X, 20, "供 D 汇总使用；不是整组最终报告")
    canvas.drawRightString(PAGE_W - MARGIN_X, 20, str(document.page))
    canvas.restoreState()


def render(root: Path, output: Path, font: Path, bold_font: Path):
    for path in (font, bold_font):
        if not path.is_file():
            raise FileNotFoundError(f"CJK TrueType font not found: {path}; pass --font and --bold-font")
    pdfmetrics.registerFont(TTFont("YaHei", str(font), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("YaHei-Bold", str(bold_font), subfontIndex=0))
    pdfmetrics.registerFontFamily("YaHei", normal="YaHei", bold="YaHei-Bold",
                                  italic="YaHei", boldItalic="YaHei-Bold")
    main_source = root / "docs" / "database-design.md"
    sources = [main_source]
    story = parse_markdown(main_source.read_text(encoding="utf-8"), styles(), root, insert_er=True)
    for relative, prefix in [
        ("evaluation/validation-summary.md", "附录 A："),
        ("evaluation/index-100k/benchmark-summary.md", "附录 B："),
    ]:
        path = root / relative
        if path.exists():
            sources.append(path)
            sty = styles()
            story.append(PageBreak())
            story.extend(parse_markdown(path.read_text(encoding="utf-8"), sty, root, appendix_prefix=prefix))
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(b"\0".join(p.read_bytes() for p in sources)).hexdigest()
    document = SimpleDocTemplate(str(output), pagesize=A4, leftMargin=MARGIN_X,
                                 rightMargin=MARGIN_X, topMargin=MARGIN_TOP,
                                 bottomMargin=MARGIN_BOTTOM, title="图书馆借阅系统：A 数据库设计说明",
                                 author="Database course project / Part A",
                                 subject="Database design and actual measured-result appendices",
                                 keywords="source-sha256:" + digest,
                                 pageCompression=1, allowSplitting=1)
    document.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    print(f"Rendered {output.resolve()}")
    print("Body sources:")
    for path in sources:
        print("  " + str(path.relative_to(root)))
    print("Combined source SHA256: " + digest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    parser.add_argument("--bold-font", type=Path, default=Path("C:/Windows/Fonts/msyhbd.ttc"))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    render(root, args.output or root / "docs" / "database-design.pdf", args.font, args.bold_font)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
