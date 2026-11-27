"""Reproduce the physical ER diagram for sql/01_schema.sql.

SVG and Mermaid: Python standard library only (--svg-only).
PDF: optional reportlab. PNG: optional Poppler pdftoppm on PATH.
Usage: python scripts/render_er.py [--svg-only] [--output docs]
The SQL schema is authoritative; update this small diagram specification with it.
"""
from __future__ import annotations

import argparse
import html
import shutil
import subprocess
from pathlib import Path


WIDTH, HEIGHT = 1800, 1270
NAVY, TEAL = "#122942", "#087E83"
INK, MUTED, BORDER = "#253C50", "#566D7D", "#CDDBE4"
PALE, ROW = "#F0F6FA", "#F6F9FC"
HEADER, ROW_H, FOOTER = 44, 34, 28

# Columns: name, exact SQL data type, keys, nullable, auto_increment/generated.
TABLES = {
    "categories": (50, 190, 340, [
        ("category_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("name", "VARCHAR(80)", "UQ", False, ""),
    ], ""),
    "publishers": (50, 410, 340, [
        ("publisher_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("name", "VARCHAR(160)", "UQ", False, ""),
    ], ""),
    "authors": (50, 730, 340, [
        ("author_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("author_key", "VARCHAR(64)", "UQ", False, ""),
        ("name", "VARCHAR(120)", "", False, ""),
    ], "author_key: ASCII / case sensitive"),
    "books": (480, 190, 380, [
        ("book_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("isbn", "CHAR(13)", "UQ", False, ""),
        ("title", "VARCHAR(255)", "", False, ""),
        ("category_id", "BIGINT UNSIGNED", "FK", False, ""),
        ("publisher_id", "BIGINT UNSIGNED", "FK", False, ""),
        ("publication_year", "SMALLINT UNSIGNED", "", False, ""),
        ("description", "TEXT", "", True, ""),
        ("created_at", "DATETIME", "", False, ""),
    ], "isbn: ASCII / case sensitive"),
    "book_authors": (480, 730, 380, [
        ("book_id", "BIGINT UNSIGNED", "PK,FK", False, ""),
        ("author_id", "BIGINT UNSIGNED", "PK,FK", False, ""),
    ], "Composite PK: (book_id, author_id)"),
    "readers": (950, 190, 370, [
        ("reader_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("reader_no", "VARCHAR(32)", "UQ", False, ""),
        ("name", "VARCHAR(100)", "", False, ""),
        ("email", "VARCHAR(254)", "UQ", True, ""),
        ("status", "ENUM", "", False, ""),
        ("created_at", "DATETIME", "", False, ""),
    ], "status: ACTIVE | SUSPENDED"),
    "book_copies": (950, 630, 370, [
        ("copy_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("book_id", "BIGINT UNSIGNED", "FK", False, ""),
        ("barcode", "VARCHAR(40)", "UQ", False, ""),
        ("shelf_code", "VARCHAR(40)", "", False, ""),
        ("status", "ENUM", "", False, ""),
        ("acquired_at", "DATE", "", False, ""),
    ], "status: IN_SERVICE | MAINTENANCE | WITHDRAWN"),
    "loans": (1410, 630, 350, [
        ("loan_id", "BIGINT UNSIGNED", "PK", False, "AI"),
        ("reader_id", "BIGINT UNSIGNED", "FK", False, ""),
        ("copy_id", "BIGINT UNSIGNED", "FK", False, ""),
        ("borrowed_at", "DATETIME", "", False, ""),
        ("due_at", "DATETIME", "", False, ""),
        ("returned_at", "DATETIME", "", True, ""),
        ("active_copy_id", "BIGINT UNSIGNED", "UQ", True, "G"),
    ], "G: stored generated; see open-loan rule below"),
}


def row_y(name, field):
    table = TABLES[name]
    index = [column[0] for column in table[3]].index(field)
    return table[1] + HEADER + (index + 0.5) * ROW_H


def bottom(name):
    table = TABLES[name]
    return table[1] + HEADER + len(table[3]) * ROW_H + FOOTER


class Scene:
    """Minimal shared vector primitives, rendered identically into SVG and PDF."""
    def __init__(self):
        self.items = []

    def rect(self, x, y, width, height, fill, stroke=None, radius=0):
        self.items.append(("rect", x, y, width, height, fill, stroke, radius))

    def text(self, x, y, value, size=14, color=INK, bold=False, anchor="start"):
        self.items.append(("text", x, y, value, size, color, bold, anchor))

    def path(self, points, color=TEAL, width=2.5):
        self.items.append(("path", points, color, width))

    def circle(self, x, y, radius, fill=TEAL):
        self.items.append(("circle", x, y, radius, fill))

    def label(self, x, y, value, anchor="start"):
        self.text(x, y, value, 15, TEAL, True, anchor)

    def svg(self):
        elements = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
            '<title>Library borrowing system - physical ER model</title>',
            '<desc>Eight tables with all columns and seven foreign-key relationships. Each child has exactly one parent; each parent has zero or many children. The SQL schema is authoritative.</desc>',
        ]
        for item in self.items:
            if item[0] == "rect":
                _, x, y, w, h, fill, stroke, radius = item
                elements.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke or "none"}"/>')
            elif item[0] == "text":
                _, x, y, value, size, color, bold, anchor = item
                elements.append(f'<text x="{x}" y="{y}" font-family="Arial, Helvetica, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{anchor}">{html.escape(value)}</text>')
            elif item[0] == "path":
                _, points, color, width = item
                value = " ".join(f"{x},{y}" for x, y in points)
                elements.append(f'<polyline points="{value}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round"/>')
            elif item[0] == "circle":
                _, x, y, radius, fill = item
                elements.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}"/>')
        return "\n".join(elements + ["</svg>"]) + "\n"

    def pdf(self, path):
        try:
            from reportlab.lib.colors import HexColor
            from reportlab.lib.pagesizes import A3, landscape
            from reportlab.pdfgen.canvas import Canvas
        except ImportError as exc:
            raise RuntimeError("PDF export needs optional reportlab: pip install reportlab; or use --svg-only") from exc
        page_w, page_h = landscape(A3)
        canvas = Canvas(str(path), pagesize=(page_w, page_h), invariant=1)
        canvas.setTitle("Library borrowing system - physical ER model")
        canvas.setAuthor("Database course project / Part A")
        scale = min(page_w / WIDTH, page_h / HEIGHT)
        canvas.translate((page_w - WIDTH * scale) / 2, (page_h - HEIGHT * scale) / 2)
        canvas.scale(scale, scale)
        for item in self.items:
            if item[0] == "rect":
                _, x, y, w, h, fill, stroke, radius = item
                canvas.setFillColor(HexColor(fill))
                if stroke:
                    canvas.setStrokeColor(HexColor(stroke))
                canvas.roundRect(x, HEIGHT - y - h, w, h, radius, fill=1, stroke=bool(stroke))
            elif item[0] == "text":
                _, x, y, value, size, color, bold, anchor = item
                canvas.setFillColor(HexColor(color))
                canvas.setFont("Helvetica-Bold" if bold else "Helvetica", size)
                fn = {"start": canvas.drawString, "middle": canvas.drawCentredString, "end": canvas.drawRightString}[anchor]
                fn(x, HEIGHT - y, value)
            elif item[0] == "path":
                _, points, color, width = item
                canvas.setStrokeColor(HexColor(color))
                canvas.setLineWidth(width)
                canvas.setLineJoin(1)
                path = canvas.beginPath()
                path.moveTo(points[0][0], HEIGHT - points[0][1])
                for x, y in points[1:]:
                    path.lineTo(x, HEIGHT - y)
                canvas.drawPath(path)
            elif item[0] == "circle":
                _, x, y, radius, fill = item
                canvas.setFillColor(HexColor(fill))
                canvas.circle(x, HEIGHT - y, radius, stroke=0, fill=1)
        canvas.showPage()
        canvas.save()


def build_scene():
    scene = Scene()
    scene.rect(0, 0, WIDTH, HEIGHT, "#FFFFFF")
    scene.rect(50, 38, 8, 73, TEAL)
    scene.text(77, 70, "Library borrowing system", 35, NAVY, True)
    scene.text(79, 103, "Physical ER model  |  MySQL 8.0 / 8.4  |  Track 1 - Part A", 17, MUTED)
    scene.text(1750, 65, "8 TABLES  /  7 FOREIGN KEYS", 16, TEAL, True, "end")
    scene.text(1750, 98, "sql/01_schema.sql is authoritative", 14, MUTED, False, "end")

    # Draw orthogonal connectors first. Routes remain entirely outside table boxes.
    links = [
        ([(390, row_y("categories", "category_id")), (435, row_y("categories", "category_id")), (435, row_y("books", "category_id")), (480, row_y("books", "category_id"))],
         (402, 239), (470, 341)),
        ([(390, row_y("publishers", "publisher_id")), (420, row_y("publishers", "publisher_id")), (420, row_y("books", "publisher_id")), (480, row_y("books", "publisher_id"))],
         (400, 459), (470, 375)),
        ([(390, row_y("authors", "author_id")), (435, row_y("authors", "author_id")), (435, row_y("book_authors", "author_id")), (480, row_y("book_authors", "author_id"))],
         (402, 779), (470, 813)),
        ([(670, bottom("books")), (670, 730)], (685, bottom("books") + 24), (685, 715)),
        ([(860, row_y("books", "book_id")), (910, row_y("books", "book_id")), (910, row_y("book_copies", "book_id")), (950, row_y("book_copies", "book_id"))],
         (875, 239), (940, 703)),
        ([(1320, row_y("readers", "reader_id")), (1370, row_y("readers", "reader_id")), (1370, row_y("loans", "reader_id")), (1410, row_y("loans", "reader_id"))],
         (1334, 239), (1400, 703)),
        ([(1320, row_y("book_copies", "copy_id")), (1350, row_y("book_copies", "copy_id")), (1350, row_y("loans", "copy_id")), (1410, row_y("loans", "copy_id"))],
         (1330, 678), (1400, 775)),
    ]
    for points, one, many in links:
        scene.path(points)
        scene.circle(*points[0], 3.5)
        scene.circle(*points[-1], 3.5)
        scene.label(*one, "1")
        scene.label(*many, "0..*", anchor="end" if points[-1][0] != 670 else "start")
    scene.text(684, 620, "book_id", 14, MUTED)
    scene.text(684, 640, "references", 12, MUTED)
    scene.text(684, 660, "books.book_id", 14, MUTED)

    for name, (x, y, w, columns, footnote) in TABLES.items():
        height = HEADER + len(columns) * ROW_H + FOOTER
        scene.rect(x, y, w, height, "#FFFFFF", BORDER, 8)
        scene.rect(x, y, w, HEADER, NAVY, radius=8)
        scene.rect(x, y + HEADER - 8, w, 8, NAVY)
        scene.text(x + 15, y + 29, name, 21, "#FFFFFF", True)
        for index, (field, datatype, key, nullable, extra) in enumerate(columns):
            row_top = y + HEADER + index * ROW_H
            if index % 2 == 0:
                scene.rect(x + 1, row_top, w - 2, ROW_H, ROW)
            baseline = row_top + 22
            badge = "/".join(filter(None, (key.replace(",", "/"), extra)))
            scene.text(x + 9, baseline, badge, 9, TEAL, True)
            scene.text(x + 51, baseline, field + (" ?" if nullable else ""), 14, INK)
            scene.text(x + w - 11, baseline, datatype, 11.4, MUTED, anchor="end")
        if footnote:
            scene.text(x + 11, y + height - 10, footnote, 10.3, MUTED)

    scene.rect(50, 1010, 1710, 205, PALE, radius=10)
    scene.text(71, 1044, "Reading the diagram", 20, NAVY, True)
    scene.text(71, 1076, "PK  primary key     FK  foreign key     UQ  unique key     G  stored generated     AI  auto_increment     ?  nullable", 16, INK)
    scene.text(71, 1107, "Cardinality: 1 = exactly one parent; 0..* = zero or many child rows. Unmarked columns are NOT NULL.", 16, INK)
    scene.text(71, 1138, "Open-loan rule: active_copy_id = copy_id when returned_at IS NULL; otherwise NULL. UNIQUE(active_copy_id).", 16, INK)
    scene.text(71, 1169, "FK actions: RESTRICT; book_authors.book_id uses ON DELETE CASCADE. This does not delete borrowing history.", 16, INK)
    scene.text(71, 1198, "Dates: due_at > borrowed_at; returned_at IS NULL or returned_at >= borrowed_at. Availability is derived, not duplicated.", 15, MUTED)
    scene.text(50, 1244, "Database course project  |  Part A handoff to B / C / D", 13, MUTED)
    scene.text(1760, 1244, "A3 landscape  |  vector source included", 13, MUTED, anchor="end")
    return scene


def mermaid():
    lines = ["%% Physical schema; SQL is authoritative. '?' appears in comments for nullable columns.", "erDiagram"]
    for parent, child, label in [
        ("categories", "books", "classifies"),
        ("publishers", "books", "publishes"),
        ("books", "book_authors", "has_author_link"),
        ("authors", "book_authors", "has_book_link"),
        ("books", "book_copies", "has_copy"),
        ("readers", "loans", "borrows"),
        ("book_copies", "loans", "has_history"),
    ]:
        lines.append(f"    {parent} ||--o{{ {child} : {label}")
    for table, (_, _, _, columns, _) in TABLES.items():
        lines.append(f"    {table} {{")
        for field, datatype, key, nullable, extra in columns:
            key = key.replace("UQ", "UK")
            comments = []
            if nullable:
                comments.append("nullable")
            if extra:
                comments.append("stored generated" if extra == "G" else "AUTO_INCREMENT")
            if field in ("created_at",):
                comments.append("DEFAULT CURRENT_TIMESTAMP")
            suffix = ' "' + "; ".join(comments) + '"' if comments else ""
            lines.append(f"        {datatype.replace(' ', '_')} {field}" + (" " + key if key else "") + suffix)
        lines.append("    }")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg-only", action="store_true", help="Export SVG/Mermaid with the standard library only")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    scene = build_scene()
    (args.output / "er-diagram.svg").write_text(scene.svg(), encoding="utf-8")
    (args.output / "er-diagram.mmd").write_text(mermaid(), encoding="utf-8")
    if not args.svg_only:
        scene.pdf(args.output / "er-diagram.pdf")
        executable = shutil.which("pdftoppm")
        if not executable:
            raise SystemExit("SVG/Mermaid/PDF written; PNG export needs optional Poppler pdftoppm on PATH.")
        subprocess.run([executable, "-png", "-r", "160", "-singlefile",
                        str(args.output / "er-diagram.pdf"), str(args.output / "er-diagram")],
                       check=True, capture_output=True)
    print(f"ER diagram exported to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
