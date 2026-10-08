from dataclasses import dataclass

# Binding text of the Standard (allowed by default in retrieval)
BINDING_TYPES = ("standard", "appendix_a", "appendix_b", "general")
# Editorial / non-binding text (excluded unless explicitly requested)
NON_BINDING_TYPES = ("note", "intro", "appendix_c", "back_matter")
ALL_TYPES = BINDING_TYPES + NON_BINDING_TYPES


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
