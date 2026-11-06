"""Concept pages, built by the engine from the wiki's own pages as the schema's Checks lists set out (Concept pages,
Concept lines, Concept term match, Concept slug, Concept summary). No AI call is made and no claim is written: each
page lists, one line per clause per holding page, the claims on the topic and subtopic pages about its concept, as
their citation, the source heading the clause sits under and a link to the page that holds them.

A concept is a defined term (one the page that defines the wiki's terms cites in the Defined-term citation form) or a
major heading of a source's own text (paragraphs of no kind the schema's Paragraph kinds names): the highest heading
level whose headings carry a number of more than one part, or the top level where none does, kept only where its
lines sit on at least the schema's number of pages. Every concept page is rebuilt each time, cleared as well as
written, so a concept whose lines have gone goes too."""
import re

from ..wiki import checks, store

NUMBERED = re.compile(r"^(\d+(?:\.\d+)+)\s")  # a heading's own number of more than one part ("5.5 Impairment")
RANGE = re.compile(r"\s*[–—-]\s*")


def _labels(group: str) -> list[str]:
    """The paragraph labels a citation names ("5.5.3, 5.5.4", "paragraphs B4.1.1–B4.1.26"), sub-paragraph letters
    aside; a range names its two ends."""
    group = re.sub(r"^\s*(?:paragraphs?|paras?)\s+", "", group.strip(), flags=re.I)
    out = []
    for part in re.split(r"\s*(?:[,;]|\band\b)\s*", group):
        out += [x for x in RANGE.split(part) if x] if ":" not in part else [part]
    return [re.sub(r"(?:\s*\([^)]*\))+$", "", x).strip() for x in out if x.strip()]


def _term_re(term: str, match: dict) -> re.Pattern:
    """A defined term as the schema's Concept term match finds it: whole words, case and the listed endings."""
    base, ends = term, [e for e in match.get("endings") or []]
    for e in ends:
        if base.casefold().endswith(e.casefold()) and len(base) > len(e) + 2:
            base = base[: -len(e)]
            break
    pat = re.escape(base).replace(r"\ ", r"\s+") + (f"(?:{'|'.join(map(re.escape, ends))})?" if ends else "")
    if match.get("words", True):
        pat = rf"(?<![\w-]){pat}(?![\w-])"
    return re.compile(pat, 0 if match.get("case") else re.I)


def _fill(template: str, values: list[str]) -> str:
    """A schema form with its placeholders ("<...>") filled in order."""
    it = iter(values)
    return checks.PLACEHOLDER.sub(lambda m: next(it, m.group(0)), template)


def _statements(content: str) -> list[str]:
    """A page's statements, line by line, each line cut into its sentences by the one sentence split (checks.sentences)."""
    out = []
    for line in content.split("\n"):
        line = line.strip().lstrip("-*• ").strip()
        if line and not line.startswith("#"):
            out += [s for s in checks.sentences(line) if s.strip()]
    return out


def _plain(statement: str) -> str:
    """A statement's words, its citations left out and other links read as their text."""
    s = re.sub(r"\[\[source-[^\]]*\]\]", " ", statement)
    return store.LINK_RE.sub(lambda m: m.group(2) or m.group(1), s)


def _slug(chk, framework: str, name: str, number: str | None = None) -> str:
    form = chk.concept_slug or "<framework>-concept-<term>"
    part = number.replace(".", "-") if number else " ".join(name.split()[: chk.concept_slug_words or len(name.split())])
    return store.slugify(re.sub(r"<term[^>]*>", part, form.replace("<framework>", framework)))


