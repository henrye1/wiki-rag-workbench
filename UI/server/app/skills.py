"""Skills: named instructions a chat on the Ask screen can use. A chat's chosen skills (ask.chats.skill_ids) are added
to the answer instruction of both RAG and the wiki; they never change what is searched. Optional: a chat starts with none.
A skill may also carry questions: Run on Ask asks each as its own message in a new chat, then writes a summary (ask.py)."""
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .ask import _q

router = APIRouter(prefix="/api/skills", tags=["skills"])


MAX_QUESTIONS, MAX_QUESTION = 50, 2000


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=300)
    instructions: str = Field(min_length=1, max_length=20000)
    questions: list[str] = Field(default_factory=list, description="Asked one by one, in order, when the skill is run on Ask")
    summary: str = Field("", max_length=4000, description="How to write the run's verdict from the answers; empty = the default")


def _clean(body: SkillIn) -> tuple[str, str, str, list[str], str]:
    name, instructions = body.name.strip(), body.instructions.strip()
    if not name or not instructions:
        raise HTTPException(422, "A skill needs a name and instructions")
    questions = [q.strip() for q in body.questions if q.strip()]
    if len(questions) > MAX_QUESTIONS:
        raise HTTPException(422, f"A skill can have at most {MAX_QUESTIONS} questions")
    if any(len(q) > MAX_QUESTION for q in questions):
        raise HTTPException(422, f"A question can be at most {MAX_QUESTION} characters")
    return name, body.description.strip(), instructions, questions, body.summary.strip()


async def _write(sql: str, params: tuple):
    try:
        return await _q(sql, params, one=True)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, f'A skill named "{params[0]}" already exists')


@router.get("")
async def list_skills():
    return await _q("select * from ask.skills order by lower(name)")


@router.post("", status_code=201)
async def create_skill(body: SkillIn):
    return await _write("""insert into ask.skills (name, description, instructions, questions, summary)
                           values (%s, %s, %s, %s, %s) returning *""", _clean(body))


@router.get("/{skill_id}")
async def get_skill(skill_id: UUID):
    row = await _q("select * from ask.skills where id = %s", (skill_id,), one=True)
    if not row:
        raise HTTPException(404, "Skill not found")
    return row


@router.put("/{skill_id}")
async def update_skill(skill_id: UUID, body: SkillIn):
    row = await _write("""update ask.skills set name = %s, description = %s, instructions = %s, questions = %s, summary = %s,
                          updated_at = now() where id = %s returning *""", (*_clean(body), skill_id))
    if not row:
        raise HTTPException(404, "Skill not found")
    return row


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: UUID):
    """Deletes the skill and takes it off every chat that uses it."""
    await get_skill(skill_id)
    await _q("update ask.chats set skill_ids = array_remove(skill_ids, %s) where %s = any(skill_ids)", (skill_id, skill_id))
    await _q("delete from ask.skills where id = %s", (skill_id,))
