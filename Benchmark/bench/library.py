"""The original source texts as numbered paragraphs, read only from the copies the wikis keep (wiki.sources), never
from wiki pages. Each paragraph knows its document and tier:
- standard: a Standard's own text (Part A, as read by the IFRS reader, appendices included);
- supporting: documents published with it (Parts B and C: implementation guidance, illustrative examples, basis for
  conclusions).
search() finds the paragraphs that best match a piece of text (BM25 over words), for showing the judge the source.
"""
import math
import re
from collections import Counter

import psycopg

LABEL_LINE = re.compile(r"^\[([^\]\n]+)\][ \t]*", re.M)
WORD = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
STOP = set("""a an and are as at be been by can for from has have if in into is it its may must not of on or shall should
such than that the their them then there these this those to under was were when where which while who will with would
also any each other only same so some its entity entities""".split())


# abbreviations answers and rubrics use, spelled out as the Standard writes them
ABBREV = {"ecl": "expected credit losses", "ecls": "expected credit losses", "sicr": "significant increase in credit risk",
          "eir": "effective interest rate", "pd": "probability of default", "lgd": "loss given default", "ead": "exposure at default",
          "fvoci": "fair value through other comprehensive income", "fvtpl": "fair value through profit or loss",
          "oci": "other comprehensive income", "poci": "purchased or originated credit-impaired", "sppi": "solely payments of principal and interest",
          "12-month": "12-month", "dpd": "days past due"}


def _words(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text.lower()):
        out += WORD.findall(ABBREV[w]) if w in ABBREV else [w]
    return [_stem(w) for w in out if w not in STOP and len(w) > 1]


def _stem(w: str) -> str:
    """Light stemming so "increased significantly" meets "significant increase"."""
    if any(c.isdigit() for c in w):
        return w
    for suf in ("ingly", "edly", "ings", "ing", "ed", "ly", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _tier(meta: dict | None) -> str:
    return "supporting" if (meta or {}).get("parser") == "ifrs_accompanying" else "standard" if (meta or {}).get("parser") == "ifrs" else "other"


def _doc_name(title: str, meta: dict | None) -> str:
    """e.g. "IFRS 9 Part A" from "13 - IFRS 9 Financial Instruments" and the PDF's "Annotated-BB2025-A ..." title."""
    std = re.search(r"\b(IFRS|IAS|IFRIC|SIC)\s*(\d+)", title or "")
    part = re.search(r"BB\d{4}-([ABC])\b", (meta or {}).get("title") or "")
    name = f"{std.group(1)} {std.group(2)}" if std else (title or "source")
    return f"{name} Part {part.group(1)}" if part else name


class Library:
    def __init__(self, conn: psycopg.Connection):
        self.by_source: dict[str, dict[str, str]] = {}
        self.titles: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.tiers: dict[str, str] = {}
        rows = conn.execute("""select distinct on (s.slug) s.slug, s.title, s.text, s.meta from wiki.sources s
                               order by s.slug, length(s.text) desc""").fetchall()
        for r in rows:
            r = r if isinstance(r, dict) else dict(zip(("slug", "title", "text", "meta"), r))
            paras: dict[str, str] = {}
            ms = list(LABEL_LINE.finditer(r["text"] or ""))
            for i, m in enumerate(ms):
                end = ms[i + 1].start() if i + 1 < len(ms) else len(r["text"])
                key = " ".join(m.group(1).split())
                paras[key] = (paras.get(key, "") + "\n" + r["text"][m.end():end].strip()).strip()
            self.by_source[r["slug"]] = paras
            self.titles[r["slug"]] = r["title"]
            self.names[r["slug"]] = _doc_name(r["title"], r["meta"])
            self.tiers[r["slug"]] = _tier(r["meta"])
        self._index = None

    def find(self, part: str, source: str | None = None) -> list[tuple[str, str]]:
        """(source slug, paragraph text) for each source holding this paragraph; only the named source when given."""
        hits = []
        for slug, paras in self.by_source.items():
            if source and slug != source:
                continue
            for k in (part, re.sub(r"(\([a-z0-9]{1,4}\))+$", "", part)):
                if k in paras:
                    hits.append((slug, paras[k]))
                    break
        return hits

    def _build(self):
        docs = []
        for slug, paras in self.by_source.items():
            if self.tiers[slug] == "other":
                continue
            for label, text in paras.items():
                if label.startswith("p") and label[1:].isdigit():  # page markers, not paragraphs
                    continue
                docs.append((slug, label, text, Counter(_words(label + " " + text))))
        n = len(docs)
        df = Counter(w for *_, tf in docs for w in tf)
        self._index = {"docs": docs, "idf": {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()},
                       "avg": sum(sum(tf.values()) for *_, tf in docs) / max(n, 1)}

    def search(self, text: str, k: int = 8, per_tier: int = 2) -> list[dict]:
        """The best-matching paragraphs: the top k overall, plus the best per_tier of each tier not among them, so the
        judge always sees both the Standard's and the supporting documents' closest paragraphs."""
        if self._index is None:
            self._build()
        q = set(_words(text))
        idf, avg, k1, b = self._index["idf"], self._index["avg"], 1.5, 0.75
        scored = []
        for slug, label, body, tf in self._index["docs"]:
            dl = sum(tf.values())
            s = sum(idf[w] * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * dl / avg)) for w in q if w in tf)
            if s > 0:
                scored.append((s, slug, label, body))
        scored.sort(key=lambda x: -x[0])
        picked = scored[:k]
        for tier in ("standard", "supporting"):
            have = sum(self.tiers[x[1]] == tier for x in picked)
            if have < per_tier:
                picked += [x for x in scored[k:] if self.tiers[x[1]] == tier][: per_tier - have]
        return [{"paragraph": label, "source": slug, "document": self.names[slug], "tier": self.tiers[slug],
                 "text": body[:1500], "score": round(s, 2)} for s, slug, label, body in picked]
