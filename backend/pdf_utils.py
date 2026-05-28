"""Small PDF export helpers for markdown CV previews."""

from __future__ import annotations

import re
from pathlib import Path


def markdown_to_plain_text(markdown: str) -> str:
    """Convert lightweight markdown to readable plain text for PDF export."""
    text = markdown.replace("\r\n", "\n")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def write_simple_pdf(text: str, output_path: Path, title: str) -> Path:
    """Write a minimal multi-page PDF with plain text content."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = _build_pdf_bytes(text, title)
    output_path.write_bytes(pdf_bytes)
    return output_path


def _build_pdf_bytes(text: str, title: str) -> bytes:
    page_width = 595
    page_height = 842
    left_margin = 48
    top_margin = 64
    line_height = 14
    max_chars = 88
    usable_lines = 50

    lines = _wrap_lines([title, "", *text.splitlines()], max_chars=max_chars)
    if not lines:
        lines = [title]
    pages = [lines[index:index + usable_lines] for index in range(0, len(lines), usable_lines)]

    objects: list[bytes] = []

    def add_object(payload: str | bytes) -> int:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        objects.append(data)
        return len(objects)

    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = add_object("<< /Type /Pages /Kids [] /Count 0 >>")
    page_ids: list[int] = []

    for page_number, page_lines in enumerate(pages, start=1):
        stream = _page_stream(page_lines, page_number, page_height, left_margin, top_margin, line_height)
        content_id = add_object(f"<< /Length {len(stream)} >>\nstream\n".encode("utf-8") + stream + b"\nendstream")
        page_id = add_object(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] /Count {len(page_ids)} >>".encode("utf-8")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode("utf-8"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("utf-8"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("utf-8")
    )
    return bytes(pdf)


def _page_stream(
    lines: list[str],
    page_number: int,
    page_height: int,
    left_margin: int,
    top_margin: int,
    line_height: int,
) -> bytes:
    commands = ["BT", "/F1 11 Tf"]
    y_position = page_height - top_margin
    for line in lines:
        escaped = _escape_pdf_text(line)
        commands.append(f"1 0 0 1 {left_margin} {y_position} Tm ({escaped}) Tj")
        y_position -= line_height
    commands.append("ET")
    return "\n".join(commands).encode("utf-8")


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(lines: list[str], max_chars: int) -> list[str]:
    wrapped: list[str] = []
    for raw_line in lines:
        line = raw_line.expandtabs(2).strip()
        if not line:
            wrapped.append("")
            continue
        current = line
        while len(current) > max_chars:
            split_at = current.rfind(" ", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            wrapped.append(current[:split_at].rstrip())
            current = current[split_at:].lstrip()
        wrapped.append(current)
    return wrapped