def build(chk, pages: dict[str, dict], sources: dict[str, dict], sections: list[dict], section_of, framework: str,
          existing: dict[str, dict]) -> list[store.Op]:
    """The concept pages, as ops against the wiki as it will stand: a create or update for each concept the lists
    give, and a delete for each concept page no longer given. pages: slug -> type, title, content_md (every page);
    sources: _source_paths (each paragraph's heading path, printed heading and kind); section_of: page slug -> its
    section ({num, name}) or None; framework: the prefix the wiki's section slugs carry (e.g. ifrs-9)."""
    if not (chk.concept_terms or chk.concept_heading_pages or chk.entity_pages) or not chk.concept_line:
        return []
    holders = {sl: p for sl, p in pages.items() if p["type"] in ("topic", "subtopic")}
    order = {sec["num"]: k for k, sec in enumerate(sections)}

    # the terms, from the page that defines the wiki's terms (the page citing most of them)
    held = {sl: checks.defined_terms(p["content_md"], chk) for sl, p in pages.items() if p["type"] in ("topic", "subtopic")}
    terms_page = max(held, key=lambda sl: len(held[sl]), default=None)
    prefix = chk.defined_term_form.split("<", 1)[0] if "<" in chk.defined_term_form else ""
    terms: dict[str, str] = {}  # term -> its citation on the terms page
    if chk.concept_terms and terms_page and held[terms_page]:
        for m in store.LINK_RE.finditer(pages[terms_page]["content_md"]):
            lab = (m.group(2) or "").strip()
            if m.group(1).startswith("source-") and prefix and lab.startswith(prefix):
                term = re.sub(r"\s*\([a-z0-9]{1,3}\)$", "", lab[len(prefix):].strip())
                terms.setdefault(term, f"[[{m.group(1)}|{prefix}{term}]]" if f"{prefix}{term}" in
                                 sources.get(m.group(1), {}).get("own", {}) else m.group(0))
    term_res = sorted(((t, _term_re(t, chk.concept_match)) for t in terms), key=lambda x: -len(x[0]))

    # the major headings of each source's own text: the paragraphs under each, and its level
    heading_of: dict[tuple[str, str], tuple[str, str | None]] = {}  # (source, label) -> (heading, its number)
    if chk.concept_heading_pages:
        for s_slug, info in sources.items():
            own = {lab: path for lab, path in info["own"].items()
                   if not chk.kinds.get(info["kinds"].get(lab) or info["route_kind"].get(lab) or "")
                   and not (prefix and lab.startswith(prefix)) and path}
            level = next((k for k in range(max((len(p) for p in own.values()), default=0))
                          if any(len(p) > k and NUMBERED.match(p[k]) for p in own.values())), 0)
            # the heading that holds the defined terms is not a concept: each of its terms is
            # (the heading whose paragraphs are mostly defined terms; a term printed again in the text does not count)
            n_terms, n_all = {}, {}
            for lab, path in info["own"].items():
                if len(path) > level:
                    n_all[path[level]] = n_all.get(path[level], 0) + 1
                    n_terms[path[level]] = n_terms.get(path[level], 0) + bool(prefix and lab.startswith(prefix))
            of_terms = {h for h, n in n_all.items() if n_terms[h] * 2 > n}
            major = {path[level] for path in own.values() if len(path) > level} - of_terms
            # under a heading: its own paragraphs, and the guidance filed with them (the schema's Guidance filed with
            # its requirement), which the source's numbering places under it
            for lab, path in info["own"].items():
                kind = chk.kinds.get(info["kinds"].get(lab) or info["route_kind"].get(lab) or "")
                if len(path) > level and path[level] in major and (not kind or kind in chk.guidance_kinds):
                    h = path[level]
                    heading_of[(s_slug, lab)] = (h, (m.group(1) if (m := NUMBERED.match(h)) else None))

    # the entities: each designation in one of the schema's Document names forms, other than the wiki's own sources
    names_re = None
    if chk.entity_pages and chk.entity_lines and chk.document_names and chk.entity_slug:
        names_re = re.compile(r"(?<![\w-])(" + "|".join(re.escape(f).replace(re.escape("<n>"), r"\d+[A-Z]?") for f in chk.document_names)
                              .replace(r"\ ", r"\s+") + r")(?![\w-])")
    designation = lambda text: " ".join(text.split())
    own_sources = {designation(m.group(1)) for info in sources.values() for m in (names_re.finditer(info.get("title") or "") if names_re else [])}

    # every claim's lines: (concept key) -> [(section order, page, place, citation, heading, label)]
    lines: dict[tuple, list] = {}
    for sl, p in holders.items():
        sec = section_of(sl)
        for place, st in enumerate(_statements(p["content_md"])):
            cites = [(m.group(1), lab) for m in checks.closing_links(st) if m.group(1).startswith("source-")
                     for lab in _labels(m.group(2) or "")]
            if not cites:
                continue
            found, rest = [], _plain(st)
            for t, rx in term_res:  # longest term first; a term found inside a longer one is not found again
                if rx.search(rest):
                    found.append(("term", t))
                    rest = rx.sub(" ", rest)
            if names_re:
                found += [("entity", d) for d in dict.fromkeys(designation(m.group(1)) for m in names_re.finditer(_plain(st)))
                          if d not in own_sources]
            for src, lab in cites:
                info = sources.get(src, {})
                printed = info.get("printed", {}).get(lab) or (info.get("own", {}).get(lab) or [""])[-1] or info.get("title", "")
                for key in found + ([("heading",) + heading_of[(src, lab)]] if (src, lab) in heading_of else []):
                    lines.setdefault(key, []).append(((order.get(sec["num"], 99) if sec else 99), sl, place,
                                                      f"[[{src}|{lab}]]", printed, sec))

    ops, made = [], set()
    for key, got in lines.items():
        if key[0] == "heading":
            if len({g[1] for g in got}) < chk.concept_heading_pages:
                continue
            title, slug = key[1], _slug(chk, framework, key[1], key[2])
            first = []
        elif key[0] == "entity":
            if len({g[1] for g in got}) < (chk.entity_pages or 1):
                continue
            title, first = key[1], []
            slug = store.slugify(re.sub(r"<[^>]+>$", key[1], chk.entity_slug.replace("<framework>", framework)))
        else:
            if not chk.concept_terms:
                continue
            title, slug = key[1], _slug(chk, framework, key[1])
            first = [_fill(chk.concept_defined, [terms_page, terms[key[1]]])] if chk.concept_defined and terms_page else []
        if slug in made:  # two concepts that would take the same slug are the same page
            continue
        made.add(slug)
        body, seen, by_sec = list(first), set(), {}
        for o, sl, place, cite, printed, sec in sorted(got, key=lambda g: (g[0], g[1], g[2])):
            if (cite, sl) in seen:
                continue
            seen.add((cite, sl))
            by_sec.setdefault((o, sec["name"] if sec else ""), []).append(
                "- " + _fill(chk.concept_line, [cite, printed, sl, pages[sl]["title"]]))
        for (o, name), ls in by_sec.items():
            body += [f"## {name}" if name else "## Other pages", "\n".join(ls)]
        names = [name for (_, name) in by_sec if name]
        summary = chk.concept_summary_lead
        for n in names:
            add = (chk.concept_summary_sep if summary != chk.concept_summary_lead else "") + n
            if chk.concept_summary_max and len(summary + add) > chk.concept_summary_max:
                break
            summary += add
        cur = existing.get(slug)
        kind = "entity" if key[0] == "entity" else "concept"
        ops.append(store.Op(op="update" if cur else "create", slug=slug, type=kind, title=title, summary=summary,
                            content_md="\n\n".join(body), base_version=cur["version"] if cur else None,
                            change_note=f"{kind.capitalize()} page rebuilt from the pages"))
    for sl, p in existing.items():  # a concept or entity page no list gives any more goes
        if p["type"] in ("concept", "entity") and sl not in made:
            ops.append(store.Op(op="delete", slug=sl, base_version=p.get("version"), change_note="Concept no longer listed"))
    return ops


