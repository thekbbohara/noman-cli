"""PDF editor for merging, splitting, and annotating PDFs.

Supported operations:
    - Merge multiple PDFs into one
    - Split PDF into individual pages or page ranges
    - Add annotations (text, highlights, stamps)
    - Rotate pages
    - Extract specific page ranges

Dependencies:
    PyMuPDF (fitz) - primary PDF engine

Configuration (in ~/.noman/config.toml):
    [pdf.editor]
    engine = "pymupdf"
    default_quality = 0.9
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EditResult:
    """Result of a PDF editing operation."""
    success: bool
    output_path: str | None = None
    pages_modified: int = 0
    pages_total: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "OK" if self.success else "FAILED"
        return (
            f"EditResult[{status}]: {self.message} | "
            f"modified={self.pages_modified}/{self.pages_total}"
        )


class PDFEditor:
    """PDF editor supporting merge, split, annotate, and transform operations.

    Uses PyMuPDF (fitz) for all PDF manipulation.
    """

    def __init__(
        self,
        engine: str = "pymupdf",
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PDF editor.

        Args:
            engine: PDF engine to use.
            config: Configuration dict from config.toml [pdf.editor] section.
        """
        self._config = config or {}
        self._engine = self._config.get("engine", engine)
        self._default_quality = self._config.get("default_quality", 0.9)

    async def merge(
        self,
        inputs: list[str | Path],
        output: str | Path,
        page_ranges: list[tuple[int, int]] | None = None,
    ) -> EditResult:
        """Merge multiple PDFs into a single PDF.

        Args:
            inputs: List of input PDF file paths.
            output: Output PDF file path.
            page_ranges: Optional list of (start, end) page ranges per input.

        Returns:
            EditResult with operation status.

        Raises:
            FileNotFoundError: If any input file does not exist.
            ValueError: If inputs list is empty.
        """
        if not inputs:
            raise ValueError("No input files provided for merge")

        for inp in inputs:
            if not Path(inp).exists():
                raise FileNotFoundError(f"Input file not found: {inp}")

        try:
            import fitz  # PyMuPDF

            out_doc = fitz.open()

            for idx, inp_path in enumerate(inputs):
                path = Path(inp_path)
                in_doc = fitz.open(str(path))

                # Apply page range if specified
                if page_ranges and idx < len(page_ranges):
                    start, end = page_ranges[idx]
                    for page_num in range(max(0, start), min(len(in_doc), end + 1)):
                        out_doc.insert_pdf(in_doc, from_page=page_num, to_page=page_num)
                else:
                    out_doc.insert_pdf(in_doc)

                in_doc.close()

            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_doc.save(str(out_path))
            out_doc.close()

            return EditResult(
                success=True,
                output_path=str(out_path),
                pages_modified=len(out_doc),
                pages_total=len(out_doc),
                message=f"Merged {len(inputs)} PDFs into {out_path}",
            )

        except ImportError:
            logger.error("PyMuPDF not installed. Run: pip install PyMuPDF")
            raise
        except Exception as e:
            logger.error(f"Merge failed: {e}")
            return EditResult(success=False, message=f"Merge failed: {e}")

    async def split(
        self,
        source: str | Path,
        output_dir: str | Path | None = None,
        page_ranges: list[tuple[int, int]] | None = None,
        single_page: bool = False,
    ) -> list[EditResult]:
        """Split a PDF into multiple PDFs.

        Args:
            source: Input PDF file path.
            output_dir: Directory for output files. Defaults to source directory.
            page_ranges: Specific page ranges to extract as separate PDFs.
            single_page: If True, create one PDF per page.

        Returns:
            List of EditResults for each output file.

        Raises:
            FileNotFoundError: If the source file does not exist.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        if not output_dir:
            output_dir = path.parent

        results: list[EditResult] = []

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(path))

            if single_page:
                for page_num in range(len(doc)):
                    out_doc = fitz.open()
                    out_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    out_path = Path(output_dir) / f"{path.stem}_page_{page_num + 1}.pdf"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_doc.save(str(out_path))
                    out_doc.close()
                    results.append(EditResult(
                        success=True,
                        output_path=str(out_path),
                        pages_modified=1,
                        pages_total=1,
                        message=f"Extracted page {page_num + 1}",
                    ))
            elif page_ranges:
                for idx, (start, end) in enumerate(page_ranges):
                    out_doc = fitz.open()
                    for page_num in range(max(0, start), min(len(doc), end + 1)):
                        out_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    out_path = Path(output_dir) / f"{path.stem}_range_{idx + 1}.pdf"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_doc.save(str(out_path))
                    out_doc.close()
                    results.append(EditResult(
                        success=True,
                        output_path=str(out_path),
                        pages_modified=len(doc) if len(doc) > 0 else 0,
                        pages_total=len(doc),
                        message=f"Extracted pages {start}-{end}",
                    ))
            else:
                # Split all pages
                for page_num in range(len(doc)):
                    out_doc = fitz.open()
                    out_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
                    out_path = Path(output_dir) / f"{path.stem}_page_{page_num + 1}.pdf"
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_doc.save(str(out_path))
                    out_doc.close()
                    results.append(EditResult(
                        success=True,
                        output_path=str(out_path),
                        pages_modified=1,
                        pages_total=1,
                        message=f"Extracted page {page_num + 1}",
                    ))

            doc.close()
            return results

        except ImportError:
            logger.error("PyMuPDF not installed. Run: pip install PyMuPDF")
            raise
        except Exception as e:
            logger.error(f"Split failed: {e}")
            return [EditResult(success=False, message=f"Split failed: {e}")]

    async def annotate(
        self,
        source: str | Path,
        output: str | Path,
        annotations: list[dict[str, Any]],
    ) -> EditResult:
        """Add annotations to a PDF.

        Supported annotation types:
            - text: Add text annotation
            - highlight: Highlight text region
            - stamp: Add stamp/watermark
            - link: Add hyperlinks

        Args:
            source: Input PDF file path.
            output: Output PDF file path.
            annotations: List of annotation dicts with 'type' and parameters.

        Returns:
            EditResult with operation status.

        Raises:
            FileNotFoundError: If the source file does not exist.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(path))
            pages_modified = 0

            for ann in annotations:
                ann_type = ann.get("type", "")
                page_num = ann.get("page", 0)

                if page_num >= len(doc):
                    continue

                page = doc[page_num]

                if ann_type == "text":
                    text = ann.get("text", "")
                    point = ann.get("point", (100, 100))
                    color = ann.get("color", [1, 0, 0])
                    fontsize = ann.get("fontsize", 12)
                    page.insert_text(
                        point,
                        text,
                        fontsize=fontsize,
                        fontname=ann.get("font", "helv"),
                        color=color,
                    )
                    pages_modified += 1

                elif ann_type == "highlight":
                    rect = ann.get("rect", (0, 0, 100, 20))
                    color = ann.get("color", [1, 1, 0])
                    page.draw_rect(rect, color=color, fill=color, width=0)
                    pages_modified += 1

                elif ann_type == "stamp":
                    stamp = ann.get("stamp", "")
                    point = ann.get("point", (100, 100))
                    fontsize = ann.get("fontsize", 48)
                    page.insert_text(
                        point,
                        stamp,
                        fontsize=fontsize,
                        color=ann.get("color", [0.5, 0.5, 0.5]),
                    )
                    pages_modified += 1

                elif ann_type == "link":
                    rect = ann.get("rect", (0, 0, 100, 20))
                    uri = ann.get("uri", "")
                    page.insert_link({
                        "kind": fitz.LINK_URI,
                        "from": rect,
                        "uri": uri,
                    })
                    pages_modified += 1

                elif ann_type == "stamp_image":
                    img_path = ann.get("image", "")
                    point = ann.get("point", (100, 100))
                    scale = ann.get("scale", 1.0)
                    if img_path and Path(img_path).exists():
                        page.insert_image_shape(point, filename=str(img_path), scale=scale)
                        pages_modified += 1

            doc.save(str(out_path))
            doc.close()

            return EditResult(
                success=True,
                output_path=str(out_path),
                pages_modified=pages_modified,
                pages_total=len(doc),
                message=f"Added {len(annotations)} annotations to {pages_modified} pages",
            )

        except ImportError:
            logger.error("PyMuPDF not installed. Run: pip install PyMuPDF")
            raise
        except Exception as e:
            logger.error(f"Annotation failed: {e}")
            return EditResult(success=False, message=f"Annotation failed: {e}")

    async def rotate(
        self,
        source: str | Path,
        output: str | Path,
        angles: dict[int, int] | None = None,
        default_angle: int = 0,
    ) -> EditResult:
        """Rotate pages of a PDF.

        Args:
            source: Input PDF file path.
            output: Output PDF file path.
            angles: Dict mapping page numbers to rotation angles (0, 90, 180, 270).
            default_angle: Default rotation for pages not in angles dict.

        Returns:
            EditResult with operation status.

        Raises:
            FileNotFoundError: If the source file does not exist.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(path))
            pages_modified = 0

            for page_num in range(len(doc)):
                angle = angles.get(page_num, default_angle) if angles else default_angle
                if angle != 0:
                    doc[page_num].rotate(angle)
                    pages_modified += 1

            doc.save(str(out_path))
            doc.close()

            return EditResult(
                success=True,
                output_path=str(out_path),
                pages_modified=pages_modified,
                pages_total=len(doc),
                message=f"Rotated {pages_modified} pages",
            )

        except ImportError:
            logger.error("PyMuPDF not installed. Run: pip install PyMuPDF")
            raise
        except Exception as e:
            logger.error(f"Rotate failed: {e}")
            return EditResult(success=False, message=f"Rotate failed: {e}")

    async def compress(
        self,
        source: str | Path,
        output: str | Path,
        quality: float | None = None,
    ) -> EditResult:
        """Compress a PDF by reducing image quality.

        Args:
            source: Input PDF file path.
            output: Output PDF file path.
            quality: JPEG quality (0.0-1.0). Defaults to 0.9.

        Returns:
            EditResult with operation status.
        """
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {source}")

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        active_quality = quality if quality is not None else self._default_quality

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(path))
            doc.save(
                str(out_path),
                garbage=4,
                deflate=True,
                clean=True,
                jpeg_quality=int(active_quality * 100),
            )
            doc.close()

            in_size = path.stat().st_size
            out_size = out_path.stat().st_size
            reduction = ((in_size - out_size) / in_size * 100) if in_size > 0 else 0

            return EditResult(
                success=True,
                output_path=str(out_path),
                pages_modified=len(doc),
                pages_total=len(doc),
                message=f"Compressed: {in_size:,} -> {out_size:,} bytes ({reduction:.1f}% reduction)",
            )

        except ImportError:
            logger.error("PyMuPDF not installed. Run: pip install PyMuPDF")
            raise
        except Exception as e:
            logger.error(f"Compress failed: {e}")
            return EditResult(success=False, message=f"Compress failed: {e}")
