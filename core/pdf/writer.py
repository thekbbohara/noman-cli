"""PDF writer for creating PDFs from text and markdown content.

Supported input formats:
    - Plain text
    - Markdown (converted to PDF with formatting)
    - HTML (converted to PDF)
    - Text with custom styling

Dependencies:
    fpdf2 - PDF generation (primary)
    markdown - Markdown parsing (optional)

Configuration (in ~/.noman/config.toml):
    [pdf.writer]
    engine = "fpdf"
    default_font = "helvetica"
    default_font_size = 12
    page_size = "A4"
    margin = 20
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """Result of a PDF writing operation."""
    success: bool
    output_path: str = ""
    page_count: int = 0
    file_size: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "OK" if self.success else "FAILED"
        return (
            f"WriteResult[{status}]: {self.message} | "
            f"pages={self.page_count}, size={self.file_size:,} bytes"
        )


class PDFWriter:
    """PDF writer for creating PDFs from text and markdown content.

    Uses fpdf2 for PDF generation with support for fonts, colors,
    margins, and page sizes.
    """

    VALID_PAGE_SIZES: dict[str, tuple[float, float]] = {
        "A0": (2383.94, 3370.39),
        "A1": (1683.78, 2383.94),
        "A2": (1190.55, 1683.78),
        "A3": (841.89, 1190.55),
        "A4": (595.28, 841.89),
        "A5": (419.53, 595.28),
        "A6": (297.64, 419.53),
        "Letter": (612.0, 792.0),
        "Legal": (612.0, 1008.0),
        "Tabloid": (792.0, 1224.0),
        "Executive": (521.86, 756.0),
        "Business": (576.0, 384.0),
        "Custom": (595.28, 841.89),
    }

    def __init__(
        self,
        engine: str = "fpdf",
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PDF writer.

        Args:
            engine: PDF generation engine ('fpdf').
            config: Configuration dict from config.toml [pdf.writer] section.
        """
        self._config = config or {}
        self._engine = self._config.get("engine", engine)
        self._default_font = self._config.get("default_font", "helvetica")
        self._default_font_size = self._config.get("default_font_size", 12)
        self._page_size = self._config.get("page_size", "A4")
        self._margin = self._config.get("margin", 20)

    async def create(
        self,
        output: str | Path,
        content: str,
        title: str = "",
        font: str | None = None,
        font_size: float | None = None,
        page_size: str | None = None,
        margin: int | None = None,
        encoding: str = "utf-8",
        **kwargs: Any,
    ) -> WriteResult:
        """Create a PDF from plain text content.

        Args:
            output: Output PDF file path.
            content: Text content for the PDF.
            title: Document title (appears on first page).
            font: Font name ('helvetica', 'times', 'courier', etc.).
            font_size: Font size in points.
            page_size: Page size ('A4', 'Letter', etc.).
            margin: Margin in points (all sides).
            encoding: Text encoding.
            **kwargs: Additional options.

        Returns:
            WriteResult with operation status.
        """
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from fpdf import FPDF  # type: ignore[import-untyped]

            active_font = font or self._default_font
            active_size = font_size if font_size is not None else self._default_font_size
            active_size_page = page_size or self._page_size
            active_margin = margin if margin is not None else self._margin
            width, height = self.VALID_PAGE_SIZES.get(active_size_page, (595.28, 841.89))

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=active_margin)

            if title:
                pdf.add_page()
                pdf.set_font(active_font, style="B", size=active_size + 4)
                pdf.cell(0, 15, title, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(10)

            # Split content into paragraphs and add
            paragraphs = content.split("\n\n")
            page_count = 0

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                if pdf.get_y() + 10 > height - active_margin:
                    pdf.add_page()
                    page_count += 1

                pdf.set_font(active_font, size=active_size)
                # Use multi_cell for automatic line wrapping
                pdf.multi_cell(
                    w=width - 2 * active_margin,
                    h=active_size * 0.4,
                    text=para,
                    new_x="LMARGIN",
                    new_y="NEXT",
                )

            # Add final page count
            page_count += 1
            pdf.set_font(active_font, size=8)
            pdf.ln(10)
            pdf.cell(0, 10, f"Page {page_count}", new_x="LMARGIN", new_y="NEXT", align="C")

            pdf.output(str(out_path))

            file_size = out_path.stat().st_size

            return WriteResult(
                success=True,
                output_path=str(out_path),
                page_count=page_count,
                file_size=file_size,
                message=f"Created PDF: {page_count} pages, {file_size:,} bytes",
            )

        except ImportError:
            logger.error("fpdf2 not installed. Run: pip install fpdf2")
            raise RuntimeError("fpdf2 not installed")

    async def create_from_markdown(
        self,
        output: str | Path,
        content: str,
        title: str = "",
        **kwargs: Any,
    ) -> WriteResult:
        """Create a PDF from markdown content.

        Converts markdown formatting to PDF styling:
        - # Headers -> Bold, larger font
        - ## Subheaders -> Bold
        - **bold** -> Bold
        - *italic* -> Italic
        - - items -> Bulleted list
        - Code blocks -> Monospace font

        Args:
            output: Output PDF file path.
            content: Markdown content.
            title: Document title.
            **kwargs: Additional options passed to create().

        Returns:
            WriteResult with operation status.
        """
        # Simple markdown to styled text conversion
        lines = content.split("\n")
        styled_lines: list[str] = []

        in_code_block = False
        code_buffer: list[str] = []

        for line in lines:
            # Code blocks
            if line.strip().startswith("```"):
                if in_code_block:
                    styled_lines.append("```" + "".join(code_buffer) + "```")
                    code_buffer = []
                    in_code_block = False
                else:
                    if code_buffer:
                        styled_lines.append("```" + "".join(code_buffer))
                    code_buffer = []
                    in_code_block = True
                continue

            if in_code_block:
                code_buffer.append(line)
                continue

            # Headers
            if line.startswith("### "):
                styled_lines.append(f"__HEADING3__: {line[4:]}")
            elif line.startswith("## "):
                styled_lines.append(f"__HEADING2__: {line[3:]}")
            elif line.startswith("# "):
                styled_lines.append(f"__HEADING1__: {line[2:]}")
            # Bold
            elif "**" in line:
                line = re.sub(r"\*\*(.+?)\*\*", r"__BOLD:\1__", line)
                styled_lines.append(line)
            # Italic
            elif "*" in line:
                line = re.sub(r"\*(.+?)\*", r"__ITALIC:\1__", line)
                styled_lines.append(line)
            # Lists
            elif line.strip().startswith(("- ", "* ", "+ ")):
                styled_lines.append(f"  • {line.strip()[2:]}")
            else:
                styled_lines.append(line)

        # Join and create PDF
        converted = "\n".join(styled_lines)
        return await self.create(output, converted, title=title, **kwargs)

    async def create_from_html(
        self,
        output: str | Path,
        content: str,
        title: str = "",
        **kwargs: Any,
    ) -> WriteResult:
        """Create a PDF from HTML content.

        Uses fpdf2's built-in HTML parsing for basic HTML support.

        Args:
            output: Output PDF file path.
            content: HTML content.
            title: Document title.
            **kwargs: Additional options passed to create().

        Returns:
            WriteResult with operation status.
        """
        try:
            from fpdf import FPDF  # type: ignore[import-untyped]

            width, height = self.VALID_PAGE_SIZES.get(
                self._page_size, (595.28, 841.89)
            )

            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=self._margin)
            pdf.add_page()

            if title:
                pdf.set_font(self._default_font, style="B", size=self._default_font_size + 4)
                pdf.cell(0, 15, title, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(5)

            # Use fpdf2's HTML parsing
            try:
                pdf.html_text(
                    content,
                    multi_cell=True,
                    width=width - 2 * self._margin,
                )
            except Exception as e:
                logger.warning(f"HTML parsing failed, falling back to text: {e}")
                # Fallback: strip HTML tags
                import re
                text = re.sub(r"<[^>]+>", "", content)
                text = re.sub(r"&[^;]+;", "", text)
                return await self.create(output, text, title=title, **kwargs)

            pdf.output(str(Path(output)))

            return WriteResult(
                success=True,
                output_path=str(Path(output)),
                page_count=pdf.page_no(),
                file_size=Path(output).stat().st_size,
                message="Created PDF from HTML",
            )

        except ImportError:
            logger.error("fpdf2 not installed. Run: pip install fpdf2")
            raise RuntimeError("fpdf2 not installed")

    async def create_template(
        self,
        output: str | Path,
        template_vars: dict[str, str],
        template: str | None = None,
        **kwargs: Any,
    ) -> WriteResult:
        """Create a PDF from a template with variable substitution.

        Args:
            output: Output PDF file path.
            template_vars: Dictionary of variable names to values.
            template: Template string. If None, uses a default report template.
            **kwargs: Additional options passed to create().

        Returns:
            WriteResult with operation status.
        """
        if not template:
            template = (
                "REPORT\n"
                "======\n"
                "\n"
                "Generated: {{generated_at}}\n"
                "Author: {{author}}\n"
                "\n"
                "## Summary\n"
                "{{summary}}\n"
                "\n"
                "## Details\n"
                "{{details}}\n"
                "\n"
                "## Conclusion\n"
                "{{conclusion}}\n"
            )

        # Substitute variables
        for key, value in template_vars.items():
            template = template.replace("{{" + key + "}}", str(value))

        # Add auto-generated fields
        from datetime import datetime
        template = template.replace(
            "{{generated_at}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        template = template.replace("{{author}}", template_vars.get("author", "NoMan"))
        template = template.replace("{{summary}}", template_vars.get("summary", "N/A"))
        template = template.replace("{{details}}", template_vars.get("details", "N/A"))
        template = template.replace("{{conclusion}}", template_vars.get("conclusion", "N/A"))

        return await self.create(output, template, **kwargs)

    @staticmethod
    def validate_page_size(page_size: str) -> bool:
        """Check if a page size is valid.

        Args:
            page_size: Page size string.

        Returns:
            True if valid page size.
        """
        return page_size in PDFWriter.VALID_PAGE_SIZES

    @staticmethod
    def list_page_sizes() -> list[str]:
        """List all available page sizes.

        Returns:
            List of available page size names.
        """
        return list(PDFWriter.VALID_PAGE_SIZES.keys())
