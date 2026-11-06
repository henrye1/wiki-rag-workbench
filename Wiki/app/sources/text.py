import re


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
