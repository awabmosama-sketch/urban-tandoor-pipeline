from __future__ import annotations
from pathlib import Path

from docx import Document as DocxDocument


def _table_to_markdown(table) -> str:
    rows = []
    for row in table.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def load_docx_sections(path: Path) -> list[dict]:
    """Returns [{"section": heading_text, "text": paragraph/table text}].
    Groups consecutive paragraphs under the most recent Heading N. Tables
    are rendered as markdown and appended to the current section."""
    doc = DocxDocument(str(path))
    sections: list[dict] = []
    current_heading = "intro"
    current_parts: list[str] = []

    def flush():
        nonlocal current_parts
        text = "\n\n".join(p for p in current_parts if p.strip())
        if text.strip():
            sections.append({"section": current_heading, "text": text})
        current_parts = []

    for para in doc.paragraphs:
        style = (para.style.name or "").lower()
        if style.startswith("heading") and para.text.strip():
            flush()
            current_heading = para.text.strip()
        elif para.text.strip():
            current_parts.append(para.text.strip())

    for table in doc.tables:
        current_parts.append(_table_to_markdown(table))

    flush()
    return sections
