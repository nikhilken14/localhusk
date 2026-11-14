from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import PageParams, Pagination, get_db
from assistant.core.config import get_settings
from assistant.core.errors import APIError
from assistant.core.textutil import LIKE_ESCAPE, like_pattern, preview
from assistant.db.models import ChatMessage, Conversation, ProviderConfig
from assistant.db.session import SessionLocal
from assistant.providers.base import ChatMessageInput, Usage
from assistant.providers.registry import registry
from assistant.schemas.chat import (
    ConversationCreate, ConversationRead, ConversationUpdate, MessageCreate, MessageRead, SendResult,
)
from assistant.schemas.common import Page
from assistant.services import attachments as att_service
from assistant.services import chat as chat_service
from assistant.services import llm
from assistant.services.usage import record_usage

router = APIRouter(prefix="/conversations", tags=["conversations"])
log = logging.getLogger("assistant.chat")


def _last_content():
    return (select(ChatMessage.content).where(ChatMessage.conversation_id == Conversation.id)
            .order_by(ChatMessage.created_at.desc()).limit(1).correlate(Conversation).scalar_subquery())


def _count():
    return (select(func.count(ChatMessage.id)).where(ChatMessage.conversation_id == Conversation.id)
            .correlate(Conversation).scalar_subquery())


def conversation_read(conversation: Conversation, count: int, last: str | None) -> ConversationRead:
    return ConversationRead(
        id=conversation.id, title=conversation.title, pinned=conversation.pinned, archived=conversation.archived,
        provider_id=conversation.provider_id, message_count=count, preview=preview(last or ""),
        created_at=conversation.created_at, updated_at=conversation.updated_at)


def _read_one(db: Session, conversation: Conversation) -> ConversationRead:
    count = db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.conversation_id == conversation.id)) or 0
    last = db.scalar(select(ChatMessage.content).where(ChatMessage.conversation_id == conversation.id)
                     .order_by(ChatMessage.created_at.desc()).limit(1))
    return conversation_read(conversation, count, last)


@router.get("", response_model=Page[ConversationRead], summary="List conversations (search + pagination)")
def list_conversations(
    q: str | None = Query(None, description="Matches title or message content"),
    archived: bool | None = Query(None, description="Omit for all; true/false to filter"),
    pinned: bool | None = None,
    page: Pagination = PageParams, db: Session = Depends(get_db),
):
    conditions = []
    if archived is not None:
        conditions.append(Conversation.archived.is_(archived))
    if pinned is not None:
        conditions.append(Conversation.pinned.is_(pinned))
    if q and q.strip():
        pattern = like_pattern(q)
        conditions.append(or_(
            Conversation.title.ilike(pattern, escape=LIKE_ESCAPE),
            exists().where(and_(ChatMessage.conversation_id == Conversation.id,
                                ChatMessage.content.ilike(pattern, escape=LIKE_ESCAPE)))))
    total = db.scalar(select(func.count(Conversation.id)).where(*conditions)) or 0
    rows = db.execute(
        select(Conversation, _count().label("mc"), _last_content().label("lc")).where(*conditions)
        .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(page.limit).offset(page.offset)).all()
    return Page(items=[conversation_read(c, mc or 0, lc) for c, mc, lc in rows], total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=ConversationRead, status_code=201)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    if payload.provider_id and db.get(ProviderConfig, payload.provider_id) is None:
        raise APIError(404, "Model connection not found")
    return _read_one(db, chat_service.create_conversation(db, payload.title, payload.provider_id))


@router.get("/{conversation_id}", response_model=ConversationRead)
def read_conversation(conversation_id: str, db: Session = Depends(get_db)):
    return _read_one(db, chat_service.get_conversation(db, conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationRead)
def update_conversation(conversation_id: str, payload: ConversationUpdate, db: Session = Depends(get_db)):
    conversation = chat_service.get_conversation(db, conversation_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("provider_id") and db.get(ProviderConfig, data["provider_id"]) is None:
        raise APIError(404, "Model connection not found")
    for key, value in data.items():
        setattr(conversation, key, value)
    db.commit()
    return _read_one(db, conversation)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)):
    db.delete(chat_service.get_conversation(db, conversation_id))  # messages cascade
    db.commit()


