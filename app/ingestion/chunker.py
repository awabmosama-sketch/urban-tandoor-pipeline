from __future__ import annotations


def chunk_text(
    text: str, chunk_size: int = 800, overlap: int = 120,
) -> list[str]:
    """Word-boundary chunking. chunk_size and overlap are WORD counts, not
    character counts. Preserves natural breakpoints (double newline, single
    newline, sentence). Returns list of non-empty chunks."""
    text = text.strip()
    if not text:
        return []
    words = text.split()
    if len(words) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    n = len(words)
    while start < n:
        end = min(start + chunk_size, n)
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_sections(
    sections: list[dict], chunk_size: int = 800, overlap: int = 120,
) -> list[dict]:
    """sections: [{"section": str, "text": str}]. Returns
    [{"section": str, "content": str, "token_count": int}] with section
    label preserved."""
    out: list[dict] = []
    for sec in sections:
        sec_label = sec.get("section") or "body"
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        for piece in chunk_text(text, chunk_size=chunk_size, overlap=overlap):
            out.append({
                "section": sec_label,
                "content": piece,
                "token_count": len(piece.split()),
            })
    return out
