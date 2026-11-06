from dataclasses import dataclass

# Documents published with a Standard (Parts B and C), by paragraph-number prefix (IE, IG, BC..., DO).
# Not part of the Standard, but searched by default: each passage is labelled with its kind.
ACCOMPANYING_TYPES = ("example", "implementation_guidance", "basis_for_conclusions", "dissenting_opinion")


@dataclass
class Chunk:
    para_ref: str | None
    source_type: str
    page: int
    heading: str | None
    content: str
    part: int = 0
    heading_path: tuple = ()  # ((level, heading), ...) from the top heading down to the one this text sits under

    def embed_text(self) -> str:
        head = " | ".join(x for x in (self.para_ref, self.heading) if x)
        return f"{head}\n{self.content}" if head else self.content
