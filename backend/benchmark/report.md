# 评测报告状态（2026-10-18 更新）

> **旧版本本文件中的 73.3% / 33.3% 等数字已作废。** 那些数字来自未对齐的旧脚本（Baseline 反而高于 Hybrid、Hit Rate 与结论方向矛盾），不再作为项目结论，也不应写进简历。

## 1. 当前真实可复算的评测

### 1.1 真实简历库（4 份 PDF + 9 张 JPG OCR）

- 语料：`data/真实简历/`，13 个文件，入库 **54 chunks**；
- 向量后端：**PostgreSQL pgvector 0.8.1 + HNSW**（`document_chunks.embedding vector(1024)`）；Chroma 仅保留为回滚/对比；
- Golden：`backend/benchmark/real_resumes_golden.json`，**42 条**（39 条可评 + 3 条拒答）；
- 评法：只评检索；`evidence_all@3` 要求 gold evidence 的每条短语都出现在 top3 正文；拒答类不计 Hit@K；
- 详细逐题报告（含真实姓名/学校，**已 gitignore**）：`backend/benchmark/real_resumes_report.md`。

| 检索模式 | evidence_all@3 | evidence_any@3 | MRR | 平均检索延迟 |
| :--- | ---: | ---: | ---: | ---: |
| vector (BGE-M3 + pgvector) | **92.31%** | 97.44% | 0.7479 | 632.1 ms |
| fulltext (BM25/jieba) | 82.05% | 84.62% | 0.8075 | 151.9 ms |
| hybrid 0.7/0.3 (pgvector) | 89.74% | 92.31% | 0.7799 | 814.2 ms |
| hybrid 0.8/0.2 | **92.31%** | 94.87% | 0.7274 | 未单独计时 |

- BM25 k1/b 扫描：`evidence_all@3` 均为 82.05%；MRR 最高为 `k1=2.0, b=0.9` 的 0.8465；
- Hybrid 权重扫描：0.8/0.2 的 evidence_all@3 最高（92.31%），但 MRR 低于 0.4/0.6（0.8491）；
- 结论：**当前真实简历库上混合检索没有稳定超过纯向量**；BM25 快 6～8 倍，适合做精确关键词补充，但不能单独作为主召回。

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

真实问题：“张梦洋的硕士学校和专业、就读时间是什么？”，`deepseek-chat`，KB=`kb_real_resumes`：

| 配置 | TTFT | 总耗时 | 结果 |
| :--- | ---: | ---: | :--- |
| hybrid，无 rerank | 2.99 s | 3.56 s | 答案正确，但先提到无关图片 |
| hybrid + BGE-Reranker-v2-m3 | 3.70 s | 4.15 s | top1 命中张梦洋，答案先给正确信息 |

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
```

真实简历、OCR corpus、逐题报告均含 PII，已在 `.gitignore` 中排除，只保留在本地。

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
