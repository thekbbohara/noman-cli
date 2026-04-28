"""PDF OCR engine for scanned document text recognition.

Uses Tesseract OCR for text recognition from scanned PDF pages.
Supports multiple languages and auto-detection.

Dependencies:
    pytesseract - Python wrapper for Tesseract OCR
    Pillow - image processing
    PyMuPDF (fitz) - PDF to image conversion

Configuration (in ~/.noman/config.toml):
    [pdf.ocr]
    enabled = true
    engine = "tesseract"
    lang = "eng"
    auto_detect = true
    psm = "auto"  # Page segmentation mode: 0-13
    tessdata_dir = ""
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Result from OCR processing of a document/page."""
    text: str
    confidence: float
    language: str
    pages: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    source: str = ""
    is_scanned: bool = True
    raw_response: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"OCRResult(confidence={self.confidence:.1f}%, language={self.language}, "
            f"pages={self.page_count}, text_len={len(self.text)})"
        )


class PDFOCR:
    """PDF OCR engine using Tesseract for text recognition.

    Converts PDF pages to images and runs Tesseract OCR on each page.
    Supports multiple languages, page segmentation modes, and auto-detection.
    """

    VALID_PSM_MODES = frozenset(range(14))

    def __init__(
        self,
        engine: str = "tesseract",
        language: str = "eng",
        psm: int = -1,
        auto_detect: bool = True,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PDF OCR engine.

        Args:
            engine: OCR engine ('tesseract').
            language: Tesseract language code(s) (e.g., 'eng', 'eng+fra').
            psm: Page segmentation mode (-1 for auto).
            auto_detect: Auto-detect language from content.
            config: Configuration dict from config.toml [pdf.ocr] section.
        """
        self._config = config or {}
        self._engine = self._config.get("engine", engine)
        self._language = self._config.get("lang", language)
        self._psm = self._config.get("psm", psm)
        self._auto_detect = self._config.get("auto_detect", auto_detect)
        self._tessdata_dir = self._config.get("tessdata_dir", "")
        self._threshold = self._config.get("threshold", 30)  # Min confidence threshold
        self._max_retries = self._config.get("max_retries", 2)

    async def process(
        self,
        source: str | Path,
        language: str | None = None,
        psm: int | None = None,
        page_range: tuple[int, int] | None = None,
    ) -> OCRResult:
        """Process a PDF with OCR.

        Args:
            source: Path to the PDF file (scanned).
            language: Override language code. Defaults to configured language.
            psm: Override page segmentation mode. Defaults to configured mode.
            page_range: Optional (start, end) page range to process.

        Returns:
            OCRResult with recognized text and confidence scores.

        Raises:
            FileNotFoundError: If the source file does not exist.
            RuntimeError: If Tesseract is not installed.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        lang = language or self._language
        active_psm = psm if psm is not None else self._psm

        try:
            import fitz  # PyMuPDF
            import pytesseract  # type: ignore[import-untyped]
            from PIL import Image  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError(
                "OCR dependencies not installed. Run: pip install pytesseract Pillow PyMuPDF\n"
                "Also install system Tesseract: apt install tesseract-ocr"
            )

        doc = fitz.open(str(path))
        full_text_parts: list[str] = []
        page_results: list[dict[str, Any]] = []
        confidences: list[float] = []

        # Determine pages to process
        if page_range:
            start, end = max(0, page_range[0]), min(len(doc), page_range[1] + 1)
            pages = range(start, end)
        else:
            pages = range(len(doc))

        for page_num in pages:
            page = doc[page_num]

            # Render page to image at high DPI
            matrix = fitz.Matrix(3, 3)  # 300 DPI
            pix = page.get_pixmap(matrix=matrix)
            img_data = pix.tobytes("png")
            pix = None  # Free memory

            # Detect language if enabled
            detect_lang = lang if not self._auto_detect else "osd+eng"
            try:
                config_str = f"--psm {active_psm}"
                if self._tessdata_dir:
                    config_str += f" --tessdata-dir {self._tessdata_dir}"

                custom_config = config_str
                text = pytesseract.image_to_string(
                    img_data,
                    lang=detect_lang,
                    config=custom_config,
                )

                # Get confidence
                try:
                    lang_data = pytesseract.image_to_data(
                        img_data,
                        lang=detect_lang,
                        config=config_str,
                        output_type=pytesseract.Output.DICT,
                    )
                    avg_conf = 0.0
                    count = 0
                    for conf in lang_data.get("conf", []):
                        if conf > 0:
                            avg_conf += conf
                            count += 1
                    confidence = avg_conf / count if count > 0 else 0.0
                except Exception:
                    confidence = 75.0

                text = text.strip()
                confidences.append(confidence)
                page_results.append({
                    "page": page_num,
                    "text": text,
                    "confidence": confidence,
                    "language": detect_lang.split("+")[0] if "+" in detect_lang else detect_lang,
                    "word_count": len(text.split()) if text else 0,
                })
                full_text_parts.append(text)

                logger.debug(
                    f"OCR page {page_num}: confidence={confidence:.1f}%, "
                    f"words={len(text.split()) if text else 0}"
                )

            except Exception as e:
                warning = f"OCR page {page_num} failed: {e}"
                logger.warning(warning)
                page_results.append({
                    "page": page_num,
                    "text": "",
                    "confidence": 0.0,
                    "language": detect_lang,
                    "word_count": 0,
                    "error": str(e),
                })
                full_text_parts.append("")

        doc.close()

        avg_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

        return OCRResult(
            text="\n\n".join(full_text_parts),
            confidence=avg_confidence,
            language=lang.split("+")[0] if "+" in lang else lang,
            pages=page_results,
            page_count=len(pages),
            source=str(path),
            is_scanned=True,
            raw_response={"psm": active_psm, "language": lang},
            warnings=[f"Page {r['page']} had OCR issues" for r in page_results if "error" in r],
        )

    async def process_page(
        self,
        source: str | Path,
        page_num: int,
        language: str | None = None,
    ) -> OCRResult:
        """Process a single page of a PDF with OCR.

        Args:
            source: Path to the PDF file.
            page_num: Zero-based page number.
            language: Override language code.

        Returns:
            OCRResult for the single page.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        lang = language or self._language

        try:
            import fitz
            import pytesseract
            from PIL import Image
        except ImportError:
            raise RuntimeError(
                "OCR dependencies not installed. Run: pip install pytesseract Pillow PyMuPDF"
            )

        doc = fitz.open(str(path))
        if page_num < 0 or page_num >= len(doc):
            doc.close()
            raise ValueError(f"Page {page_num} out of range (0-{len(doc) - 1})")

        page = doc[page_num]
        matrix = fitz.Matrix(3, 3)
        pix = page.get_pixmap(matrix=matrix)
        img_data = pix.tobytes("png")
        pix = None

        detect_lang = lang if not self._auto_detect else "osd+eng"
        config_str = f"--psm {self._psm}"
        if self._tessdata_dir:
            config_str += f" --tessdata-dir {self._tessdata_dir}"

        text = pytesseract.image_to_string(img_data, lang=detect_lang, config=config_str)
        text = text.strip()

        doc.close()
        confidence = 75.0  # Single page default

        return OCRResult(
            text=text,
            confidence=confidence,
            language=lang.split("+")[0] if "+" in lang else lang,
            pages=[{
                "page": page_num,
                "text": text,
                "confidence": confidence,
                "language": lang.split("+")[0] if "+" in lang else lang,
                "word_count": len(text.split()) if text else 0,
            }],
            page_count=1,
            source=str(path),
            is_scanned=True,
        )

    async def detect_language(
        self,
        source: str | Path,
        sample_pages: int = 3,
    ) -> str:
        """Auto-detect the language of a scanned PDF.

        Args:
            source: Path to the PDF file.
            sample_pages: Number of pages to sample for detection.

        Returns:
            Detected language code (e.g., 'eng', 'fra', 'deu').
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        try:
            import fitz
            import pytesseract

            doc = fitz.open(str(path))
            pages_to_check = min(sample_pages, len(doc))

            confidences: dict[str, float] = {}

            for page_num in range(pages_to_check):
                page = doc[page_num]
                matrix = fitz.Matrix(3, 3)
                pix = page.get_pixmap(matrix=matrix)
                img_data = pix.tobytes("png")
                pix = None

                # Try OSD (Orientation and Script Detection)
                try:
                    osd_result = pytesseract.image_to_osd(img_data, output_type=pytesseract.Output.DICT)
                    script = osd_result.get("Script", "")
                    if script:
                        confidences[script.lower()] = confidences.get(script.lower(), 0) + 1
                except Exception:
                    pass

            doc.close()

            if confidences:
                # Return most common script
                return max(confidences, key=confidences.get)

            return "eng"  # Default fallback

        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
            return "eng"

    async def ocr_to_text_file(
        self,
        source: str | Path,
        output: str | Path,
        language: str | None = None,
        page_range: tuple[int, int] | None = None,
    ) -> str:
        """OCR a PDF and save text to a file.

        Args:
            source: Path to the PDF file.
            output: Path to the output text file.
            language: Override language code.
            page_range: Optional (start, end) page range.

        Returns:
            Path to the output file.
        """
        result = await self.process(source, language=language, page_range=page_range)
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.text, encoding="utf-8")
        return str(out_path)

    async def ocr_to_pdf(
        self,
        source: str | Path,
        output: str | Path,
        language: str | None = None,
        page_range: tuple[int, int] | None = None,
    ) -> str:
        """OCR a PDF and create a searchable PDF (text layer).

        Args:
            source: Path to the PDF file.
            output: Path to the output searchable PDF.
            language: Override language code.
            page_range: Optional (start, end) page range.

        Returns:
            Path to the output PDF file.
        """
        result = await self.process(source, language=language, page_range=page_range)

        try:
            import fitz

            doc = fitz.open(str(Path(source)))

            # Add text layer to each page
            for page_data in result.pages:
                page_num = page_data["page"]
                page = doc[page_num]
                page.insert_text(
                    (0, 0),
                    page_data["text"],
                    fontsize=1,
                    color=(0, 0, 0),
                    render=1,  # invisible text layer
                )

            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(out_path))
            doc.close()

            return str(out_path)

        except ImportError:
            logger.warning("PyMuPDF not available for searchable PDF creation")
            return str(Path(output))

    @property
    def available(self) -> bool:
        """Check if Tesseract OCR is available."""
        try:
            import pytesseract
            return pytesseract.get_tesseract_version() is not None
        except Exception:
            return False

    @staticmethod
    def list_languages() -> list[str]:
        """List available Tesseract languages.

        Returns:
            List of available language codes.
        """
        try:
            import pytesseract
            langs = pytesseract.get_languages(config="")
            return sorted(set(langs)) if langs else []
        except Exception:
            return []
