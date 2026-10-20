# 评测报告状态（2026-10-18 更新）

> **旧版本本文件中的 73.3% / 33.3% 等数字已作废。** 那些数字来自未对齐的旧脚本（Baseline 反而高于 Hybrid、Hit Rate 与结论方向矛盾），不再作为项目结论，也不应写进简历。

## 1. 当前真实可复算的评测

### 1.1 真实简历库（4 份 PDF + 9 张 JPG OCR）

- 语料：`data/真实简历/`，13 个文件，入库 **54 chunks**；
- 向量后端：**PostgreSQL pgvector 0.8.1 + HNSW**（`document_chunks.embedding vector(1024)`）；Chroma 仅保留为回滚/对比；
- Golden：`backend/benchmark/real_resumes_golden.json`，**42 条**（39 条可评 + 3 条拒答）；
- 评法：只评检索；标准指标由 `ir_measures` 计算，`Success@3` 的 relevance 定义为“同一个 chunk 同时包含全部 gold_evidence”；拒答类不计 Hit@K；
- 详细逐题报告（含真实姓名/学校，**已 gitignore**）：`backend/benchmark/real_resumes_report.md`；
- 2026-10-19 重跑：结构与相关性映射校验通过，以下数字由 `benchmark/metrics.py` + `ir_measures` 生成。

| 检索模式 | Success@3 | RR@3 | nDCG@3 | evidence_all@3 | evidence_any@3 | 平均检索延迟 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| vector (BGE-M3 + pgvector) | **92.31%** | 0.7094 | 0.7629 | **92.31%** | 97.44% | 465.7 ms |
| fulltext (BM25/jieba) | 82.05% | 0.7778 | 0.7888 | 82.05% | 84.62% | 42.9 ms |
| hybrid 0.7/0.3 (pgvector) | 89.74% | **0.8034** | **0.8272** | 89.74% | 92.31% | 526.7 ms |
| hybrid 0.8/0.2 | **92.31%** | — | — | **92.31%** | 94.87% | 未单独计时 |

- BM25 k1/b 扫描：`evidence_all@3` 均为 82.05%；`evidence_any_rr` 最高为 `k1=2.0, b=0.9` 的 0.8465；
- Hybrid 权重扫描：0.8/0.2 的 evidence_all@3 最高（92.31%），但 `evidence_any_rr` 低于 0.4/0.6（0.8491）；
- 标准 `RR@3` 与自定义 `evidence_any_rr` 不是同一个口径：前者只看“同时包含全部 evidence”的 chunk，后者只要包含任一 evidence；两套都保留，避免拿旧 MRR 冒充标准指标；
- 延迟会随 embedding 网络/缓存波动：本轮 vector 464.1 ms、fulltext 71.2 ms、hybrid 544.2 ms；旧一轮为 632.1 / 151.9 / 814.2 ms，不构成矛盾；
- 结论不变：**当前真实简历库上混合检索没有稳定超过纯向量**；BM25 快 6～8 倍，适合做精确关键词补充，但不能单独作为主召回。

### 1.2 简历切块消融（R01–R08，8 条简历事实题）

只对 PDF/DOCX 重切，临时 Chroma collection；数字来自 `backend/benchmark/chunking_eval.py`。

| 切块大小 | PDF/DOCX chunk 数 | evidence_all@3 | MRR |
| ---: | :--- | ---: | ---: |
| 300 字 | 9 / 11 | 75.00% | 0.6875 |
| 500 字 | 7 / 9 | **75.00%** | **0.6875** |
| 800 字 | 5 / 8 | 75.00% | 0.5417 |

- 旧库中 PDF 2 chunks / DOCX 4 chunks，R01–R08 在完整库里几乎全部被 202 块的实习笔记挤掉；
- 采用 **500 字 / 50 overlap** 重灌后，真实简历库的简历题才可检索；800 字 MRR 明显下降，因此选 500。

### 1.3 首 token 延迟（单条样本，非分布结论）

真实问题：“某候选人的硕士学校和专业、就读时间是什么？”，`deepseek-chat`，KB=`kb_real_resumes`：

| 配置 | TTFT | 总耗时 | 结果 |
| :--- | ---: | ---: | :--- |
| hybrid，无 rerank | 2.99 s | 3.56 s | 答案正确，但先提到无关图片 |
| hybrid + BGE-Reranker-v2-m3 | 3.70 s | 4.15 s | top1 命中目标候选人，答案先给正确信息 |

> 只跑了一条，不能据此写 P95；要写 P95 需跑 ≥20 条并记录分布。TTFT 是 Chroma 时期样本，pgvector 切换后未重跑，不要混用。

## 2. 尚未完成的评测

