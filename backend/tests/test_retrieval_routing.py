"""文件意图路由与候选池测试（不依赖数据库）。"""

from app.services.retrieval import _candidate_k, _route_by_file_intent


def _row(file_name: str, score: float) -> dict:
    return {"file_name": file_name, "score": score, "content": ""}


def test_candidate_pool_expands_for_file_intent_queries():
    assert _candidate_k("简历上第一篇论文是什么？", 3) == 100
    assert _candidate_k("笔记里 Query 改写几次？", 3) == 100
    assert _candidate_k("Kubernetes OOM 排查", 3) == 20


def test_resume_intent_routes_to_resume_files_in_mixed_kb():
    results = [
        _row("notes.md", 0.90),
        _row("paper.md", 0.80),
        _row("resume.pdf", 0.50),
        _row("resume.docx", 0.40),
    ]
    out = _route_by_file_intent("简历上第一篇论文的会议是什么？", results, 3)
    assert {row["file_name"] for row in out} == {"resume.pdf", "resume.docx"}


def test_pure_resume_kb_keeps_original_order():
    results = [_row("a.pdf", 0.9), _row("b.pdf", 0.8), _row("c.pdf", 0.7)]
    out = _route_by_file_intent("简历上第一篇论文的会议是什么？", results, 2)
    assert [row["file_name"] for row in out] == ["a.pdf", "b.pdf"]


def test_notes_intent_routes_to_markdown_in_mixed_kb():
    results = [
        _row("resume.pdf", 0.90),
        _row("notes.md", 0.60),
        _row("paper.md", 0.50),
    ]
    out = _route_by_file_intent("笔记里沙盒怎么防命令注入？", results, 2)
    assert {row["file_name"] for row in out} == {"notes.md", "paper.md"}
