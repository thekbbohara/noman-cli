"""PDF reader with text, image, and metadata extraction.

Supported features:
    - Extract text from PDF files (including scanned PDFs via OCR)
    - Extract images from PDFs
    - Extract metadata (author, title, pages, creator, etc.)
    - Support for password-protected PDFs
    - Support for scanned PDFs (with OCR fallback)

Dependencies:
    PyMuPDF (fitz) - primary PDF engine
    pytesseract - OCR engine for scanned PDFs (optional)
    Pillow - image handling (optional)

Configuration (in ~/.noman/config.toml):
    [pdf]
    engine = "pymupdf"  # pymupdf or pdfplumber
    ocr_enabled = true
    ocr_lang = "eng"
    password = ""

Usage:
    from core.pdf.reader import PDFReader
    reader = PDFReader()
    result = await reader.read("document.pdf")
    print(result.text)
    print(result.metadata)
    print(f"Pages: {result.page_count}")
"""

from __future__ import annotations

import base64
import io
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)


@dataclass
class PDFReadResult:
    """Result from reading a PDF file."""
    text: str
    pages: list[str] = field(default_factory=list)
    page_count: int = 0
    images: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    is_scanned: bool = False
    source: str = ""
    encrypted: bool = False
    raw_data: bytes | None = None

    def __str__(self) -> str:
        return (
            f"PDFReadResult(source={self.source}, pages={self.page_count}, "
            f"text_len={len(self.text)}, images={len(self.images)}, "
            f"is_scanned={self.is_scanned})"
        )


@dataclass
class PDFInfo:
    """Metadata about a PDF file."""
    file_path: str
    page_count: int = 0
    title: str = ""
    author: str = ""
    subject: str = ""
    creator: str = ""
    producer: str = ""
    creation_date: str = ""
    modification_date: str = ""
    encryption: str = "none"
    file_size: int = 0
    is_encrypted: bool = False
    format: str = ""
    version: str = ""
    keywords: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "page_count": self.page_count,
            "title": self.title,
            "author": self.author,
            "subject": self.subject,
            "creator": self.creator,
            "producer": self.producer,
            "creation_date": self.creation_date,
            "modification_date": self.modification_date,
            "encryption": self.encryption,
            "file_size": self.file_size,
            "is_encrypted": self.is_encrypted,
            "format": self.format,
            "version": self.version,
            "keywords": self.keywords,
        }

    def __str__(self) -> str:
        lines = [f"PDF Info: {self.file_path}"]
        lines.append(f"  Pages: {self.page_count}")
        lines.append(f"  Size: {self.file_size:,} bytes")
        lines.append(f"  Format: {self.format} v{self.version}")
        for key, val in [
            ("Title", self.title),
            ("Author", self.author),
            ("Subject", self.subject),
            ("Creator", self.creator),
            ("Producer", self.producer),
            ("Keywords", self.keywords),
            ("Creation", self.creation_date),
            ("Modified", self.modification_date),
            ("Encryption", self.encryption),
        ]:
            if val:
                lines.append(f"  {key}: {val}")
        return "\n".join(lines)


