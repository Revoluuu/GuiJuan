"""GuiJuan: safe local tools for organizing research PDFs."""

from .scanner import PdfFile, scan_pdf_files

__all__ = ["PdfFile", "scan_pdf_files"]
__version__ = "0.2.0"