def guidance_examples(chk, pages: dict[str, dict], sources: dict[str, dict]) -> tuple[str, str]:
    """The block the examples section's index adds for the issuer's examples printed inside guidance, which are filed
    with their requirement (the schema's examples brief): one line per paragraph, naming its examples and where it is
    written up, its clauses listed, not cited. Returns (its heading, the block); empty when there are none."""
    label_re = checks.example_label_re(chk)
    names = [v for k, v in chk.kinds.items() if v in chk.guidance_kinds]
    if not (label_re and names):
        return "", ""
    head = f"## Examples inside {names[0]}"
    holders = {sl: p for sl, p in pages.items() if p["type"] in ("topic", "subtopic")}
    cited_on: dict[tuple[str, str], list[str]] = {}
    for sl, p in holders.items():
        for m in store.LINK_RE.finditer(p["content_md"]):
            if m.group(1).startswith("source-"):
                for lab in _labels(m.group(2) or ""):
                    cited_on.setdefault((m.group(1), lab), [])
                    if sl not in cited_on[(m.group(1), lab)]:
                        cited_on[(m.group(1), lab)].append(sl)
    lines = []
    for s_slug, info in sources.items():
        for lab, text in info["para"].items():
            kind = chk.kinds.get(info["kinds"].get(lab) or info["route_kind"].get(lab) or "")
            if kind in chk.guidance_kinds and (found := list(dict.fromkeys(m.group(0) for m in label_re.finditer(text)))) \
                    and (where := cited_on.get((s_slug, lab))):
                pages_md = ", ".join(f"[[{x}|{pages[x]['title']}]]" for x in where)
                lines.append(f"- {', '.join(found)} ({info['printed'].get(lab) or ''}): in {pages_md}; {info['title']} {lab}")
    return head, "\n".join(dict.fromkeys(lines))
