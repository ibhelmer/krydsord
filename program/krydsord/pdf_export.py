"""Printable A4 puzzles and answer keys using ReportLab.

The puzzle-only export never draws the answers or stores them in annotations.
Long clue lists flow onto extra pages. System fonts are used when available;
no external font files are distributed with the application.
"""
from __future__ import annotations

from io import BytesIO
from itertools import zip_longest
import os
from pathlib import Path
import tempfile
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle,
)

from . import __version__
from .models import Puzzle

INK = colors.HexColor("#233342")
MUTED = colors.HexColor("#516274")


def _fonts() -> tuple[str, str]:
    regular, bold = "CrosswordSans", "CrosswordSansBold"
    if regular in pdfmetrics.getRegisteredFontNames():
        return regular, bold
    windir = Path(os.environ.get("WINDIR", "C:/Windows"))
    candidates = [
        (windir / "Fonts/arial.ttf", windir / "Fonts/arialbd.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
         Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")),
        (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
    ]
    for normal_file, bold_file in candidates:
        if normal_file.is_file() and bold_file.is_file():
            try:
                pdfmetrics.registerFont(TTFont(regular, str(normal_file)))
                pdfmetrics.registerFont(TTFont(bold, str(bold_file)))
                pdfmetrics.registerFontFamily(regular, normal=regular, bold=bold,
                                              italic=regular, boldItalic=bold)
                return regular, bold
            except (OSError, ValueError):
                continue
    return "Helvetica", "Helvetica-Bold"


def _check_glyphs(font: str, text: str) -> None:
    face = pdfmetrics.getFont(font).face
    if hasattr(face, "charWidths"):
        unsupported = {c for c in text if not c.isspace() and ord(c) not in face.charWidths}
    else:
        unsupported = set()
        for c in text:
            try:
                c.encode("cp1252")
            except UnicodeEncodeError:
                unsupported.add(c)
    if unsupported:
        raise ValueError("PDF-skrifttypen understøtter ikke disse tegn: "
                         + " ".join(sorted(unsupported)) + ". Fjern dem fra titel/forklaringer.")


class CrosswordGrid(Flowable):
    def __init__(self, puzzle: Puzzle, regular: str, bold: str, solution: bool):
        super().__init__()
        self.puzzle, self.regular, self.bold, self.solution = puzzle, regular, bold, solution
        self.cell = min(23.0, 503.0 / puzzle.cols, 330.0 / puzzle.rows)
        self.width, self.height = puzzle.cols * self.cell, puzzle.rows * self.cell
        self.hAlign = "CENTER"

    def draw(self) -> None:
        canvas = self.canv
        grid = self.puzzle.grid()
        starts = {(p.row, p.col): p.number for p in self.puzzle.placements}
        canvas.setLineWidth(0.45)
        canvas.setStrokeColor(INK)
        for row in range(self.puzzle.rows):
            for col in range(self.puzzle.cols):
                x, y = col * self.cell, self.height - (row + 1) * self.cell
                used = bool(grid[row][col])
                canvas.setFillColor(colors.white if used else INK)
                canvas.rect(x, y, self.cell, self.cell, fill=1, stroke=1)
                if not used:
                    continue
                if (row, col) in starts:
                    canvas.setFillColor(INK)
                    canvas.setFont(self.regular, max(4.5, self.cell * 0.25))
                    canvas.drawString(x + self.cell * 0.08, y + self.cell * 0.71,
                                      str(starts[row, col]))
                if self.solution:
                    canvas.setFont(self.bold, self.cell * 0.54)
                    canvas.setFillColor(INK)
                    canvas.drawCentredString(x + self.cell / 2, y + self.cell * 0.16,
                                             grid[row][col])


def export_pdf(puzzle: Puzzle, path: str | Path, *, include_solution: bool = False,
               solution_only: bool = False) -> Path:
    puzzle.validate()
    if not puzzle.placements:
        raise ValueError("Krydsordet er tomt. Indsæt eller generér ord først.")
    puzzle.renumber()
    regular, bold = _fonts()
    text = puzzle.title + puzzle.note + "".join(p.entry.clue + p.entry.answer for p in puzzle.placements)
    _check_glyphs(regular, text)
    _check_glyphs(bold, puzzle.title + "".join(p.entry.answer for p in puzzle.placements))
    path = Path(path).expanduser().resolve()
    if not path.parent.is_dir():
        raise ValueError("Mappen til PDF-filen findes ikke.")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40,
                            topMargin=34, bottomMargin=42,
                            title=puzzle.title + (" - facit" if solution_only else ""),
                            author="", creator=f"Kryds & Tværs Generator {__version__}")
    styles = {
        "eyebrow": ParagraphStyle("eyebrow", fontName=bold, fontSize=8, leading=11,
                                   textColor=MUTED, spaceAfter=7),
        "title": ParagraphStyle("title", fontName=bold, fontSize=24, leading=29,
                                 textColor=INK, spaceAfter=7),
        "meta": ParagraphStyle("meta", fontName=regular, fontSize=9, leading=13,
                                textColor=MUTED, spaceAfter=8),
        "clue": ParagraphStyle("clue", fontName=regular, fontSize=9.1, leading=12.8,
                                textColor=INK),
        "head": ParagraphStyle("head", fontName=bold, fontSize=10, leading=14,
                                textColor=INK),
    }
    story = []
    sections = [True] if solution_only else [False, True] if include_solution else [False]
    for section_index, solution in enumerate(sections):
        if section_index:
            story.append(PageBreak())
        tag = "FACIT / MED SVAR" if solution else "OPGAVE / UDEN SVAR"
        story.append(Paragraph("KRYDS &amp; TVÆRS  /  " + tag, styles["eyebrow"]))
        story.append(Paragraph(escape(puzzle.title), styles["title"]))
        description = (f"{len(puzzle.placements)} ord · {puzzle.rows} × {puzzle.cols} felter · "
                       "Æ, Ø og Å fylder ét felt hver.")
        story.append(Paragraph(description, styles["meta"]))
        if puzzle.note:
            story.append(Paragraph(escape(puzzle.note), styles["meta"]))
        if not solution:
            story.append(Paragraph("Navn: ______________________________  Dato: ______________", styles["meta"]))
        story.append(Spacer(1, 4))
        story.append(CrosswordGrid(puzzle, regular, bold, solution))
        story.append(Spacer(1, 16))
        across = sorted((p for p in puzzle.placements if p.direction == "across"), key=lambda p: p.number)
        down = sorted((p for p in puzzle.placements if p.direction == "down"), key=lambda p: p.number)
        def clue(p):
            if p is None:
                return ""
            answer = f" <b>{escape(p.entry.answer)}</b> —" if solution else ""
            content = (f"<b>{p.number}.</b>{answer} {escape(p.entry.clue)} "
                       f"<font color='#516274'>({len(p.entry.answer)})</font>")
            return Paragraph(content, styles["clue"])
        rows = [[Paragraph("VANDRET", styles["head"]), "", Paragraph("LODRET", styles["head"])]]
        rows.extend([[clue(a), "", clue(d)] for a, d in zip_longest(across, down)])
        width = A4[0] - 80
        table = LongTable(rows, colWidths=[(width - 20) / 2, 20, (width - 20) / 2], repeatRows=1,
                          hAlign="LEFT")
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("LINEBELOW", (0, 0), (0, 0), 0.5, colors.HexColor("#C4CDD4")),
            ("LINEBELOW", (2, 0), (2, 0), 0.5, colors.HexColor("#C4CDD4")),
        ]))
        story.append(table)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#CDD4DA"))
        canvas.setLineWidth(0.4)
        canvas.line(40, 32, A4[0] - 40, 32)
        canvas.setFillColor(MUTED)
        canvas.setFont(regular, 7)
        canvas.drawString(40, 20, f"Kryds & Tværs Generator · {__version__}")
        canvas.drawRightString(A4[0] - 40, 20, f"Side {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    # Replace atomically: a failed export cannot destroy an existing PDF.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".pdf.tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(buffer.getvalue())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return path