@router.get("/{conversation_id}/messages", response_model=Page[MessageRead], summary="Persisted messages (paginated)")
def list_messages(conversation_id: str, order: Literal["asc", "desc"] = "asc", page: Pagination = PageParams,
                  db: Session = Depends(get_db)):
    chat_service.get_conversation(db, conversation_id)
    total = db.scalar(select(func.count(ChatMessage.id)).where(ChatMessage.conversation_id == conversation_id)) or 0
    direction = ChatMessage.created_at.asc() if order == "asc" else ChatMessage.created_at.desc()
    rows = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                      .order_by(direction, ChatMessage.id).limit(page.limit).offset(page.offset)).all()
    return Page(items=[MessageRead.model_validate(m) for m in rows], total=total, limit=page.limit, offset=page.offset)



def _compose_user_content(db: Session, conversation_id: str, payload: MessageCreate) -> tuple[str, str]:
    """Return (stored_content, llm_content). stored is what we persist; llm includes extracted docs."""
    attachments = att_service.resolve_for_message(db, conversation_id, payload.attachment_ids or None)
    user_text = (payload.content or "").strip()
    if not user_text and not attachments:
        raise APIError(400, "Message content or at least one attachment is required")
    names = ", ".join(a.filename for a in attachments)
    if attachments and user_text:
        stored = f"{user_text}\n\n[Attached: {names}]"
    elif attachments:
        stored = f"[Attached: {names}]"
    else:
        stored = user_text
    llm_content = att_service.build_user_content_with_attachments(user_text, attachments)
    return stored, llm_content


def _enrich_history_with_docs(db: Session, conversation_id: str, history: list[ChatMessageInput]) -> list[ChatMessageInput]:
    """Keep document context available across the whole chat, not only the message that attached them.

    Stored history only keeps "[Attached: names]". We re-inject extracted text from every
    conversation attachment (capped) so later turns still "remember" the docs.
    """
    if not history:
        return history
    all_atts = att_service.list_for_conversation(db, conversation_id)
    if not all_atts:
        return history
    # Prefer newest first; build_user_content already truncates per file.
    # Cap total injected size so we do not blow the context window.
    max_total = 120_000
    used = 0
    chosen = []
    for att in all_atts:
        text = (att.extracted_text or "").strip()
        if not text:
            continue
        if used + len(text) > max_total and chosen:
            break
        chosen.append(att)
        used += len(text)
    if not chosen:
        return history
    # Put a single synthetic user turn at the front with the docs so every follow-up sees them.
    # Avoid duplicating if the first history item already embeds the same block.
    doc_block = att_service.build_user_content_with_attachments(
        "The following documents were uploaded earlier in this conversation. Use them as context for later messages.",
        list(reversed(chosen)),  # chronological for the model
    )
    if history and history[0].role == "user" and "--- Attached documents (extracted text) ---" in (history[0].content or ""):
        return history
    return [ChatMessageInput("user", doc_block), ChatMessageInput("assistant", "Understood. I will use the attached documents as context.")] + history


@router.post("/{conversation_id}/messages", response_model=SendResult, summary="Send a message and run the selected LLM")
async def send_message(conversation_id: str, payload: MessageCreate, db: Session = Depends(get_db)):
    conversation = chat_service.get_conversation(db, conversation_id)
    provider = llm.snapshot(llm.resolve_provider(db, payload.provider_id, conversation.provider_id))
    stored, llm_content = _compose_user_content(db, conversation.id, payload)
    user_message = chat_service.save_message(db, conversation, "user", stored)
    # Rebuild history then replace the last user turn with the attachment-expanded content for the LLM only.
    history = chat_service.build_history(db, conversation.id, get_settings().max_history_messages)
    if history and history[-1].role == "user":
        history[-1] = ChatMessageInput("user", llm_content)
    # Re-inject prior docs so the model still has them on later turns in the same chat.
    history = _enrich_history_with_docs(db, conversation.id, history)
    options = provider.options(payload.temperature, payload.max_output_tokens)
    completion = await llm.complete(provider, history, options)  # raises APIError(502) with a safe message
    usage_row = record_usage(db, provider, source="chat", usage=completion.usage, messages=history,
                             output_text=completion.text, reference_id=conversation.id)
    assistant_message = chat_service.save_message(
        db, conversation, "assistant", completion.text, provider_id=provider.id, model=provider.model,
        input_tokens=usage_row.input_tokens, output_tokens=usage_row.output_tokens)
    return SendResult(
        user_message=MessageRead.model_validate(user_message), assistant_message=MessageRead.model_validate(assistant_message),
        usage={"input_tokens": usage_row.input_tokens, "output_tokens": usage_row.output_tokens, "estimated": usage_row.estimated})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.post("/{conversation_id}/stream", summary="Stream assistant output as server-sent events")
