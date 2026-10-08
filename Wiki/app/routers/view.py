"""Public read-only HTML viewer."""
import pathlib
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

from ..db import get_pool
from ..wiki import search, store

router = APIRouter(prefix="/view", tags=["viewer"], include_in_schema=False)
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).resolve().parent.parent / "templates"))
md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
MARK = ""  # private-use char: survives markdown rendering untouched
CALLOUT_RE = re.compile(r"<blockquote>\s*<p>\[!(\w+)\]\s*", re.I)


async def _wiki_or_404(w: str) -> dict:
    try:
        return await store.get_wiki(w)
    except store.NotFound:
        raise HTTPException(404, "Wiki not found")


def render_md(text: str, wiki_slug: str, existing: set[str]) -> Markup:
    def link(m):
        slug = store.slugify(m.group(1))
        label = (m.group(2) or m.group(1)).strip().replace("]", "")
        cls = "" if slug in existing else " broken"
        return f'<a class="wl{cls}" href="/view/{quote(wiki_slug)}/{quote(slug)}">{escape(label)}</a>'

    # Wiki links -> placeholders so markdown-it (html disabled) does not escape our anchors
    anchors: list[str] = []

    def stash(m):
        anchors.append(link(m))
        return f"{MARK}{len(anchors) - 1}{MARK}"

    html = md.render(store.LINK_RE.sub(stash, text))
    html = re.sub(f"{MARK}(\\d+){MARK}", lambda m: anchors[int(m.group(1))], html)
    html = CALLOUT_RE.sub(lambda m: f'<blockquote class="callout {m.group(1).lower()}"><p><strong>{m.group(1).capitalize()}:</strong> ', html)
    return Markup(html)


async def _slugs(wiki_id) -> set[str]:
    return {p["slug"] for p in await store.list_pages(wiki_id)}


@router.get("", response_class=HTMLResponse)
async def home(request: Request):
    async with get_pool().connection() as conn:
        wikis = await (await conn.execute("select slug, name, description from wiki.wikis order by name")).fetchall()
    return templates.TemplateResponse(request, "home.html", {"wikis": wikis})


@router.get("/{w}", response_class=HTMLResponse)
async def index(request: Request, w: str, q: str | None = None):
    wiki = await _wiki_or_404(w)
    pages = await store.list_pages(wiki["id"])
    results = await search.search_pages(wiki["id"], q, 20) if q else None
    groups = [(t, [p for p in pages if p["type"] == t]) for t in store.PAGE_TYPES]
    return templates.TemplateResponse(
        request, "index.html", {"wiki": wiki, "groups": [g for g in groups if g[1]], "q": q, "results": results, "count": len(pages)}
    )


@router.get("/{w}/log", response_class=HTMLResponse)
async def log(request: Request, w: str):
    wiki = await _wiki_or_404(w)
    body = render_md(await store.render_log(wiki), wiki["slug"], await _slugs(wiki["id"]))
    return templates.TemplateResponse(request, "doc.html", {"wiki": wiki, "title": "Log", "body": body})


@router.get("/{w}/schema", response_class=HTMLResponse)
async def schema(request: Request, w: str):
    wiki = await _wiki_or_404(w)
    body = render_md(wiki["schema_md"], wiki["slug"], await _slugs(wiki["id"]))
    return templates.TemplateResponse(request, "doc.html", {"wiki": wiki, "title": "Schema", "body": body})


@router.get("/{w}/{slug}", response_class=HTMLResponse)
async def page(request: Request, w: str, slug: str):
    wiki = await _wiki_or_404(w)
    p = await store.get_page(wiki["id"], slug)
    if not p:
        refs = await store.backlinks(wiki["id"], slug)
        return templates.TemplateResponse(
            request, "missing.html", {"wiki": wiki, "slug": slug, "backlinks": refs}, status_code=404
        )
    body = render_md(p["content_md"], wiki["slug"], await _slugs(wiki["id"]))
    return templates.TemplateResponse(
        request, "page.html",
        {"wiki": wiki, "page": p, "body": body, "backlinks": await store.backlinks(wiki["id"], slug),
         "sources": await store.page_sources(p["id"])},
    )
