<div align="center">

# 辽大·求职 Agent

**面向高校学生的 Agentic 求职助手：简历诊断、模拟面试、岗位反欺诈与可追溯知识库问答**

把简历、项目材料、招聘 JD 和面试对话串成一条可评测、可观测的求职链路，而不是只做一个“文档问答 Demo”。

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-TypeScript-149ECA?logo=react&logoColor=white)](https://react.dev/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-1C3C3C)](https://github.com/langchain-ai/langgraph)
[![Langfuse](https://img.shields.io/badge/Langfuse-Observability-0A7AFF)](https://langfuse.com/)
[![CI](https://github.com/my420254/Agentic-Multimodal-RAG/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/my420254/Agentic-Multimodal-RAG/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)

[功能](#功能) · [工作流程](#工作流程) · [快速开始](#快速开始) · [评测与可观测](#评测与可观测) · [项目结构](#项目结构)

</div>

## 这个项目解决什么问题？

高校学生求职时通常有三个断点：

1. **简历不知道弱在哪**：项目描述全是“负责/参与/优化”，没有量化、没有取舍、没有边界；
2. **面试没有真实追问**：背题库不等于能应对“基于你简历的追问”；
3. **招聘信息真假难辨**：培训贷、境外诱导、刷单灰产等风险信息混在 JD 里。

这个项目把三件事做成一条链路：

- 简历/材料上传 → 解析 → 切块 → Hybrid RAG；
- 简历 × JD 匹配 → 能力雷达 → STAR 重写（事实保真，没数据就留占位符）；
- 选中一份简历 → 检索 top chunk → 模拟面试官追问 + 引用；
- 岗位 JD → 反欺诈规则 + 可选 LLM 审计；
- 全链路 trace / dataset / experiment / prompt 版本。

## 功能

### 求职核心

- **简历深度诊断**：按目标 JD 计算综合匹配度、硬技能缺口、能力雷达、关键优势与薄弱项；
- **STAR 量化重写**：只重组简历已有事实，没有实测数字时保留 `[请补充真实数据]` 占位符，不编造；
- **模拟面试**：选择一份简历，按 `resume_file_id` 只检索该文件的 top4 chunk，再出题、追问、打分、给改进建议；回答带 citations；
- **岗位反欺诈**：培训贷、境外高薪、刷单、扣押证件等规则识别，可选 LLM 深度审计；
- **提示词工坊**：用户级 `mock_interviewer` / `resume_doctor` / `star_rewriter` 覆盖。

### RAG 与 Agent

- **多模态解析**：PDF、DOCX、Markdown、TXT、JPG、PNG；保留标题层级、图片 chunk 与引用位置；
- **Hybrid 检索**：pgvector 向量 + jieba BM25 加权融合，可选 Rerank 与上下文扩展；
- **单工具 LangGraph Agent**：意图路由 → `search_knowledge_base` → grading → 低质量重试（最多 3 次）→ 最终回答；
- **工具治理**：Pydantic schema、`extra=forbid`、超时、瞬时重试、错误分类、重复调用熔断；
- **引用可追溯**：回答返回 `citations`（文件、chunk、页码/位置、分数）。

### 工程与运营

- **鉴权与隔离**：JWT access/refresh、API Key SHA-256、owner 校验、逐路由 scope、Admin 角色、审计日志；
- **多租户边界**：KB/file/chunk 在 API/Agent 层做 owner 隔离；**不是 PostgreSQL RLS**；
- **可观测**：Langfuse trace / dataset / experiment / prompt；本地 `agent_traces` fallback；Prometheus + request_logs；
- **生产化**：Alembic migration、`/ready` 检查 PG/Redis/LLM、CORS 白名单、统一异常 + `request_id`、Docker Compose、CI。

## 实际界面

当前前端导航（登录后）：

| 页面 | 作用 |
| :--- | :--- |
| **简历诊断** `/career/resume` | 选简历 → 对比 JD → 匹配度/雷达/STAR 重写 |
| **模拟面试** `/career/interview` | 选简历 → 多轮追问 → 评分与改进建议 |
| **提示词工坊** `/career/prompts` | 用户级面试官/简历医生提示词覆盖 |
| **知识库** `/kb` | 上传、解析、切块、向量化、召回测试 |
| **智能对话** `/chat` | Hybrid RAG 问答 + Agent 思考步骤 + citations |
| **管理后台** `/admin` | 用户、API Key、模型、系统提示词、审计、观测 |

### 登录

![登录](docs/assets/login.jpg)

### 简历诊断

选择/粘贴简历与目标 JD，输出匹配度、能力雷达、痛点与 STAR 量化重写。截图中的简历内容已用合成数据替代，真实姓名已脱敏。

<details>
<summary>展开完整诊断报告截图</summary>

![简历诊断](docs/assets/career-resume.jpg)

</details>

### 模拟面试

选择一份简历后，面试官只基于该文件的 top4 chunk 出题，追问带 citations。

![模拟面试](docs/assets/career-interview.jpg)

### 提示词工坊

面试官、简历医生、STAR 重写三类系统提示词可查看、修改并即时生效。

![提示词工坊](docs/assets/career-prompts.jpg)

### 知识库

支持多格式上传、解析状态、chunk 预览、向量化与召回测试。

![知识库](docs/assets/knowledge-base.jpg)

### 智能对话

Hybrid RAG 问答，展示 Agent 步骤、召回详情与 citations。

![智能对话](docs/assets/chat.jpg)

### 管理后台

业务控制面（用户、API Key、模型、系统提示词、审计日志）+ Langfuse 观测摘要（traces、P95、错误率、tokens、实验入口）；详细 trace 在 Langfuse UI 查看。

![管理后台](docs/assets/admin.jpg)

## 工作流程

```mermaid
flowchart LR
    A["简历 / 项目材料 / JD"] --> B["多模态解析"]
    B --> C["标题感知 / 递归切块"]
    C --> D["pgvector 向量索引"]
    C --> E["jieba BM25 索引"]

    Q["求职任务"] --> F{"入口"}
    F -->|简历诊断| G["简历 × JD 匹配 + STAR 重写"]
    F -->|模拟面试| H["按 resume_file_id 检索 top4 chunk"]
    F -->|岗位反欺诈| I["规则 + 可选 LLM 审计"]
    F -->|知识库问答| J["Hybrid RAG"]
    D --> J
    E --> J
    J --> K["LangGraph Agent"]
    K --> L{"相关性足够？"}
    L -->|否| M["改写 query 重试"]
    M --> J
    L -->|是| N["带 citations 的回答"]
    G --> O["Langfuse trace / dataset / experiment"]
    H --> O
    I --> O
    N --> O
```

## 技术架构

```text
React + TypeScript + Vite + Ant Design
                |
                v
            FastAPI
  ┌─────────────┼──────────────┬──────────────┐
  │             │              │              │
Auth/KB      Retrieval      Career/Interview  Admin
  │             │              │              │
  └──────┬──────┴──────┬───────┴──────┬───────┘
         │             │              │
   PostgreSQL      Redis          LLM / Embedding / VLM / Rerank
   + pgvector     cache/session    DeepSeek / SiliconFlow / Ollama
         │
    Langfuse (trace / dataset / experiment / prompt)
```

主要组件：

- Backend：FastAPI、SQLModel、LangGraph、Celery（可选）
- Frontend：React、TypeScript、Vite、Ant Design
- Retrieval：pgvector + HNSW、jieba BM25、Hybrid、可选 Rerank
- 评测：`ir_measures`、golden set、Langfuse Experiments
- 存储：PostgreSQL（含 pgvector）、Redis、本地文件存储
- 工程：Alembic、pytest、GitHub Actions、Docker Compose

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- PostgreSQL 16+ 且安装 pgvector
- Redis
- 任意 OpenAI-compatible 模型服务（DeepSeek / SiliconFlow / Ollama 等）

### 1. 克隆项目

```bash
git clone https://github.com/my420254/Agentic-Multimodal-RAG.git
cd Agentic-Multimodal-RAG
```

### 2. 启动后端

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，至少配置：

```dotenv
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/agent_db
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<至少 32 字符，用 secrets.token_urlsafe 生成>

LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=...
LLM_MODEL=deepseek-chat

EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=BAAI/bge-m3
```

启动：

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

首次启动会自动执行 Alembic migration；也可以手动：

```bash
alembic upgrade head
```

### 3. 启动前端

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:3000`，登录后默认进入 **简历诊断**。

### 4. 初始化本地数据（可选）

```bash
cd backend
python scripts/seed_admin.py          # 管理员账号
python scripts/seed_demo_users.py     # 演示学生账号
python scripts/ingest_real_resumes.py # 本地真实简历（PII，不要提交）
python scripts/sync_pgvector.py       # 同步向量
```

### 5. Docker Compose（可选）

```bash
export JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
docker compose build
docker compose up -d
curl http://127.0.0.1:8000/ready
```

前端 `http://127.0.0.1:3000`，后端 `http://127.0.0.1:8000`。  
使用宿主机 Ollama 时，把 `LLM_BASE_URL` / `EMBEDDING_BASE_URL` 改为 `http://host.docker.internal:11434/v1`。详见 [`docs/DOCKER.md`](docs/DOCKER.md)。

## 评测与可观测

### 求职域指标

| 评测 | 数据 | 结果 |
| :--- | :--- | :--- |
| 真实简历检索 | 42 条 golden、54 chunks | vector `evidence_all@3 = 92.31%`，`RR@3 = 0.7094` |
| 模拟面试 grounding | 10 条真实简历 × 岗位 | **10/10** 通过 |
| 求职匹配 / 反欺诈 | `career_demo_v1` 5 条合成简历 | 4 个 evaluator 均 **1.000** |
| 后端测试 | 127 条 | **127 passed**（CI 122 passed + 5 skipped） |

> `evidence_all@3` 是检索命中，不是回答准确率；延迟是单条样本，不是 P95。  
> Hybrid 没有稳定超过纯向量：BM25 更快、向量更准，hybrid 作为可调策略保留。

### Langfuse

```bash
# 同步 Agent prompt（5 个 key，production label）
python backend/scripts/sync_langfuse_prompts.py

# 求职域 dataset + experiment
python backend/benchmark/langfuse_career_dataset.py --run-experiment

# 通用 Agent smoke（SRE 非 PII 语料）
python backend/benchmark/langfuse_agent_dataset.py --run-experiment
```

- Trace：`chat.request → retrieval → tool → LLM → grading → answer`；
- Dataset / Experiment：`career_demo_v1` / `career_quality_baseline`；
- Prompt：`agent.intent` / `agent.system` / `agent.grading` / `agent.answer` / `agent.chat`；
- 未配置 key 时自动 no-op，本地 `agent_traces` 继续工作。

### Admin 与 Langfuse 的分工

| 能力 | Admin | Langfuse |
| :--- | :--- | :--- |
| 用户 / API Key / 模型 / 审计 | ✅ 业务控制面 | ❌ |
| trace / span / tool / retrieval / LLM 延迟 | 24h 摘要 | ✅ 详情与过滤 |
| P95 / 错误率 / tokens | 摘要卡片 | ✅ 按 trace/实验对比 |
| Dataset / Experiment / Score | 跳转入口 | ✅ 数据集与实验 |
| Prompt 版本 / 回滚 | 用户级覆盖 | ✅ 全局版本与 label |
| RAG Hit@K / MRR / citation | 自研 evaluator 计算 | 展示 score，不原生计算 |

Admin 的“观测”tab 调用：

```text
GET /api/v1/admin/observability/langfuse-summary?hours=24
```

后端用 Langfuse Basic Auth 聚合最近 24h 的 observations（60s 缓存），前端只拿摘要，不暴露 key；详细分析直接跳转 Langfuse Traces / Experiments / Prompts / Datasets。

### 前后端边界

- React SPA 通过 REST/SSE 调 FastAPI，CORS 使用白名单；
- Admin 是独立前端路由，业务 API 在 `/api/v1/admin/*`；
- 可观测详情在 Langfuse，Admin 只保留业务控制面和摘要/跳转，不重复造第二个评测 UI。

### Golden 体检

```bash
cd backend
python benchmark/validate_golden.py \
  --golden benchmark/personal_kb_golden.json \
  --kb-id <your-kb-id>
```

### PII

- 真实简历、OCR corpus、逐题报告、`real_resumes_golden.json` 全部 gitignore；
- tracked golden 使用 `resume.pdf` / `resume.docx` 别名，真实文件名只在本机 ignored 的 `personal_kb_files.local.json`；
- Langfuse Cloud 只上传求职域合成简历和 SRE smoke；真实简历 trace 使用 `TRACE_CONTENT_MODE=metadata/redacted` 或自托管。

## 项目结构

```text
backend/app/
├── api/                     auth / chat / career / knowledge_base / files / chunks / recall / admin / benchmark
├── core/                    配置、数据库、鉴权、access、metrics、rate limit、rerank loader、tracing
├── models/                  SQLModel 表
├── services/
│   ├── retrieval.py         pgvector + BM25 + hybrid + rerank + cache
│   ├── agent_workflow.py    LangGraph：intent → tool → grading → retry → answer
│   ├── mock_interview.py    基于选中简历 chunk 的模拟面试
│   ├── career_matcher.py    简历 × JD 匹配 + STAR 重写
│   ├── job_fraud_detector.py 岗位反欺诈
│   ├── prompt_registry.py   Langfuse prompt + code fallback
│   └── trace_service.py     本地 trace fallback
├── tools/                   search_knowledge_base + governance
├── tasks/                   Celery（可选）
├── benchmark/               42/10/10 golden、标准指标、Langfuse dataset/experiment
├── alembic/                 baseline migration
└── tests/                   127 条测试

frontend/src/
├── pages/CareerCenter/      简历诊断 / 模拟面试 / 提示词工坊
├── pages/KnowledgeBase/     上传、详情、chunk 预览、召回测试
├── pages/Chat/              流式问答 + Agent 步骤 + citations
├── pages/Admin/             用户 / API Key / 模型 / Prompt / 审计 / 观测
└── services/                API 客户端
```

## 已知边界

- 单工具 Agent，不是通用 Agent harness 平台；没有多 Agent / Supervisor / Handoff；
- 没有 LangGraph Checkpoint 跨进程恢复、HITL、MCP / Skills；
- 没有生产级压测 / QPS / P95；没有统一 LLM Gateway 路由/配额；
- 多租户是 API/Agent 层 owner 隔离，不是 PostgreSQL RLS；
- 没有 LLM-as-a-Judge 平台；当前 evaluator 是确定性指标；
- 真实简历数据只在本机，公开仓库不包含。

## Contributing

欢迎提交 Issue 和 Pull Request。提交前请运行：

```bash
cd backend && pytest -q
cd ../frontend && npm run build
```

## License

本项目采用 [MIT License](LICENSE)。
