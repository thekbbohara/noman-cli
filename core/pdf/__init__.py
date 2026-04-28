"""PDF handling module for noman-cli.

PDF reading, editing, OCR, and writing capabilities.

Modules:
    reader: PDFReader - Extract text, images, metadata from PDFs
    editor: PDFEditor - Merge, split, annotate PDFs
    ocr: PDFOCR - OCR for scanned PDFs using Tesseract
    writer: PDFWriter - Create PDFs from text/markdown

Usage (programmatic):
    from core.pdf import PDFReader, PDFOCR, PDFWriter
    reader = PDFReader()
    result = await reader.read("document.pdf")
    print(result.text)

    ocr = PDFOCR()
    result = await ocr.process("scanned.pdf")
    print(result.text)

    writer = PDFWriter()
    await writer.create("output.pdf", "Hello World")

CLI:
    noman pdf read <file>           - Read text from PDF
    noman pdf ocr <file>            - OCR scanned PDF
    noman pdf write <output> <text> - Create PDF from text
    noman pdf merge <out> <f1> <f2> - Merge PDFs
    noman pdf split <file>          - Split PDF into pages
    noman pdf info <file>           - Show PDF metadata
"""

from __future__ import annotations

from core.pdf.editor import PDFEditor
from core.pdf.ocr import PDFOCR, OCRResult
from core.pdf.reader import PDFInfo, PDFReader, PDFReadResult
from core.pdf.writer import PDFWriter

__all__ = [
    "PDFEditor",
    "PDFOCR",
    "OCRResult",
    "PDFInfo",
    "PDFReader",
    "PDFReadResult",
    "PDFWriter",
]