class PDFReader:
    """Multi-engine PDF reader with text, image, and metadata extraction.

    Uses PyMuPDF (fitz) as the primary engine, with pdfplumber as fallback.
    Supports both native text PDFs and scanned PDFs (with OCR).
    """

    VALID_ENGINES = frozenset(["pymupdf", "pdfplumber"])

    def __init__(
        self,
        engine: str = "pymupdf",
        ocr_enabled: bool = True,
        ocr_lang: str = "eng",
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PDF reader.

        Args:
            engine: PDF engine to use ('pymupdf' or 'pdfplumber').
            ocr_enabled: Enable OCR for scanned PDFs.
            ocr_lang: Language code for OCR (default 'eng' for English).
            config: Configuration dict from config.toml [pdf] section.
        """
        self._config = config or {}
        self._engine = self._config.get("engine", engine)
        self._ocr_enabled = self._config.get("ocr_enabled", ocr_enabled)
        self._ocr_lang = self._config.get("ocr_lang", ocr_lang)
        self._password = self._config.get("password", "") or ""
        self._cache: dict[str, PDFReadResult] = {}

    def _get_engine(self) -> str:
        """Determine the best available engine."""
        if self._engine == "pdfplumber":
            try:
                import pdfplumber  # noqa: F401
                return "pdfplumber"
            except ImportError:
                logger.warning("pdfplumber not installed, falling back to pymupdf")
        return "pymupdf"

    async def read(
        self,
        source: str | Path,
        engine: str | None = None,
        extract_images: bool = False,
        password: str | None = None,
    ) -> PDFReadResult:
        """Read a PDF file and extract text, images, and metadata.

        Args:
            source: Path to the PDF file.
            engine: Override engine for this call.
            extract_images: Whether to extract embedded images.
            password: Password for encrypted PDFs.

        Returns:
            PDFReadResult with extracted content.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
            RuntimeError: If the PDF cannot be read.
            ValueError: If the PDF is password-protected and no password provided.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        cache_key = f"{path.resolve()}:{extract_images}:{password or ''}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        active_engine = engine or self._get_engine()
        result = PDFReadResult(text="", pages=[], page_count=0, source=str(source))

        try:
            if active_engine == "pymupdf":
                result = await self._read_pymupdf(path, extract_images, password or self._password)
            elif active_engine == "pdfplumber":
                result = await self._read_pdfplumber(path, extract_images, password or self._password)
            else:
                raise ValueError(f"Unknown PDF engine: {active_engine}")

            # Auto-detect scanned PDFs and apply OCR if needed
            if self._ocr_enabled and not result.text.strip() and result.page_count > 0:
                logger.info("PDF appears to be scanned, running OCR")
                result = await self._apply_ocr(result)

            self._cache[cache_key] = result
            return result

        except Exception as e:
            logger.error(f"Failed to read PDF '{source}': {e}")
            result.raw_data = path.read_bytes() if path.exists() else None
            return result

    async def read_metadata(
        self,
        source: str | Path,
        password: str | None = None,
    ) -> PDFInfo:
        """Extract metadata from a PDF file without reading full content.

        Args:
            source: Path to the PDF file.
            password: Password for encrypted PDFs.

        Returns:
            PDFInfo with metadata.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(path))
            info = doc.metadata or {}

            pdf_info = PDFInfo(
                file_path=str(path),
                page_count=len(doc),
                title=info.get("title", ""),
                author=info.get("author", ""),
                subject=info.get("subject", ""),
                creator=info.get("creator", ""),
                producer=info.get("producer", ""),
                creation_date=info.get("creationDate", ""),
                modification_date=info.get("modDate", ""),
                encryption="encrypted" if doc.is_encrypted else "none",
                file_size=path.stat().st_size,
                is_encrypted=doc.is_encrypted,
                format=info.get("format", ""),
                version=info.get("format", "").split("-")[-1] if info.get("format") else "",
                keywords=info.get("keywords", ""),
            )
            doc.close()
            return pdf_info

        except ImportError:
            logger.warning("PyMuPDF not installed, using fallback metadata extraction")
            return self._fallback_metadata(path, password)

    async def _read_pymupdf(
        self,
        path: Path,
        extract_images: bool,
        password: str,
    ) -> PDFReadResult:
        """Read PDF using PyMuPDF (fitz)."""
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))

        if doc.is_encrypted:
            if not password:
                doc.close()
                raise ValueError(
                    f"PDF is encrypted. Provide a password: "
                    f"PDFReader.read(password='...')"
                )
            result = doc.authenticate(password)
            if not result:
                doc.close()
                raise ValueError("Incorrect password for encrypted PDF")

        pages: list[str] = []
        images: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}

        try:
            info = doc.metadata or {}
            metadata = {
                "title": info.get("title", ""),
                "author": info.get("author", ""),
                "subject": info.get("subject", ""),
                "creator": info.get("creator", ""),
                "producer": info.get("producer", ""),
                "creationDate": info.get("creationDate", ""),
                "modDate": info.get("modDate", ""),
                "keywords": info.get("keywords", ""),
            }
        except Exception:
            pass

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            pages.append(text)

            if extract_images:
                image_list = page.get_images(full=True)
                for img_index, img in enumerate(image_list):
                    try:
                        xref = img[0]
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n < 5:
                            img_bytes = pix.tobytes("png")
                        else:
                            pix1 = fitz.Pixmap(fitz.csRGBAP, pix)
                            img_bytes = pix1.tobytes("png")
                        pix = None
                        if pix1:
                            pix1 = None

                        images.append({
                            "page": page_num,
                            "index": img_index,
                            "format": img[2] if len(img) > 2 else "unknown",
                            "size": len(img_bytes),
                            "data_base64": base64.b64encode(img_bytes).decode("ascii"),
                        })
                    except Exception as e:
                        logger.warning(f"Failed to extract image {img_index} from page {page_num}: {e}")

        doc.close()

        full_text = "\n\n".join(pages)
        return PDFReadResult(
            text=full_text,
            pages=pages,
            page_count=len(doc) if doc else 0,
            images=images,
            metadata=metadata,
            source=str(path),
            encrypted=doc.is_encrypted if hasattr(doc, 'is_encrypted') else False,
            raw_data=path.read_bytes() if path.exists() else None,
        )

    async def _read_pdfplumber(
        self,
        path: Path,
        extract_images: bool,
        password: str,
    ) -> PDFReadResult:
        """Read PDF using pdfplumber."""
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            pages: list[str] = []
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                pages.append(text)

            metadata = {}
            if pdf.metadata:
                metadata = {k: str(v) for k, v in pdf.metadata.items()}

        full_text = "\n\n".join(pages)
        return PDFReadResult(
            text=full_text,
            pages=pages,
            page_count=len(pdf.pages) if 'pdf' in dir() else 0,
            images=[],
            metadata=metadata,
            source=str(path),
            encrypted=False,
            raw_data=path.read_bytes() if path.exists() else None,
        )

    async def _apply_ocr(self, result: PDFReadResult) -> PDFReadResult:
        """Apply OCR to a scanned PDF."""
        try:
            from core.pdf.ocr import PDFOCR

            ocr = PDFOCR(language=self._ocr_lang)
            ocr_result = await ocr.process(result.source)
            result.text = ocr_result.text
            result.is_scanned = True
            result.pages = [ocr_result.text]
            return result
        except Exception as e:
            logger.warning(f"OCR failed: {e}. Returning text-only result.")
            return result

    def _fallback_metadata(self, path: Path, password: str) -> PDFInfo:
        """Fallback metadata extraction using only file stats."""
        return PDFInfo(
            file_path=str(path),
            file_size=path.stat().st_size,
            is_encrypted=False,
        )

    async def read_string(
        self,
        source: str | Path,
        **kwargs: Any,
    ) -> PDFReadResult:
        """Convenience method to read a PDF file."""
        return await self.read(source, **kwargs)

    async def read_bytes(
        self,
        data: bytes,
        filename: str = "document.pdf",
        **kwargs: Any,
    ) -> PDFReadResult:
        """Read a PDF from raw bytes."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = Path(tmp.name)

        try:
            result = await self.read(tmp_path, **kwargs)
            result.source = filename
            return result
        finally:
            tmp_path.unlink(missing_ok=True)

    async def read_stream(
        self,
        stream: BinaryIO,
        filename: str = "document.pdf",
        **kwargs: Any,
    ) -> PDFReadResult:
        """Read a PDF from a file-like stream."""
        data = stream.read()
        return await self.read_bytes(data, filename=filename, **kwargs)

    def clear_cache(self) -> None:
        """Clear the read cache."""
        self._cache.clear()
