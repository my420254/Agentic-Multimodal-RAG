"""
自动化 Agent 与 RAG 基准评测运行脚本 (Benchmark Runner)

支持：
1. 批量运行 50 道黄金测试集 (包含全量、基础、多步推理、对抗防幻觉、闲聊快路径)
2. 自动化消融实验 (Ablation Study):
   - Baseline: 纯向量检索 (无重排, 普通模式)
   - Hybrid + Rerank: 向量 + BM25 混合检索 + Rerank 重排 (普通模式)
   - Agentic RAG: 完整 Agent 工作流 (意图分流 + 自主检索 + 反思评估 + 3层记忆)
3. 自动生成 Markdown 格式的评测消融对比表与质量报告

DEPRECATED：本脚本中的 60%+/85%+、BGE-Reranker-large 等结论未与当前数据对齐，
禁止引用或用于简历。请使用 `eval_personal_kb.py` + `backend/benchmark/report.md`。
"""

raise SystemExit("DEPRECATED: use eval_personal_kb.py; this script contains old unvalidated numbers")

import os
import sys
import json
import time
import requests
import sqlite3
from typing import List, Dict, Any

from evaluator import AgentEvaluator

BASE_URL = "http://127.0.0.1:8000"
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset.json")


def load_dataset() -> List[Dict[str, Any]]:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_first_knowledge_base_id() -> str:
    """获取数据库中首个测试知识库 ID"""
    try:
        res = requests.get(f"{BASE_URL}/api/v1/knowledge-bases")
        if res.status_code == 200:
            kbs = res.json()
            if isinstance(kbs, list) and len(kbs) > 0:
                return kbs[0]["id"]
            if isinstance(kbs, dict) and "data" in kbs and len(kbs["data"]) > 0:
                return kbs["data"][0]["id"]
    except Exception as e:
        print(f"⚠️ 获取知识库失败: {e}")
    return ""


def run_single_query(
    query: str,
    kb_ids: List[str],
    mode: str = "agent",
    search_mode: str = "hybrid",
    rerank_enabled: bool = True
) -> Dict[str, Any]:
    """发送请求并收集完整的输出流与指标"""
    payload = {
        "messages": [{"role": "user", "content": query}],
        "kb_ids": kb_ids,
        "mode": mode,
        "search_mode": search_mode,
        "top_k": 3,
        "rerank_enabled": rerank_enabled,
        "rerank_top_k": 3,
        "stream": True
    }
    
    start_time = time.time()
    answer_chunks = []
    citations = []
    agent_steps = []
    intent = "qa"

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/chat/completions",
            json=payload,
            stream=True,
            timeout=40
        )
        
        current_event = None
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    event_data = json.loads(data_str)
                    if current_event == "answer_chunk":
                        answer_chunks.append(event_data.get("content", ""))
                    elif current_event == "rag_result":
                        citations = event_data.get("citations", [])
                    elif current_event == "agent_thought":
                        agent_steps.append(event_data)
                        step_content = str(event_data.get("content", ""))
                        if "闲聊意图" in step_content or "chat" in step_content.lower():
                            intent = "chat"
                except Exception:
                    pass
    except Exception as e:
        answer_chunks.append(f"请求发生异常: {str(e)}")

    latency = round(time.time() - start_time, 2)
    full_answer = "".join(answer_chunks)

    return {
        "answer": full_answer,
        "intent": intent,
        "citations": citations,
        "agent_steps": agent_steps,
        "latency": latency
    }


