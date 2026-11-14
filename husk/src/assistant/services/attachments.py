"""Chat file attachments: store on disk, extract text for LLM context.

Supported: .txt .md .csv .json .pdf .docx .xlsx .zip
Extraction libraries are optional — missing ones return a clear error for that type.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.core.config import HUSK_HOME
from assistant.core.errors import APIError
from assistant.core.timeutil import utcnow
from assistant.db.models.chat import ChatAttachment, Conversation
from assistant.db.models.automation import Agent

log = logging.getLogger("assistant.attachments")

# Hard limits (bytes / chars) to keep local and prompt-safe.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB per file
MAX_EXTRACTED_CHARS = 80_000  # per file, truncated for the LLM
MAX_ATTACHMENTS_PER_MESSAGE = 8
MAX_ZIP_MEMBERS = 40
MAX_ZIP_MEMBER_BYTES = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".log",
    ".pdf", ".docx", ".xlsx", ".xlsm", ".zip",
}
MIME_BY_EXT = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".log": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".zip": "application/zip",
}


def attachments_root() -> Path:
    root = HUSK_HOME / "data" / "attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name).strip(" ._")
    return (name or "file")[:180]


def _truncate(text: str, limit: int = MAX_EXTRACTED_CHARS) -> str:
    text = (text or "").replace("\x00", "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…[truncated, {len(text) - limit} more characters]"


def _extract_text_plain(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise APIError(400, "PDF support requires the pypdf package (pip install pypdf)", "missing_extractor") from exc
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            parts.append(f"[page {i + 1}: could not extract text]")
    return "\n\n".join(parts)


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise APIError(400, "DOCX support requires python-docx (pip install python-docx)", "missing_extractor") from exc
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _extract_xlsx(data: bytes) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise APIError(400, "XLSX support requires openpyxl (pip install openpyxl)", "missing_extractor") from exc
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    chunks: list[str] = []
    for sheet in wb.worksheets:
        chunks.append(f"## Sheet: {sheet.title}")
        rows_out: list[str] = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= 500:
                rows_out.append("…[sheet truncated at 500 rows]")
                break
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                rows_out.append("\t".join(cells))
        chunks.append("\n".join(rows_out))
    return "\n\n".join(chunks)


def _extract_csv(data: bytes) -> str:
    text = _extract_text_plain(data)
    # Normalise via csv so delimiters stay readable
    try:
        reader = csv.reader(io.StringIO(text))
        lines = []
        for i, row in enumerate(reader):
            if i >= 1000:
                lines.append("…[csv truncated at 1000 rows]")
                break
            lines.append("\t".join(row))
        return "\n".join(lines)
    except csv.Error:
        return text


def _extract_json(data: bytes) -> str:
    text = _extract_text_plain(data)
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return text


def _extract_zip(data: bytes) -> str:
    parts: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            members = [i for i in zf.infolist() if not i.is_dir()][:MAX_ZIP_MEMBERS]
            for info in members:
                if info.file_size > MAX_ZIP_MEMBER_BYTES:
                    parts.append(f"### {info.filename}\n[skipped: member too large ({info.file_size} bytes)]")
                    continue
                name = info.filename
                ext = Path(name).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS - {".zip"}:  # no nested zips
                    parts.append(f"### {name}\n[skipped: unsupported type {ext or '(none)'}]")
                    continue
                try:
                    raw = zf.read(info)
                except Exception as exc:  # noqa: BLE001
                    parts.append(f"### {name}\n[read error: {exc}]")
                    continue
                try:
                    body = extract_bytes(raw, name)
                except APIError as exc:
                    body = f"[extract error: {exc.message}]"
                parts.append(f"### {name}\n{body}")
    except zipfile.BadZipFile as exc:
        raise APIError(400, "Invalid or corrupted ZIP file", "bad_zip") from exc
    return "\n\n".join(parts) if parts else "[empty archive]"


def extract_bytes(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".txt", ".md", ".markdown", ".log"}:
        text = _extract_text_plain(data)
    elif ext == ".csv":
        text = _extract_csv(data)
    elif ext == ".json":
        text = _extract_json(data)
    elif ext == ".pdf":
        text = _extract_pdf(data)
    elif ext == ".docx":
        text = _extract_docx(data)
    elif ext in {".xlsx", ".xlsm"}:
        text = _extract_xlsx(data)
    elif ext == ".zip":
        text = _extract_zip(data)
    else:
        raise APIError(400, f"Unsupported file type: {ext or '(none)'}", "unsupported_type")
    return _truncate(text)


def save_upload(
    db: Session,
    *,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    conversation: Conversation | None = None,
    agent: Agent | None = None,
) -> ChatAttachment:
    """Store a file for a conversation and/or agent. At least one owner is required."""
    if conversation is None and agent is None:
        raise APIError(400, "Attachment must belong to a conversation or an agent")
    if len(data) > MAX_UPLOAD_BYTES:
        raise APIError(400, f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit", "file_too_large")
    if not data:
        raise APIError(400, "Empty file", "empty_file")

    safe = _safe_filename(filename)
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise APIError(
            400,
            f"Unsupported type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            "unsupported_type",
        )

    extracted = extract_bytes(data, safe)
    att_id = str(uuid4())
    owner_key = conversation.id if conversation is not None else f"agent-{agent.id}"
    rel_dir = Path(owner_key)
    disk_dir = attachments_root() / rel_dir
    disk_dir.mkdir(parents=True, exist_ok=True)
    disk_name = f"{att_id}{ext}"
    disk_path = disk_dir / disk_name
    disk_path.write_bytes(data)

    mime = content_type or MIME_BY_EXT.get(ext, "application/octet-stream")
    row = ChatAttachment(
        id=att_id,
        conversation_id=conversation.id if conversation is not None else None,
        agent_id=agent.id if agent is not None else None,
        filename=safe,
        content_type=mime[:120],
        size_bytes=len(data),
        storage_path=str(rel_dir / disk_name),
        extracted_text=extracted,
        extracted_chars=len(extracted),
    )
    db.add(row)
    db.flush()
    return row


def get_attachment(db: Session, attachment_id: str) -> ChatAttachment:
    row = db.get(ChatAttachment, attachment_id)
    if row is None:
        raise APIError(404, "Attachment not found")
    return row


def list_for_conversation(db: Session, conversation_id: str) -> list[ChatAttachment]:
    return list(db.scalars(
        select(ChatAttachment)
        .where(ChatAttachment.conversation_id == conversation_id)
        .order_by(ChatAttachment.created_at.desc())
    ))


def resolve_for_message(
    db: Session,
    conversation_id: str,
    attachment_ids: list[str] | None,
) -> list[ChatAttachment]:
    if not attachment_ids:
        return []
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise APIError(400, f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per message", "too_many_attachments")
    rows: list[ChatAttachment] = []
    for aid in attachment_ids:
        row = db.get(ChatAttachment, aid)
        if row is None or row.conversation_id != conversation_id:
            raise APIError(404, f"Attachment not found: {aid}")
        rows.append(row)
    return rows


def resolve_for_agent(
    db: Session,
    agent_id: str,
    attachment_ids: list[str] | None,
) -> list[ChatAttachment]:
    """Resolve attachments owned by this agent (or not yet bound to another agent)."""
    if not attachment_ids:
        return []
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise APIError(400, f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments per run", "too_many_attachments")
    rows: list[ChatAttachment] = []
    for aid in attachment_ids:
        row = db.get(ChatAttachment, aid)
        if row is None:
            raise APIError(404, f"Attachment not found: {aid}")
        if row.agent_id is not None and row.agent_id != agent_id:
            raise APIError(404, f"Attachment not found: {aid}")
        # Bind to agent if it was uploaded generically for this flow
        if row.agent_id is None:
            row.agent_id = agent_id
        rows.append(row)
    return rows


def list_for_agent(db: Session, agent_id: str) -> list[ChatAttachment]:
    return list(db.scalars(
        select(ChatAttachment)
        .where(ChatAttachment.agent_id == agent_id)
        .order_by(ChatAttachment.created_at.desc())
    ))


def bind_to_run(db: Session, attachments: list[ChatAttachment], run_id: str) -> None:
    for row in attachments:
        row.run_id = run_id


def build_user_content_with_attachments(user_text: str, attachments: list[ChatAttachment]) -> str:
    """Compose the prompt content: user text + extracted document blocks."""
    if not attachments:
        return user_text
    blocks = [user_text.strip()] if user_text.strip() else []
    blocks.append("--- Attached documents (extracted text) ---")
    for att in attachments:
        header = f"[File: {att.filename} | {att.content_type} | {att.size_bytes} bytes]"
        body = (att.extracted_text or "").strip() or "[no extractable text]"
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


def attachment_public(row: ChatAttachment) -> dict:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "agent_id": row.agent_id,
        "run_id": row.run_id,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "extracted_chars": row.extracted_chars,
        "preview": (row.extracted_text or "")[:400],
        "created_at": row.created_at,
    }


def delete_attachment(db: Session, row: ChatAttachment) -> None:
    path = attachments_root() / row.storage_path
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        log.warning("Could not delete attachment file %s", path)
    db.delete(row)
