import pytest
from sqlalchemy import text
from sqlmodel import Session, select
from app.core.database import engine
from app.models.models import KnowledgeBase, DocumentChunk, FileDocument, CustomModel


def test_postgres_connection_and_version():
    """验证 PostgreSQL 连接与版本 (18+)"""
    with Session(engine) as session:
        result = session.exec(text("SELECT version();")).first()
        assert result is not None
        version_str = str(result[0])
        assert "PostgreSQL" in version_str


def test_pgvector_extension_active():
    """验证 pgvector 扩展、向量列与 HNSW 索引真实存在"""
    with Session(engine) as session:
        ext = session.exec(
            text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
        ).first()
        assert ext is not None and ext[0] == "vector"

        col = session.exec(text(
            "SELECT data_type, udt_name FROM information_schema.columns "
            "WHERE table_name='document_chunks' AND column_name='embedding';"
        )).first()
        assert col is not None, "document_chunks.embedding 列不存在"
        assert col[1] == "vector"

        idx = session.exec(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename='document_chunks' AND indexname='ix_document_chunks_embedding_hnsw';"
        )).first()
        assert idx is not None, "pgvector HNSW 索引不存在"


def test_database_tables_exist():
    """验证核心业务数据表均已在 PostgreSQL 中正确创建"""
    with Session(engine) as session:
        tables = session.exec(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
            )
        ).all()
        table_names = [t[0] for t in tables]
        required_tables = [
            "knowledge_bases",
            "file_documents",
            "document_chunks",
            "chunk_index",
            "index_stats",
            "retrieval_logs",
            "custom_models",
        ]
        for tbl in required_tables:
            assert tbl in table_names, f"缺少关键数据表: {tbl}"


def test_enterprise_kb_data_loaded(enterprise_kb_id):
    """验证生产知识库与切片已成功载入 PostgreSQL"""
    with Session(engine) as session:
        kb = session.get(KnowledgeBase, enterprise_kb_id)
        assert kb is not None
        assert kb.chunk_count > 0
        chunks = session.exec(
            select(DocumentChunk)
            .join(FileDocument, DocumentChunk.file_id == FileDocument.id)
            .where(FileDocument.kb_id == enterprise_kb_id)
        ).all()
        assert len(chunks) == kb.chunk_count
