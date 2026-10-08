import re

from .models import Chunk

_WS = re.compile(r"\s+")
_SENT = re.compile(r"(?<=[.;:])\s+")


def clean(text: str) -> str:
    text = _WS.sub(" ", text).strip()
    return re.sub(r"\s+([,.;:)])", r"\1", text)


def split_long(text: str, max_words: int) -> list[str]:
    """Split text into parts of <= max_words, breaking on sentence boundaries."""
    if len(text.split()) <= max_words:
        return [text]
    parts, buf, n = [], [], 0
    for sent in _SENT.split(text):
        w = len(sent.split())
        if buf and n + w > max_words:
            parts.append(" ".join(buf))
            buf, n = [], 0
        buf.append(sent)
        n += w
    if buf:
        parts.append(" ".join(buf))
    return parts


def chunk_plain(pages: list[str], max_words: int = 400, overlap: int = 50) -> list[Chunk]:
    """Generic chunker for non-IFRS docs: paragraph-packed windows per page."""
    chunks: list[Chunk] = []
    for pno, page in enumerate(pages, start=1):
        paras = [clean(p) for p in re.split(r"\n\s*\n", page) if p.strip()]
        buf: list[str] = []
        for p in paras:
            for piece in split_long(p, max_words):
                if buf and len(" ".join(buf + [piece]).split()) > max_words:
                    text = " ".join(buf)
                    chunks.append(Chunk(None, "general", pno, None, text))
                    tail = text.split()[-overlap:]
                    buf = [" ".join(tail)]
                buf.append(piece)
        if buf:
            chunks.append(Chunk(None, "general", pno, None, " ".join(buf)))
    return chunks
