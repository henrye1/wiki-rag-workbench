"""The PDF reader's publisher settings, read from Wiki/reader-settings.md (a file a person can read and change): the
headings that start and end a Standard's own text, its appendices, the prefixes of paragraph numbers, implementation
guidance, and the fonts and page positions of the publisher's layout. This module only turns that file into values."""
import pathlib
import re

FILE = pathlib.Path(__file__).resolve().parents[2] / "reader-settings.md"


def _sections(md: str) -> dict[str, list[str]]:
    """Each "## " heading (lower case) with its "- " lines, as written."""
    out: dict[str, list[str]] = {}
    for block in re.split(r"(?m)^## ", md)[1:]:
        head, _, body = block.partition("\n")
        out[head.strip().casefold()] = [m.strip() for m in re.findall(r"(?m)^- (.+)$", body)]
    return out


def _pairs(lines: list[str], sep: str) -> dict[str, str]:
    return {k.strip(): v.strip() for k, v in (x.split(sep, 1) for x in lines if sep in x)}


def _prefix_re(prefix: str) -> str:
    """A prefix as written in the file, as a pattern: <letter> is one capital letter, <up to 3 letters> none to three."""
    return (re.escape(prefix).replace(re.escape("<letter>"), "[A-Z]").replace(re.escape("<up to 3 letters>"), "[A-Z]{0,3}"))


def _ending_re(ending: str) -> str:
    """An ending as written in the file, as a pattern."""
    return (re.escape(ending).replace(re.escape("<up to 2 capital letters>"), "[A-Z]{0,2}")
            .replace(re.escape("<capital letters>"), "[A-Z]+").replace(re.escape("<digits>"), r"\d+"))


def load(path: pathlib.Path = FILE) -> dict:
    s = _sections(path.read_text(encoding="utf-8"))
    get = lambda name: s.get(name.casefold(), [])
    accompanying = _pairs(get("Paragraph numbers in documents published with a Standard"), "=")
    ig = _pairs(get("Implementation guidance"), ":")
    lay = _pairs(get("Publisher fonts and page layout"), ":")
    first, last = ig["Question letters"].split("-")
    return {
        "starts": [x.casefold() for x in get("Where a Standard's own text starts")],
        "appendices": {k.casefold(): v for k, v in _pairs(get("Appendices of a Standard"), "=").items()},
        "ends": [x.casefold() for x in get("Where a Standard's own text ends")],
        "para_prefixes": [_prefix_re(x) for x in get("Paragraph numbers in a Standard")],
        "para_endings": [_ending_re(x) for x in get("How a paragraph number may end")],  # longest first, as written
        "accompanying": {_prefix_re(k): v for k, v in accompanying.items()},  # prefix pattern -> reader kind
        "kind_labels": _pairs(get("Kind shown before each paragraph of a document published with a Standard"), "="),
        "ig_title": ig["Title begins"], "ig_letters": f"[{first}-{last}]", "ig_prefix": ig["Question label prefix"],
        "ig_intro": ig["Introduction label"],
        "body_font": lay["Body font begins"], "heading_font": lay["Heading font begins"],
        "heading_min": float(lay["Smallest heading size"]), "editorial_font": lay["Editorial font contains"],
        "box_heading_font": lay["Editorial box heading font"], "box_heading_below": float(lay["Editorial box heading smaller than"]),
        "box_heading_left_of": float(lay["Editorial box heading left of"]), "header_font": lay["Header and footer font contains"],
        "header_min": float(lay["Smallest header and footer size"]), "header_y": float(lay["Header above"]),
        "footer_y": float(lay["Footer below"]), "margin_x": float(lay["Paragraph numbers left of"]),
    }