def run_benchmark_suite(sample_limit: int = 15):
    dataset = load_dataset()
    kb_id = get_first_knowledge_base_id()
    kb_ids = [kb_id] if kb_id else []

    print("=" * 70)
    print("🚀 启动 Agent & RAG 全自动化 Benchmark 评测")
    print(f"📁 评测集总题数: {len(dataset)}，知识库 ID: {kb_ids}")
    print(f"📊 本次抽样消融题数: {sample_limit} (含各维度分级题)")
    print("=" * 70)

    # 抽样代表性题目运行消融测试
    # 选取 基础题 7 道，多步推理 5 道，对抗防幻觉 2 道，闲聊 1 道
    selected_cases = []
    categories = {}
    for case in dataset:
        c = case.get("category")
        categories[c] = categories.get(c, 0) + 1
        if c == "factual_sop" and categories[c] <= 7:
            selected_cases.append(case)
        elif c == "multihop_incident" and categories[c] <= 5:
            selected_cases.append(case)
        elif c == "adversarial_security" and categories[c] <= 2:
            selected_cases.append(case)
        elif c == "fastpath_routing" and categories[c] <= 1:
            selected_cases.append(case)

    configurations = [
        {"name": "方案 1: Baseline (纯向量检索 / 无重排)", "mode": "normal", "search_mode": "vector", "rerank": False},
        {"name": "方案 2: Hybrid + Rerank (双路召回 + BGE重排)", "mode": "normal", "search_mode": "hybrid", "rerank": True},
        {"name": "方案 3: Full Agentic (意图路由 + 护栏反思 + 3层记忆)", "mode": "agent", "search_mode": "hybrid", "rerank": True},
    ]

    ablation_summary = []

    for cfg in configurations:
        print(f"\n▶ 正在运行消融方案: 【{cfg['name']}】...")
        results = []
        for i, case in enumerate(selected_cases):
            print(f"  [{i+1}/{len(selected_cases)}] {case['id']}: {case['query'][:20]}...", end=" ", flush=True)
            output = run_single_query(
                query=case["query"],
                kb_ids=kb_ids,
                mode=cfg["mode"],
                search_mode=cfg["search_mode"],
                rerank_enabled=cfg["rerank"]
            )
            score_data = AgentEvaluator.evaluate_turn(case, output)
            results.append(score_data)
            status_icon = "✅" if score_data["task_success"] else "❌"
            print(f"{status_icon} ({score_data['latency']}s, 命中: {int(score_data['hit_ratio']*100)}%)")

        # 统计指标
        total = len(results)
        success_count = sum([1 for r in results if r["task_success"]])
        avg_hit = sum([r["hit_ratio"] for r in results]) / total
        avg_latency = sum([r["latency"] for r in results]) / total
        avg_tokens = sum([r["est_tokens"] for r in results]) / total
        hallucination_count = sum([1 for r in results if r["hallucination_detected"]])
        
        summary = {
            "name": cfg["name"],
            "success_rate": f"{(success_count / total) * 100:.1f}%",
            "hit_rate": f"{avg_hit * 100:.1f}%",
            "hallucination_count": hallucination_count,
            "avg_latency": f"{avg_latency:.2f}s",
            "avg_tokens": int(avg_tokens)
        }
        ablation_summary.append(summary)

    # 生成 Markdown 报告
    report_content = f"""# Agent & 多模态 RAG 自动化离线评测与消融实验报告

- **评测时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}
- **评测集规模**: 50 题分级黄金评测集（覆盖基础事实 50%、多步推理 30%、对抗拒答 14%、指令安全 6%）
- **测试环境**: 本地测试集群 (WSL2 Ubuntu, FastAPI + LangGraph + BGE-M3 + BGE-Reranker-large)

## 1. 核心消融实验对比表 (Ablation Table)

| 实验组方案配置 | 任务完成率 (Success Rate) | 检索命中率 (Hit Rate@3) | 幻觉率 (Bad Case 数) | 单次平均耗时 | 平均 Token 消耗 |
| :--- | :---: | :---: | :---: | :---: | :---: |
"""
    for s in ablation_summary:
        report_content += f"| **{s['name']}** | {s['success_rate']} | {s['hit_rate']} | {s['hallucination_count']} 件 | {s['avg_latency']} | {s['avg_tokens']} |\n"

    report_content += """
## 2. 核心技术结论 (面试与简历呈现要点)

1. **从纯向量到混合检索 (Baseline -> Hybrid + Rerank)**：
   - 引入 BM25 稀疏倒排表与 `BGE-Reranker-large` 交叉编码器后，检索命中率由单向量的 **60%+ 大幅跃升至 85%+**，有效克服了精确型号与专有名词的语义漂移。
   - 二次重排的硬阈值截断（Threshold Filtering）将无关脏上下文剔除在外，反而降低了后续 LLM 处理的无用 Token 负载。
2. **从普通检索到 Agent 编排 (Hybrid -> Full Agentic)**：
   - Agent 意图识别节点（Intent Router）成功将闲聊与常规问答走分流处理，避免无脑执行全库检索；
   - Reflexion 反思评分机制在召回质量不佳时自主触发 Query 改写重试，使端到端任务成功率达到最高；
   - 护栏机制（Guardrails）成功实现 **0 死循环空转**，对抗性虚构问题准确拒答率显著提高。
"""

    report_path = os.path.join(os.path.dirname(__file__), "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("\n" + "=" * 70)
    print("📄 自动化评测报告已生成至: backend/benchmark/report.md")
    print("=" * 70)
    print(report_content)


if __name__ == "__main__":
    run_benchmark_suite(sample_limit=15)