- **LLM 选型 A/B**：当前只配置了 `deepseek-chat` 一个 LLM Key；没有第二个模型 Key，不能伪造对比。Embedding 也只有 `BAAI/bge-m3`。
- **Agent 全量评测**：已有 LangGraph Agent 与 50 条 SRE golden，但本轮优先完成真实简历 RAG；Agent 全量 50 条未重跑。
- **60 条 golden / 6 组消融的 W4 目标**：当前真实简历 golden 42 条，未达到 60 条。

## 3. 复算命令

```bash
cd /home/yang/Agentic-Multimodal-RAG/backend

# 真实简历检索评测（需要本地 real_resumes_golden.json 与已入库 KB；默认 pgvector）
JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  python3 benchmark/eval_personal_kb.py \
  --kb-id kb_real_resumes \
  --golden benchmark/real_resumes_golden.json \
  --out-json benchmark/real_resumes_eval.json \
  --out-md benchmark/real_resumes_report.md

# 切块消融
JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  python3 benchmark/chunking_eval.py

# Golden 体检：结构 + 相关性映射（不是跑模型）
JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  python3 benchmark/validate_golden.py \
  --golden benchmark/real_resumes_golden.json --kb-id kb_real_resumes
JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  python3 benchmark/validate_golden.py \
  --golden benchmark/personal_kb_golden.json \
  --kb-id 6d3e18a1-f70a-4acc-80a6-65eaea9a7a69
```

真实简历、OCR corpus、逐题报告均含 PII，已在 `.gitignore` 中排除，只保留在本地。

> **PII 处理（2026-10-20）**：tracked 文件中已移除真实姓名/文件名/手机号/邮箱。  
> - `personal_kb_golden.json` 使用 `resume.pdf` / `resume.docx` 别名；真实文件名只放在本机 ignored 的 `personal_kb_files.local.json`；  
> - `interview_grounding_eval.py`、`chunking_eval.py`、`scripts/*` 改用 `E2E_RESUME_*` / `CHUNKING_*` / `RESUME_NAMES` 环境变量；  
> - `real_resumes_golden.json`、`real_resumes_corpus.json`、`real_resumes_report.md`、`data/真实简历/` 继续 gitignore。

## 1.5 模拟面试 grounding E2E（2026-10-19）

- 脚本：`backend/benchmark/interview_grounding_eval.py`；
- 用例：4 份真实简历 × 10 个岗位/回答组合；
- 每一轮先按 `resume_file_id` 过滤 pgvector，取 top4 chunk，再注入面试官提示词；
- 判定：
  - `grounding_available=true`；
  - `grounding_citations` 非空；
  - 所有 citation 的 `file_name` **只能等于选定文件**；
  - 响应里不能出现 GraphRAG 字段；
  - 问题文本长度 ≥20。
- 结果：**10/10 通过**；每轮 citation 4 条，全部来自所选简历；单轮耗时约 **3.0–4.9s**（单次样本，不是 P95）。
- 说明：面试官问题会引用简历里的原始表述（例如简历自己写了 RRF/FAISS/8KB），这不代表系统验证了这些数字；系统只保证“问题来自这份材料”。

复算：

```bash
cd /home/yang/Agentic-Multimodal-RAG/backend
python3 benchmark/interview_grounding_eval.py
```

## 1.6 上传 → 提问 → 引用全链路 E2E（2026-10-19）

- 脚本：`scripts/e2e_upload_ask.py`；
- 链路：登录 → 创建临时 KB → 上传 `e2e_qcm.md` → 解析/向量化 → 提问“量子咖啡机 QCM 项目的技术栈是什么？” → 读取 SSE 引用 → 永久删除临时 KB；
- 结果：**PASS**；
  - 文件：`e2e_qcm.md`，1 chunk；
  - 引用：`e2e_qcm.md`，score 0.718；
  - 回答包含 `FastAPI`、`Redis`、`PostgreSQL`；
  - 临时 KB 已清理。

> 这个用例只验证链路，不验证真实简历内容；真实简历 grounding 见 1.5 的 10 条用例。

## 1.7 Agent 模式评测与工具治理（2026-10-19）

- 脚本：`backend/benchmark/agent_eval.py`；
- 10 条 SRE 知识库问题，走完整 Agent 循环（意图 → 工具 → observation → grading → 最终回答）；
- 结果：**9/10** 通过（keyword_ratio ≥75% + 非开头拒答 + citations 非空 + 无 tool_error）；A04 Redis Cluster 自动转移因 KB 覆盖不足被模型正确拒答；
- 单条耗时约 **6.6–18.5s**（单次样本，不是 P95）；
- 修复了一个真实 bug：检索 3 次仍不足时，原图直接 END，answer 为空；现在 grading 会路由到 `generate_answer`，基于现有上下文回答并明确说明不足。

工具治理：

