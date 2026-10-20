"""
Benchmark 评测与消融指标 API
只提供已持久化的评测记录与报告查询；没有记录时返回空结果，不返回演示数据。
"""

import os
from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.deps import get_current_user, require_route_scope
from app.models.models import BenchmarkRecord
from app.schemas.schemas import ApiResponse

router = APIRouter(
    prefix="/benchmark",
    tags=["Benchmark & Evaluation"],
    dependencies=[Depends(get_current_user), Depends(require_route_scope)],
)

REPORT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../benchmark/report.md")
)


@router.get("/records", response_model=ApiResponse[List[Dict[str, Any]]])
async def list_benchmark_records(session: Session = Depends(get_session)):
    """获取所有消融评测历史记录及精度指标"""
    records = session.exec(
        select(BenchmarkRecord).order_by(BenchmarkRecord.created_at.desc())
    ).all()

    # 不再返回硬编码的演示数据：没有记录就诚实返回空列表。
    if not records:
        return ApiResponse(
            code=200,
            message="no benchmark records; run benchmark scripts first",
            data=[],
        )

    data = [
        {
            "id": r.id,
            "plan_name": r.plan_name,
            "dataset_name": r.dataset_name,
            "total_cases": r.total_cases,
            "success_rate": r.success_rate,
            "hit_rate": r.hit_rate,
            "hallucination_count": r.hallucination_count,
            "avg_latency": r.avg_latency,
            "avg_tokens": r.avg_tokens,
            "llm_judge_score": r.llm_judge_score,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    return ApiResponse(code=200, message="success", data=data)


@router.get("/latest", response_model=ApiResponse[Dict[str, Any]])
async def get_latest_benchmark_summary(session: Session = Depends(get_session)):
    """获取最新一条持久化评测记录；没有记录时返回空结果，不再编造指标。"""
    record = session.exec(
        select(BenchmarkRecord).order_by(BenchmarkRecord.created_at.desc()).limit(1)
    ).first()
    if record is None:
        return ApiResponse(
            code=200,
            message="no benchmark records; run benchmark scripts first",
            data={},
        )
    return ApiResponse(
        code=200,
        message="success",
        data={
            "plan_name": record.plan_name,
            "dataset_name": record.dataset_name,
            "eval_timestamp": record.created_at.isoformat() if record.created_at else None,
            "total_cases": record.total_cases,
            "success_rate": record.success_rate,
            "hit_rate": record.hit_rate,
            "hallucination_count": record.hallucination_count,
            "avg_latency": record.avg_latency,
            "avg_tokens": record.avg_tokens,
            "llm_judge_score": record.llm_judge_score,
        },
    )


@router.get("/report", response_model=ApiResponse[Dict[str, str]])
async def get_benchmark_markdown_report():
    """获取最新生成的消融实验报告 Markdown 全文"""
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "# 暂未生成评测报告\n请在后端执行 `python benchmark/run_benchmark.py` 生成。"

    return ApiResponse(code=200, message="success", data={"report_markdown": content})
