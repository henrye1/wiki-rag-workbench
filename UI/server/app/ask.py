"""Chats on the Ask screen: saved automatically, with each message's question, the full question searched, the side(s)
asked, the Sources setting and the answers. A follow-up is rewritten into a full question from the chat's earlier
questions only (never its answers); RAG and the wiki only ever receive that full question, one at a time."""
import asyncio
import json
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .config import get_settings
from .proxy import client

router = APIRouter(prefix="/api/ask", tags=["ask"])

REWRITE_SYSTEM = """You rewrite a follow-up question from a chat into one complete question that can be searched on its own.
Use the earlier questions only to work out what the follow-up refers to (pronouns, "and for...", "what about...").
Keep the follow-up's meaning, scope and wording as far as possible; do not answer it, and do not add facts, conditions or
assumptions that are not in the questions. If the follow-up is already complete on its own, return it unchanged."""
REWRITE_SCHEMA = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}


def _q(sql: str, params: tuple = (), one: bool = False):
    def run():
        with psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row) as conn:
            cur = conn.execute(sql, params)
            if cur.description is None:
                return None
            return cur.fetchone() if one else cur.fetchall()
    return asyncio.to_thread(run)


async def _chat(chat_id: UUID) -> dict:
    row = await _q("select * from ask.chats where id = %s", (chat_id,), one=True)
    if not row:
        raise HTTPException(404, "Chat not found")
    return row


class ChatIn(BaseModel):
    title: str = ""


@router.get("/chats")
async def list_chats():
    return await _q(
        """select c.id, c.title, c.created_at, c.updated_at, count(m.id) as messages
           from ask.chats c left join ask.messages m on m.chat_id = c.id
           group by c.id order by c.updated_at desc"""
    )


@router.post("/chats", status_code=201)
async def create_chat(body: ChatIn):
    return await _q("insert into ask.chats (title) values (%s) returning *", (body.title.strip()[:120],), one=True)


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: UUID):
    chat = await _chat(chat_id)
    msgs = await _q("select * from ask.messages where chat_id = %s order by seq", (chat_id,))
    return {**chat, "messages": msgs}


@router.patch("/chats/{chat_id}")
async def rename_chat(chat_id: UUID, body: ChatIn):
    await _chat(chat_id)
    return await _q("update ask.chats set title = %s where id = %s returning *", (body.title.strip()[:120], chat_id), one=True)


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(chat_id: UUID):
    """Deletes the chat and its messages only: synthesis pages made from it stay in the wiki."""
    await _chat(chat_id)
    await _q("delete from ask.chats where id = %s", (chat_id,))


class RewriteIn(BaseModel):
    question: str = Field(min_length=1)
    before_seq: int | None = Field(None, description="Rewrite as of this message (re-asking an earlier one); default: after the last")


async def _gemini_json(system: str, prompt: str, schema: dict) -> dict:
    s = get_settings()
    if not s.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set for the Workbench server")
    r = await client().post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{s.gemini_model}:generateContent",
        headers={"x-goog-api-key": s.gemini_api_key},
        json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema, "temperature": 0}},
        timeout=60,
    )
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


@router.post("/chats/{chat_id}/rewrite")
async def rewrite(chat_id: UUID, body: RewriteIn):
    """The follow-up as a full question, using at most the last N earlier questions of this chat (questions only)."""
    await _chat(chat_id)
    n = get_settings().ask_history_questions
    where, params = ("and seq < %s", (chat_id, body.before_seq, n)) if body.before_seq is not None else ("", (chat_id, n))
    rows = await _q(f"select searched from ask.messages where chat_id = %s {where} order by seq desc limit %s", params)
    earlier = [r["searched"] for r in reversed(rows)]
    q = body.question.strip()
    if not earlier:
        return {"searched": q, "rewritten": False, "earlier": []}
    prompt = "Earlier questions in this chat, oldest first:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(earlier, 1)) + f"\n\nFollow-up: {q}"
    try:
        out = (await _gemini_json(REWRITE_SYSTEM, prompt, REWRITE_SCHEMA))["question"].strip() or q
    except Exception as e:  # the question is still asked, as typed
        return {"searched": q, "rewritten": False, "earlier": earlier, "error": f"Could not rewrite the follow-up: {e}"}
    return {"searched": out, "rewritten": out != q, "earlier": earlier}


class Side(BaseModel):
    answer: str = ""
    sources: list = []
    pages: list = []
    ms: int | None = None
    error: str = ""


class MessageIn(BaseModel):
    question: str = Field(min_length=1)
    searched: str = Field(min_length=1)
    mode: Literal["rag", "wiki", "both"]
    sources: Literal["standard", "all"]
    rag_collection: str | None = None
    wiki_slug: str | None = None
    rag: Side | None = None
    wiki: Side | None = None
    seq: int | None = Field(None, description="Replace this message (asked again after editing 'Searched for')")


@router.post("/chats/{chat_id}/messages", status_code=201)
async def save_message(chat_id: UUID, body: MessageIn):
    chat = await _chat(chat_id)
    rag = Jsonb(body.rag.model_dump()) if body.rag and body.mode in ("rag", "both") else None
    wiki = Jsonb(body.wiki.model_dump()) if body.wiki and body.mode in ("wiki", "both") else None
    vals = (body.question, body.searched, body.mode, body.sources, body.rag_collection if rag else None, body.wiki_slug if wiki else None, rag, wiki)
    if body.seq is not None:
        row = await _q(
            """update ask.messages set question=%s, searched=%s, mode=%s, sources=%s, rag_collection=%s, wiki_slug=%s, rag=%s, wiki=%s,
               created_at=now() where chat_id=%s and seq=%s returning *""", (*vals, chat_id, body.seq), one=True)
        if not row:
            raise HTTPException(404, "Message not found")
    else:
        row = await _q(
            """insert into ask.messages (chat_id, seq, question, searched, mode, sources, rag_collection, wiki_slug, rag, wiki)
               values (%s, (select coalesce(max(seq), 0) + 1 from ask.messages where chat_id = %s), %s, %s, %s, %s, %s, %s, %s, %s)
               returning *""", (chat_id, chat_id, *vals), one=True)
    title = chat["title"] or " ".join(body.question.split())[:80]  # a new chat is named after its first question
    await _q("update ask.chats set title = %s, updated_at = now() where id = %s", (title, chat_id))
    return row
