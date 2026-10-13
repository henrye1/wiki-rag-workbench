from dataclasses import dataclass

# Binding text of the Standard (allowed by default in retrieval)
BINDING_TYPES = ("standard", "appendix_a", "appendix_b", "general")
# Documents published with a Standard (Parts B and C), by paragraph-number prefix (IE, IG, BC..., DO).
# Not part of the Standard, but searched by default: each passage is labelled with its kind.
ACCOMPANYING_TYPES = ("example", "implementation_guidance", "basis_for_conclusions", "dissenting_opinion")
# Editorial / non-binding text (excluded unless explicitly requested)
NON_BINDING_TYPES = ("note", "intro", "appendix_c", "back_matter")
ALL_TYPES = BINDING_TYPES + ACCOMPANYING_TYPES + NON_BINDING_TYPES


@dataclass
class Chunk:
    para_ref: str | None
    source_type: str
    page: int
    heading: str | None
    content: str
    part: int = 0

    def embed_text(self) -> str:
        head = " | ".join(x for x in (self.para_ref, self.heading) if x)
        return f"{head}\n{self.content}" if head else self.content