async def stream_message(conversation_id: str, payload: MessageCreate, db: Session = Depends(get_db)):
    """Events (``data:`` JSON, discriminated by ``type``): ``start`` -> ``delta``* -> ``usage`` -> ``done``,
    or ``error``.  ``delta`` events also carry a ``delta`` field and ``done`` a ``done: true`` flag."""
    conversation = chat_service.get_conversation(db, conversation_id)
    provider = llm.snapshot(llm.resolve_provider(db, payload.provider_id, conversation.provider_id))
    stored, llm_content = _compose_user_content(db, conversation.id, payload)
    user_message = chat_service.save_message(db, conversation, "user", stored)
    history = chat_service.build_history(db, conversation.id, get_settings().max_history_messages)
    if history and history[-1].role == "user":
        history[-1] = ChatMessageInput("user", llm_content)
    # Re-inject prior docs so the model still has them on later turns in the same chat.
    history = _enrich_history_with_docs(db, conversation.id, history)
    options = provider.options(payload.temperature, payload.max_output_tokens)
    start_event = {"type": "start", "user_message": MessageRead.model_validate(user_message).model_dump(mode="json")}
    cid = conversation.id

    async def events():
        chunks: list[str] = []
        usage: Usage | None = None
        saved = False

        def persist(status: str):  # own session: the request-scoped one may already be closed
            with SessionLocal() as session:
                conv = session.get(Conversation, cid)
                if conv is None:  # deleted while streaming
                    return None
                row = record_usage(session, provider, source="chat", usage=usage, messages=history,
                                   output_text="".join(chunks), reference_id=cid)
                message = chat_service.save_message(
                    session, conv, "assistant", "".join(chunks), provider_id=provider.id, model=provider.model, status=status,
                    input_tokens=row.input_tokens, output_tokens=row.output_tokens)
                session.commit()
                return message, row

        try:
            yield _sse(start_event)
            try:
                async for chunk in registry.get(provider.kind).stream(history, options, provider.api_key, provider.base_url):
                    if chunk.usage:
                        usage = chunk.usage
                    if chunk.delta:
                        chunks.append(chunk.delta)
                        yield _sse({"type": "delta", "delta": chunk.delta})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                message = llm.safe_error(exc, provider.api_key)
                log.warning("Stream failed for %s/%s: %s", provider.name, provider.model, message, extra={"category": "llm"})
                if chunks:
                    persist("partial")
                    saved = True
                yield _sse({"type": "error", "error": f"LLM stream failed: {message}"})
                return
            result = persist("complete")
            saved = True
            if result:
                message, row = result
                yield _sse({"type": "usage", "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                            "estimated": row.estimated})
                yield _sse({"type": "done", "done": True, "message": MessageRead.model_validate(message).model_dump(mode="json")})
            else:
                yield _sse({"type": "error", "error": "Conversation was deleted while the response was streaming"})
                yield _sse({"type": "done", "done": True})
        finally:
            if not saved and chunks:  # client disconnected mid-stream: keep what was generated
                persist("partial")

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{conversation_id}/attachments", status_code=201, summary="Upload a document for chat context")
async def upload_attachment(
    conversation_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Accept pdf, docx, xlsx, zip, txt, md, csv, json. Extracts text for the LLM."""
    conversation = chat_service.get_conversation(db, conversation_id)
    data = await file.read()
    row = att_service.save_upload(
        db,
        conversation=conversation,
        filename=file.filename or "file",
        data=data,
        content_type=file.content_type,
    )
    db.commit()
    db.refresh(row)
    return att_service.attachment_public(row)


@router.get("/{conversation_id}/attachments", summary="List uploaded attachments for a conversation")
def list_attachments(conversation_id: str, db: Session = Depends(get_db)):
    chat_service.get_conversation(db, conversation_id)
    return [att_service.attachment_public(r) for r in att_service.list_for_conversation(db, conversation_id)]


@router.delete("/{conversation_id}/attachments/{attachment_id}", status_code=204, summary="Delete an attachment")
def remove_attachment(conversation_id: str, attachment_id: str, db: Session = Depends(get_db)):
    chat_service.get_conversation(db, conversation_id)
    row = att_service.get_attachment(db, attachment_id)
    if row.conversation_id != conversation_id:
        raise APIError(404, "Attachment not found")
    att_service.delete_attachment(db, row)
    db.commit()
    return None
