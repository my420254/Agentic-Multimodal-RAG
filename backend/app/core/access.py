"""
知识库资源归属校验。

规则：
- owner_id 为 NULL：系统/公共知识库，所有登录用户可读；
- owner_id 非 NULL：仅 owner 本人可见，其他人统一 404（不泄露存在性）；
- 文件、chunk 通过 kb_id 继承所属知识库的权限。
"""

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import DocumentChunk, FileDocument, KnowledgeBase, User


def kb_visibility_filter(user: User):
    """SQLModel/SQLAlchemy where 条件：公共 KB 或本人 KB。"""
    return or_(
        KnowledgeBase.owner_id.is_(None),
        KnowledgeBase.owner_id == str(user.id),
    )


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": 40401, "message": f"{what}不存在"},
    )


def visible_kb_ids_for_user(session: Session, user: User) -> list[str]:
    """当前用户可见的 KB ID 列表（公共 + 本人）。"""
    return [
        kb.id
        for kb in session.exec(
            select(KnowledgeBase).where(kb_visibility_filter(user))
        ).all()
    ]


def get_visible_kb(
    session: Session,
    kb_id: str,
    user: User,
    include_deleted: bool = True,
) -> KnowledgeBase:
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise _not_found("知识库")
    if not include_deleted and kb.is_deleted:
        raise _not_found("知识库")
    if kb.owner_id is not None and kb.owner_id != str(user.id):
        raise _not_found("知识库")
    return kb


def get_visible_file(session: Session, file_id: str, user: User) -> FileDocument:
    file_doc = session.get(FileDocument, file_id)
    if file_doc is None:
        raise _not_found("文件")
    get_visible_kb(session, file_doc.kb_id, user)
    return file_doc


def get_visible_chunk(session: Session, chunk_id: str, user: User) -> DocumentChunk:
    chunk = session.get(DocumentChunk, chunk_id)
    if chunk is None:
        raise _not_found("Chunk")
    get_visible_file(session, chunk.file_id, user)
    return chunk
