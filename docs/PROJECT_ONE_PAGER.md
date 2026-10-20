# Agentic Multimodal RAG · 秋招项目一页纸

> 面向辽宁大学在校生的求职 Agent：简历/材料解析 → Hybrid RAG → 单工具 Agent → 引用回答 → 模拟面试 → 评测与可观测。

## 1. 一句话定位

**一个可演示、可评测、可运营的 Agentic RAG 应用**，不是通用 Agent harness 平台。

核心链路：

```text
React + Vite
    ↓
FastAPI
    ├── JWT / API Key / owner 隔离 / 逐路由 scope
    ├── 文档上传 → 解析 → 切块 → BGE-M3 向量化
    ├── Hybrid RAG：pgvector + BM25 + 加权融合 + rerank
    ├── LangGraph：intent → agent → tool → grading → retry → answer
    ├── 模拟面试：选简历 → top4 chunk → 出题 + citations
    └── Langfuse：trace / dataset / experiment / prompt
        ↓
PostgreSQL + pgvector / Redis / DeepSeek / SiliconFlow
```

## 2. 技术栈

- 后端：Python、FastAPI、SQLModel、LangGraph、Celery（可选）
- 检索：pgvector + HNSW、jieba BM25、Hybrid、BGE-reranker
- 前端：React、TypeScript、Vite、Ant Design
- 评测：42 条真实简历 golden、10 条 grounding、10 条 Agent；`ir_measures` 标准指标
- 可观测：Langfuse、Prometheus、request_logs、本地 `agent_traces`
- 工程：Alembic、pytest、GitHub Actions、Docker Compose

## 3. 三个关键决策

### 决策 1：Hybrid RAG，但不宣称“显著优于纯向量”

| 模式 | Success@3 | RR@3 | nDCG@3 |
|---|---:|---:|---:|
| vector | **92.31%** | 0.7094 | 0.7629 |
| fulltext | 82.05% | 0.7778 | 0.7888 |
| hybrid 0.7/0.3 | 89.74% | 0.7521 | 0.7894 |

结论：BM25 更快、纯向量更准，hybrid 作为可调策略保留。**不写“混合检索显著提升”。**

### 决策 2：单工具 Agent，不做多 Agent 平台

- 一个 `search_knowledge_base` 工具 + Pydantic schema
- 工具超时 20s、瞬时重试 1 次、错误分类
- grading 评分低 → 改写 query 重试，最多 3 次
- 重复调用熔断、空回答修复

取舍：业务只需要“检索 + 回答”，多 Agent/Checkpoint/HITL/MCP 没有收益。

### 决策 3：可观测和评测交给 Langfuse，业务指标自己保留

- Trace：`chat.request → retrieval → tool → LLM → grading → answer`
- Dataset：`career_demo_v1`（5 条合成简历/JD，非 PII）
- Experiment：`career_quality_baseline`：match_level_ok / score_range_ok / fraud_label_ok / has_star_rewrite 均为 1.0
- Prompt：5 个 Agent prompt，v1 + production label + 代码 fallback
- 保留自研：Hit@K/MRR、citation 正确性、事实保真、权限测试

## 4. 指标（面试可讲，但要带口径）

- 42 条真实简历 golden：vector `evidence_all@3 = 92.31%`，`RR@3 = 0.7094`
- 10 条面试 grounding：10/10 通过
- 5 条求职域合成用例（`career_demo_v1`）：匹配 + 反欺诈 4 个 evaluator 均为 1.0
- 跨领域简历匹配修复：硬技能覆盖率 <34% 时封顶 LOW，避免“学前教育简历 vs Agent 岗”被抬到 MODERATE
- 后端测试：126 passed
- 延迟：单条样本，**不是 P95**

## 5. 生产化与安全

- JWT access/refresh；API Key SHA-256、前缀、吊销、过期
- 逐路由 scope：`kb:read/write`、`chat:read`、`career:*`、`eval:run`、`admin:*`
- KB/file/chunk owner 校验；Agent 空 `kb_ids` 只检索可见 KB
- CORS 白名单；全局异常不返回 `str(exc)`，只返回 `request_id`
- `/health` liveness；`/ready` 检查 PG/Redis/LLM
- Alembic baseline + `AUTO_MIGRATE`；CI + Docker Compose

## 6. 明确不写 / 不声称

- ❌ 通用 Agent harness 平台
- ❌ 多 Agent / Supervisor / Handoff
- ❌ LangGraph Checkpoint 跨进程恢复
- ❌ HITL / MCP / Skills 渐进加载
- ❌ 高并发 / QPS / P95（没有压测）
- ❌ 企业级多租户 / PG RLS（只有 API 层隔离）
- ❌ 统一 LLM Gateway 路由/配额/成本（只有多模型配置）
- ❌ 端到端回答准确率 / 幻觉率
- ❌ LLM-as-a-Judge 平台（只有 dataset/experiment + 确定性 evaluator）
- ❌ “hybrid 显著优于 vector”（数据不支持）

## 7. 面试 5 问

1. 为什么用 hybrid？——BM25 快、向量准，hybrid 没有稳定超过纯向量，保留为可调策略。
2. 检索错还是生成错？——看 trace 的 retrieval/tool/LLM span，以及 citation 是否命中。
3. 怎么评测？——42 条 golden + `ir_measures`；Agent 用 keyword/citation/no_tool_error；不把检索命中率当回答准确率。
4. 权限怎么保证？——JWT/API Key + owner + 逐路由 scope；API 层隔离，不是 PG RLS。
5. 怎么降低幻觉？——只基于上下文回答、引用来源、不足时明确说、grading 重试；但没有量化幻觉率。

## 8. 已知限制 / 下一步

- 压测与 P95：Locust/k6
- 答案级评测：faithfulness、citation correctness、LLM judge 人工校准
- SSE 断线重连/续传
- 真实简历 dataset 的 PII 伪名化或自托管 Langfuse
- 统一 LLM Gateway（可选，按岗位需要）

## 9. PII 处理

- 真实简历、OCR corpus、逐题报告、`real_resumes_golden.json` 全部 gitignore，只在本机；
- tracked golden 使用 `resume.pdf` / `resume.docx` 别名，真实文件名只在本机 ignored 的 `personal_kb_files.local.json`；
- E2E / 切块 / 数据脚本的真实文件名通过环境变量注入；
- Langfuse Cloud 上传求职域合成简历（`career_demo_v1`）和 SRE smoke；真实简历 trace 使用 `TRACE_CONTENT_MODE=metadata/redacted` 或自托管。