- `SearchKnowledgeBaseInput` Pydantic schema：`extra=forbid`，query 1–500 字，top_k 1–20，权重 0–1；
- 工具超时 20s，瞬时错误最多重试 1 次；
- 错误分类：`validation_error` / `timeout` / `execution_error`，回传给 Agent 作为 `tool_error` step；
- 5 条工具治理单测：未知参数、空 query、越界 top_k、超时、瞬时重试。

## 1.8 Agent Trace 与后台可观测（2026-10-19）

- `/chat/completions` 生成 `X-Trace-Id`，`done` 事件带 `trace_id`；
- 落 `agent_traces`：query/answer_preview、citations、steps、tool_calls、TTFT、total_ms、error；
- Admin `GET /admin/traces` 列表与详情，前端“观测”页展示；
- 实测：一次 Agent 请求 `trace_id=tr_671a...`，TTFT 5457ms、total 8366ms，citations 3；Admin 可查；
- 说明：这是本地 trace，不是 Langfuse；Langfuse/Phoenix 外部后端仍未接。

## 1.9 Golden 数据集体检与评测口径修正（2026-10-19）

### 42 条真实简历 golden

- 结构：42 条 = 39 answer + 3 refuse；ID 无重复、query 无重复、`mix` 与 category 分布一致；
- 映射：39 条 answer 都能在 54 个 chunk 中找到“同时包含全部 evidence”的 chunk，无 impossible/ambiguous；
- 拒答：X01–X03 分别问高考分数、身份证号、期望薪资；语料中三个关键词均为 0 次命中，拒答前提成立；
- 结论：**42 条结构可用**；PII 问题见 §3 的例外说明。

### 38 条个人材料 golden

- 修复了 1 条坏样本 `P02`：原 evidence `["1.69%", "23.03%"]` 中 `1.69%` 来自 TweetEval 的另一句话，和 SST-5 Config B 的 `±1.69%` 不是同一处；改为 `["SST-5 Config B", "标准差", "1.69", "23.03"]`；
- 修复了 2 条弱证据：
  - `N03` 的 `["600","400","120","80"]` 会同时命中论文笔记的无关片段；改为 `["600 题", "factoid 400", "multi_hop 120", "unanswerable 80"]`；
  - `N04` 的 `["15"]` 在 219 个 chunk 中命中 38 个；改为 `["24.2%", "15 条"]`；
- 修正 3 条 category 标注：`X06`（CET-6 500+，实际可答）改为 `resume_fact`；`C05`/`C06`（基于笔记的事实回答）改为 `notes_fact`；
- 口径修正：`report_conflict` 的 4 条（C01–C04）**不再混入 Hit@K/MRR**；它们要求跨 chunk 取证，用单 chunk 的 `evidence_all` 计算会系统性压低分数；
- 重跑结果（29 条 answer，5 条 refusal，4 条 conflict 单独列出）：

| 检索模式 | Success@3 | RR@3 | nDCG@3 | evidence_all@3 | 平均检索延迟 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| vector (BGE-M3 + pgvector) | 79.31% | 0.7011 | 0.5817 | 79.31% | 423.5 ms |
| fulltext (BM25/jieba) | 79.31% | 0.7356 | 0.6394 | 75.86% | 61.7 ms |
| hybrid 0.7/0.3 | **86.21%** | **0.7471** | **0.6475** | **86.21%** | 491.9 ms |

- 2026-10-20 质量修复：`HiPro-LoRA.md` 旧版是 **1 个 75,712 字符巨型 chunk**，BGE-M3 无法有效编码；已按 500/50 重切为 **160 个 chunk**。检索增加“简历/笔记/论文”文件意图路由和更大候选池，避免单个文件垄断 top-k。
- 影响：旧的 38 条结果里 vector `evidence_all@3=60.61%` 包含 4 条必失败的 conflict 样本；仅算 29 条 answer 时为 68.97%；修完坏/弱证据后 72.41%；重切论文笔记 + 文件路由后 **79.31%**，hybrid **86.21%**。旧数字不是“模型退步”，而是分母、样本和 chunk 质量有问题。
- 口径提醒：个人材料库有 PDF/DOCX 重复导出和重复事实，因此 `P@3`/`Recall@3` 会被“多个相关 chunk”稀释；看检索是否命中，优先看 `Success@3`，看排序质量看 `RR@3`/`nDCG@3`。

### 标准指标迁移

- 指标实现：`ir_measures`（`Success@3`、`P@3`、`Recall@3`、`RR@3`、`nDCG@3`）；
- 相关性定义：`benchmark/metrics.py`，一个 chunk 算 relevant 当且仅当同时包含全部 `gold_evidence`；
- 兼容指标：`evidence_all@3`、`evidence_any@3`、`evidence_any_rr` 保留，用于和旧报告对齐；
- 术语修正：旧字段 `mrr` 实际是“首个包含任一 evidence 的 chunk 的 reciprocal rank”，新输出改名为 `evidence_any_rr`，不再冒充标准 MRR。
