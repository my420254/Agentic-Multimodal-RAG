# 项目现状与交接报告（Langfuse 取舍版）

> 仓库：`/home/yang/Agentic-Multimodal-RAG`  
> 盘点时间：2026-10-19  
> 当前 commit：`301aa58 docs: add current project handoff report`  
> 工作区：有未提交改动（golden 修复、标准指标、Langfuse tracing 骨架）；后端 `http://127.0.0.1:8000` 健康；前端 `http://127.0.0.1:3000` 可启动。  
> **给接手人：先读本报告。`docs/HANDOFF.md` 是 W1 鉴权时期的历史任务书，不是当前状态，不要按它从“加鉴权”开始做。**

---

## 0. 一句话结论

这是一个**可演示、可评测、可运营的高校求职 RAG/Agent 应用**：RAG、模拟面试、多租户、管理后台、Prometheus、请求日志、Langfuse trace/dataset/experiment/prompt、API Key scope、`/ready` 都已经落地；  
但它**不是生产级 Agent 平台**：没有 CI/压测/Grafana/Alembic/容器化，多租户仍是 API 层而不是 PG RLS，也没有多 Agent/Checkpoint/HITL/MCP。

**最重要的架构结论：**

> Langfuse 已经提供 trace、prompt 管理、dataset、experiment、score、人工标注；  
> 当前项目自研的 `agent_traces`、评测脚本看板、系统提示词版本 UI，有相当一部分是在重复造轮子。  
> **后续不要继续扩自研观测/评测/提示词平台，应该接 Langfuse；只保留业务特有的评测指标函数和权限控制。**

---

## 1. 项目定位与边界

### 1.1 产品定位

面向辽宁大学在校生的求职 Agent：

- 简历/材料上传、解析、切块、向量化；
- 知识库问答与引用；
- 简历 × JD 匹配；
- 模拟面试（基于选中简历的 chunk 出题，带引用）；
- 复盘/报告；
- 管理后台与可观测。

### 1.2 明确不做

当前项目**没有**以下能力，简历/汇报不要写：

- 多 Agent / Supervisor / Handoff；
- LangGraph Checkpoint 跨进程恢复；
- HITL 审批断点；
- MCP / Skills 渐进加载；
- 真正的生产级 LLM trace/成本平台（Langfuse 未接）；
- 线上 A/B 实验系统；
- 多租户数据库行级安全（owner 隔离在 API/Agent 层，不是 PG RLS）。

这些能力在省心购/中科院项目里讲，不要塞进这个项目。

---

## 2. 现状架构

```text
React + Vite + Ant Design
        |
        v
FastAPI (8000)
  ├── Auth / JWT / owner 校验
  ├── KB / 文件上传 / 解析 / 切块 / 向量化
  ├── Retrieval (pgvector + BM25 + 加权融合 + 可选 rerank)
  ├── LangGraph Agent (intent -> agent -> tools -> grading -> retry/answer)
  ├── Mock Interview (选简历 -> top4 chunk -> 出题 + citations)
  ├── Career tools (match / fraud / report)
  └── Admin (users / api keys / models / prompts / audit / observability)
        |
        +--> PostgreSQL 18 + pgvector (HNSW)
        +--> Redis (cache / session / rate limit)
        +--> DeepSeek (LLM), SiliconFlow BGE-M3 (embedding), BGE-reranker-v2-m3
        +--> Celery + Redis (可选；dev.sh 不启动 worker)
```

关键事实：

- 向量库已经是 **PostgreSQL pgvector**；Chroma 只保留回滚/对比，不是主链路。
- 检索是 **向量 + jieba BM25 加权融合**，不是 RRF；不要写成 RRF。
- Agent 是 **单工具** `search_knowledge_base`，不是多 Agent。
- 本地 trace 落 `agent_traces`，不是 Langfuse。

---

## 3. 已实现功能（按可演示性）

| 模块 | 状态 | 说明 |
| :--- | :--- | :--- |
| 登录/JWT | 完成 | access 15m / refresh 7d；`/auth/login`、`/refresh`、`/me`、`/change-password` |
| 多租户 | 完成（API 层） | KB `owner_id`、Agent 空 `kb_ids` 只检索可见库；不是 PG RLS |
| 知识库 | 完成 | 创建/列表/详情/软删/回收站/恢复/永久删除 |
| 文件上传/解析 | 完成 | PDF/DOCX/MD/TXT/JPG/PNG；解析状态、chunk、文本预览 |
| 多模态 | 完成 | 4 份 PDF + 9 张 JPG OCR 的真实简历库；图片 chunk 可检索 |
| 切块 | 完成 | 标题/递归/固定策略；300/500/800 消融；线上 500/50 |
| 向量化 | 完成 | BGE-M3 1024 维写入 pgvector；HNSW 索引 |
| 检索 | 完成 | vector / fulltext / hybrid；阈值、rerank、上下文扩展、缓存 |
| Agent | 完成（单工具） | LangGraph 意图路由、工具调用、grading、最多 3 次重写、重复调用熔断、空回答修复 |
| 工具治理 | 完成 | Pydantic schema、`extra=forbid`、20s 超时、1 次瞬时重试、错误分类 |
| 模拟面试 | 完成 | 选简历文件 -> top4 chunk -> 出题 + citations；10/10 E2E |
| 求职工具 | 完成 | 简历×JD 匹配、诈骗检测、报告 |
| 记忆 | 完成（基础） | PostgreSQL L1/L2/L3；Redis 缓存 |
| 管理后台 | 完成（P0） | 独立 `admin-frontend/`（3001）；用户/API Key/模型/系统提示词/审计/观测 六个 tab |
| API Key | 完成（部分） | SHA-256、前缀、吊销、过期；**只有 `admin:*` 强制，其他 scope 未逐路由强制** |
| 系统提示词 | 完成（自研） | 版本、草稿、发布、回滚；优先级 用户覆盖 > 全局 active > 代码默认 |
| Prometheus | 完成 | `/metrics`；HTTP/检索指标 |
| 请求日志 | 完成 | `request_logs`，不含 query/response 正文 |
| Agent Trace | 完成（本地 + Langfuse 可选） | 本地 `agent_traces` 保留；Langfuse SDK 5.0.2 已接入 root/tool/retrieval/rerank/LLM span；无 key 自动 no-op |
| RAG/Agent 评测 | 完成（脚本） | 42 条真实简历 golden + 38 条个人材料 golden、10 grounding、10 agent；标准指标走 `ir_measures`，无评测平台 UI |
| 前端 | 完成 | 学生端 `frontend/`（3000）+ 独立观测后台 `admin-frontend/`（3001）；两端构建通过 |

---

## 4. 真实数据与指标

### 4.1 数据库（2026-10-19）

| 对象 | 数量 |
| :--- | ---: |
| users | 3 |
| knowledge_bases | 8 |
| file_documents | 23 |
| document_chunks | 330 |
| chunks with embedding | 330 |
| agent_traces | 2 |
| request_logs | 119 |
| audit_logs | 1 |

### 4.2 检索（42 条真实简历 golden）

| 模式 | Success@3 | RR@3 | nDCG@3 | evidence_all@3 | 平均检索延迟 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| vector (BGE-M3 + pgvector) | **92.31%** | 0.7094 | 0.7629 | **92.31%** | 464.1 ms |
| fulltext (BM25/jieba) | 82.05% | 0.7778 | 0.7888 | 82.05% | 71.2 ms |
| hybrid 0.7/0.3 | 89.74% | 0.7521 | 0.7894 | 89.74% | 544.2 ms |
| hybrid 0.8/0.2 | **92.31%** | — | — | **92.31%** | 未单独计时 |

> 标准指标由 `ir_measures` 计算；`Success@3` 的 relevance = “同一 chunk 同时包含全部 gold_evidence”。
> 旧报告里的 MRR 0.7479 实际是 `evidence_any_rr`（只要包含任一 evidence），不是标准 MRR；两套都保留，但不要混写。
> 延迟会随 embedding 网络/缓存波动（旧一轮为 632.1 / 151.9 / 814.2 ms），不构成矛盾。
> 结论：混合检索没有稳定超过纯向量；简历项目不要写“混合检索显著提升”。真实结论是：BM25 更快、纯向量更准，hybrid 作为可调策略保留。

### 4.3 切块消融（R01–R08）

| 切块大小 | PDF/DOCX chunk 数 | evidence_all@3 | MRR |
| ---: | :--- | ---: | ---: |
| 300 字 | 9 / 11 | 75.00% | 0.6875 |
| 500 字 | 7 / 9 | **75.00%** | **0.6875** |
| 800 字 | 5 / 8 | 75.00% | 0.5417 |

线上采用 500/50。注意样本只有 8 条，结论是“方向性”，不是统计显著。

### 4.4 E2E

- 模拟面试 grounding：**10/10**；
- Agent 模式（10 条 SRE 问题，通用 smoke，不是求职域主评测）：**9/10** 通过（keyword_ratio ≥75% + 非开头拒答 + citations 非空 + 无 tool_error）；A04 Redis Cluster 自动转移因 KB 覆盖不足被模型正确拒答；
- 上传 → 解析 → 向量化 → 提问 → 引用：**PASS**；
- 后端：**128 passed**（新增 36 条 golden/标准指标/tracing/Langfuse/prompt/安全/匹配封顶测试）；
- 前端：`npm run build` 通过（约 9.4s）。

### 4.5 延迟

- 单条 TTFT：hybrid 无 rerank 2.99s；hybrid + BGE-reranker 3.70s；
- 这是**单条样本**，不是 P95，不要写成生产延迟。

---

## 5. 测试与质量

- 25 个测试文件，128 条测试；
- 覆盖：auth/隔离、KB/owner、admin、trace、Agent workflow、工具治理、检索/rerank/缓存、BM25、记忆、prompt、golden eval、chat SSE；
- 前端构建通过；
- 未覆盖/薄弱：
  - 真实 LLM 的稳定回归（多数测试 mock/局部）；
  - 并发/压测；
  - Langfuse/trace 外部后端（未接）；
  - 浏览器 E2E（只有脚本级 HTTP E2E）；
  - CI（没有 GitHub Actions）。

---

### 5.1 安全与就绪（2026-10-20）

- **CORS**：改为 `CORS_ORIGINS` 白名单（默认 `127.0.0.1/localhost:3000` 和 `:5173`），不再 `allow_origins=["*"]`；未知 Origin 的 preflight 返回 400；
- **全局异常**：不再把 `str(exc)` 返回给客户端，只返回通用错误 + `request_id`；完整 traceback 写日志；
- **请求 ID**：中间件生成/透传 `X-Request-Id`，响应头返回；
- **API Key scope**：新增 `require_route_scope`，按路由前缀/方法强制：
  - KB/files/chunks：`kb:read` / `kb:write`
  - chat：`chat:read`
  - career：`career:read` / `career:write`
  - benchmark：`eval:run`
  - settings 写入：`admin:*`
  - `<prefix>:write` 隐含 `<prefix>:read`；`admin:*` 拥有全部权限
- **/ready**：检查 PostgreSQL / Redis / LLM；PG/Redis 是硬依赖，LLM 默认只标记 `degraded`（`READY_REQUIRE_LLM=false`）；
- **实测**：`chat:read` key 访问 KB list → 403；`kb:read` key → 200；`/ready` 返回 `postgres/redis/llm=ok`；CORS 未知 Origin → 400；
- **CI**：`.github/workflows/ci.yml`，后端用 pgvector + Redis service 跑 pytest，前端跑 `npm ci && npm run build`；
- **Docker**：`docker-compose.yml` + `backend/Dockerfile` + `frontend/Dockerfile`，见 §6.7；
- 测试：**128 passed**。

## 6. 运行手册

### 6.1 环境事实

| 项 | 值 |
| :--- | :--- |
| Python | 3.14.4，依赖装在用户目录，不用 venv |
| PostgreSQL | 18.6，库 `agent_db`，pgvector 已装 |
| Redis | 6379，`PONG` |
| Node | 24.21.0 |
| 后端 | `http://127.0.0.1:8000` |
| 前端 | `http://127.0.0.1:3000` |
| 观测后台 | `http://127.0.0.1:3001`（独立 `admin-frontend/`），`admin` / `Admin@123456`（本地开发，生产必须改） |
| 测试账号 | `2023001` / `Test@123456`（本地） |
| JWT secret | `/tmp/lnu_dev_jwt_secret`（本地；不要提交） |

### 6.2 启动/停止

```bash
cd /home/yang/Agentic-Multimodal-RAG
bash scripts/dev.sh          # 后端 8000 + 前端 3000；Ctrl+C 停止
bash scripts/stop.sh         # 兜底停止
bash scripts/doctor.sh       # 依赖/PG/Redis/模型 Key/端口体检
```

日志：`.logs/backend.log`、`.logs/frontend.log`。

### 6.3 测试/构建

```bash
cd backend
JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)" python3 -m pytest tests -q
cd ../frontend && npm run build
```

### 6.4 评测

```bash
cd backend
# 42 条真实简历 golden（92.31% 那组数字）
python3 benchmark/eval_personal_kb.py \
  --kb-id kb_real_resumes \
  --golden benchmark/real_resumes_golden.json
# 38 条个人材料 golden（默认，不要和 42 条混用）
python3 benchmark/eval_personal_kb.py
python3 benchmark/interview_grounding_eval.py  # 10 条 grounded 面试
python3 benchmark/agent_eval.py                # 10 条 Agent
python3 ../scripts/e2e_upload_ask.py           # 上传->提问->引用
```

### 6.5 数据库迁移（Alembic）

```bash
cd /home/yang/Agentic-Multimodal-RAG/backend
# 应用所有 migration（现有 agent_db 已 stamp 到 baseline，不会重复建表）
JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)" alembic upgrade head
# 新增/修改表后生成迁移
JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)" alembic revision --autogenerate -m "add xxx"
# 查看当前版本
JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)" alembic current
```

- baseline revision：`alembic/versions/afbfd34f4028_baseline_schema.py`，包含 pgvector 扩展、全部表和 HNSW 索引；
- 现有库已执行 `alembic stamp head`；
- `AUTO_MIGRATE=true` 时后端启动会自动 `upgrade head`；生产多实例建议设为 `false`，由发布流程单独跑 migration；
- SQLite 测试库仍由 `SQLModel.metadata.create_all` 创建，因为 baseline 使用 pgvector 类型。

### 6.6 数据脚本

```bash
python3 scripts/seed_admin.py
python3 scripts/seed_demo_users.py
python3 scripts/sync_pgvector.py
python3 scripts/ingest_real_resumes.py
```

### 6.7 Docker Compose

```bash
cd /home/yang/Agentic-Multimodal-RAG
export JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)"
docker compose build
docker compose up -d
curl http://127.0.0.1:8000/ready
```

- 组成：pgvector + Redis + backend（Alembic 自动迁移）+ frontend（Nginx 反代 `/api/`，SSE 关闭 buffering）；
- 详情见 `docs/DOCKER.md`；
- 本地 Ollama 需要把 `LLM_BASE_URL` / `EMBEDDING_BASE_URL` 改成 `http://host.docker.internal:11434/v1`。

### 6.8 注意

- `.env` 含真实模型 Key，不要提交；
- `backend/storage/uploads/` 有真实简历，不要 `git clean`；
- Celery 已配置但 `dev.sh` 不启动 worker；解析/向量化有同步兜底，不要假设后台任务一定异步；
- 新增表靠 SQLModel `create_all`；改已有表要手写 `ALTER`。

---

## 7. 代码地图

```text
backend/app/
  api/            auth, chat, career, knowledge_base, files, chunks, admin, benchmark
  core/           config, database, deps, access, security, metrics, rate_limiter
  models/         SQLModel 表
  services/
    retrieval.py  pgvector + BM25 + 融合 + rerank + cache
    vector_store.py
    agent_workflow.py  LangGraph 单工具 Agent
    chat.py       SSE 编排
    mock_interview.py  基于简历 chunk 的出题
    system_prompt_service.py  全局提示词版本
    prompt_service.py  用户级提示词覆盖
    trace_service.py 本地 Agent trace
    tools/governance.py  工具治理
  tasks/          Celery（可选）
frontend/src/
  pages/Admin/    六个 admin tab
  pages/Career/   求职中心/面试
  services/       API client
backend/benchmark/ 42 golden / 切块 / grounding / agent / 上传 E2E
docs/               PRD, ADMIN_PLATFORM, INTERVIEW_QA, 本报告
```

---

## 8. 尚未完成 / 风险

### 8.1 P0（接手优先）

1. **Langfuse 已做云端验收**：trace、求职域 `career_demo_v1` dataset、`career_quality_baseline` experiment（match/score/fraud/star 四项均 1.0）、5 个 Agent prompt 的 Prompt Management（v1 production）均已跑通；`agent_sre_v1` 10 条仅作通用 smoke。无 key 时自动 no-op。仍缺 42 条简历/10 条 grounding 的 PII 上传方案，以及 `mock_interviewer` / `resume_doctor` 的 prompt 迁移。
2. **提示词管理自研重复**：`system_prompts` 版本/草稿/发布/回滚 + `prompt_service` 用户覆盖，和 Langfuse Prompt Management 重叠。
3. **评测自研重复**：42/10/10 的脚本和 JSON/报告，没有数据集版本、实验对比、人工标注；Langfuse Datasets/Experiments 可直接承接。
4. ~~API Key scope 未全链路强制~~ **已修复（2026-10-20）**：`require_route_scope` 按路由前缀/方法强制 `kb:read`、`kb:write`、`chat:read`、`career:read/write`、`eval:run`、`admin:*`；`<prefix>:write` 隐含 `<prefix>:read`。
5. **PII 已处理（2026-10-20）**：tracked 文件中已无真实姓名/文件名/手机号/邮箱；`personal_kb_golden.json` 使用 `resume.pdf` / `resume.docx` 别名，真实文件名只在本机 ignored 的 `personal_kb_files.local.json`；`interview_grounding_eval.py`、`chunking_eval.py`、`scripts/*` 改用环境变量；`real_resumes_*` 与 `data/真实简历/` 继续 gitignore。Langfuse Cloud 只上传求职域合成简历（`career_demo_v1`）和 SRE smoke。本地 trace 仍存 query/answer 预览，接 Cloud 时用 `TRACE_CONTENT_MODE=metadata/redacted`。

### 8.2 P1

- CI（GitHub Actions）、Docker/Compose、Grafana/告警、Locust 压测；
- 浏览器 E2E（Playwright）；
- 更多 agent eval（当前 10 条）；
- token/cost 采集（当前没有）；
- 文件状态 `parsed` 与 `ready` 语义统一；
- ~~API Key scope 逐路由校验~~ **已完成（2026-10-20）**。

### 8.3 明确不要做

- 不要继续扩自研 trace/eval/prompt **UI**；
- 不要为了“简历好看”接一个假 Langfuse；
- 不要给这个项目加多 Agent/Checkpoint/HITL/MCP（省心购/中科院项目讲）；
- 不要做 GraphRAG；
- 不要把 hybrid 写成“显著优于 vector”（数据不支持）。

---

## 9. Langfuse 取舍：你说得对，应该用现成的

### 9.1 结论

**停止自研观测/评测/提示词平台，接 Langfuse。**

但要分清“Langfuse 能替什么”和“不能替什么”。

### 9.2 能力映射

| 当前自研 | Langfuse 对应 | 处理 |
| :--- | :--- | :--- |
| `agent_traces` + Admin trace 表 | Tracing（LLM/retrieval/tool span、session、latency） | **替换**；本地表保留 1–2 周做 fallback |
| `request_logs` + Prometheus | Langfuse 看板 + Prometheus/Grafana | Prometheus 保留做基础设施指标；LLM 维度用 Langfuse |
| 系统提示词版本/草稿/发布/回滚 | Prompt Management（version/label/playground） | **迁移**；app 保留 cache/fallback/用户覆盖 |
| 42 golden / 10 grounding / 10 agent 脚本 | Datasets + Experiments + Scores | **迁移数据集与结果**；检索 Hit@K/MRR 仍需自定义 evaluator |
| JSON 报告/前端表格 | Langfuse Experiments/Annotation | 不再自研评测 UI |
| 人工 bad case 标注 | Annotation Queues | 用 Langfuse |

### 9.3 Langfuse 不能替的

- 用户/角色/API Key/模型/KB 权限：**保留自研 Admin**；
- 向量库/检索/切块：**保留**；
- Prompt 的运行时缓存、fallback、用户级覆盖：**app 侧保留**；
- RAG 的 Hit@K、MRR、citation correctness：Langfuse 不原生算，仍需你写 evaluator 函数（但 dataset/experiment/score 由 Langfuse 管）。

### 9.4 推荐落地顺序

1. **部署 Langfuse**：优先自托管（简历 PII）；或 cloud + 发送前脱敏/伪名化。版本 pin，备份 Postgres/ClickHouse。
2. **接 tracing**：SDK/OTel callback；沿用现有 `trace_id`；加 retrieval/rerank/LLM/tool/grading span；metadata：user_id（伪名）、kb_ids、model、prompt label/version、tokens、cost、latency。
3. **迁 prompt**：在 Langfuse 建 `mock_interviewer`、`resume_doctor` 等，打 `production`/`staging` label；app 启动拉取 + TTL cache + 失败 fallback；先双写，后关自研 UI。
4. **迁 datasets/evals**：42 golden + 10 grounding + 10 agent 上传为 dataset；把现有 evaluator 注册/调用；每次实验在 Langfuse 出 score，链接 trace。
5. **清理**：停写 `agent_traces`（或保留 fallback 开关）；下线自研 prompt/eval UI；保留 Admin 业务控制面。

### 9.5 验收

- 一次聊天能在 Langfuse 看到完整 trace（retrieval → rerank → LLM → tool → answer）；
- `production` prompt 改 label 后，app 不重启生效，失败有 fallback；
- 42 条 golden 在 Langfuse 跑出与现有报告可对齐的 Hit@3/MRR；
- 10 条 grounding/agent 有 score 与 trace 关联；
- PII 脱敏用例通过；
- 不再双写两套 trace。

### 9.6 风险

- Langfuse 自托管组件多（Postgres/ClickHouse/Redis/S3），运维成本高；
- Python 3.14 / LangGraph 兼容性要先做 spike；
- prompt 远程拉取失败必须 fallback，不能阻塞对话；
- 简历 PII 不能裸送 SaaS；
- 版本/标签漂移：必须记录 prompt version 到 trace。

> **兼容性 spike 结果（2026-10-19）**：临时 venv（Python 3.14）安装 `langfuse==5.0.2` 成功，安装 `langchain-core>=1` 后 `from langfuse.langchain import CallbackHandler` 可正常导入。项目环境也已安装并导入成功；若后续依赖冲突，可退回 OpenTelemetry OTLP exporter。

### 9.7 当前实现状态（2026-10-19）

已接入（代码层）：

- `app/core/tracing.py`：Langfuse 惰性单例、失败降级、PII mask、trace/observation 封装；
- `api/chat.py`：每次聊天一个 root trace，`done` 事件返回 `langfuse_trace_id`；
- `agent_workflow`：LangChain `CallbackHandler` 绑定 trace，覆盖意图/agent/grading/answer 的 LLM 调用；
- `tools/governance.py`：`tool.search_knowledge_base` span；
- `services/retrieval.py`：`retrieval.search` retriever span；
- `services/chat.py`：`rerank` span；
- `services/llm.py`：普通模式的 `llm.generate_stream` / `llm.generate` generation span；
- `main.py`：应用关闭时 flush。

配置（`backend/.env`，不要把 key 提交）：

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
TRACE_CONTENT_MODE=redacted   # metadata | redacted | full
```

验收前状态：没有 key 时 `tracer.enabled=false`，所有 span 为 no-op，聊天和 128 条测试照常通过；本地 `agent_traces` 继续写。

**Datasets / Experiments（2026-10-19，Cloud Hobby）**

- **求职域主数据集** `career_demo_v1`：5 条合成简历/JD（假姓名/假联系方式），覆盖简历×JD 匹配、跨领域低匹配、岗位反欺诈；
- **求职域 Experiment** `career_quality_baseline`：
  - `match_level_ok` / `score_range_ok` / `fraud_label_ok` / `has_star_rewrite` 均为 **1.000**；
  - Experiment URL：`https://cloud.langfuse.com/project/cmvffar6c0cqxad0jocxy3h59/experiments/results?baseline=40a3377b1057c7f8`；
- 通用 smoke `agent_sre_v1`：10 条 SRE 用例，`passed=9/10 / keyword_ratio=0.925 / citation=1.0 / no_tool_error=1.0`；A04 因 KB 覆盖不足正确拒答，不作为求职域主评测；
- 修复：`career_matcher` 在硬技能覆盖率 <34% 时封顶 LOW，避免跨领域简历被学历/项目泛化分抬到 MODERATE。
- 复算命令：
  ```bash
  cd backend
  JWT_SECRET=... python3 benchmark/langfuse_agent_dataset.py --run-experiment --limit 2
  # 全量 10 条
  JWT_SECRET=... python3 benchmark/langfuse_agent_dataset.py --run-experiment
  ```
- **未上传**：42 条真实简历、10 条 grounding。原因是 Cloud 免费版仍属外部服务，这些数据含 PII；要上传必须先伪名化，或改用自托管。
- 已知限制：Experiment 的 task 通过 HTTP 调后端，因此 Experiment 的 trace 只包含 task span；后端真实 trace 通过输出里的 `langfuse_trace_id` 关联，暂未自动 merge。

**Prompt Management（2026-10-19）**

- 已上传 5 个 Agent prompt 到 Langfuse：`agent.intent` / `agent.system` / `agent.grading` / `agent.answer` / `agent.chat`，均为 **v1 + production label**；
- 新增 `app/services/prompt_registry.py`：production label 拉取 + 300s 缓存 + 2s 超时 + 代码默认值 fallback；
- 已移除 `agent_workflow.py` 里的硬编码 prompt；每次 LLM 调用的 trace metadata 记录 `prompt_key` / `prompt_version` / `prompt_label` / `prompt_source`；
- 实测 trace `f7ad1a15...`：`agent.intent`、`agent.system`、`agent.grading`、`agent.answer` 均为 `version=1`、`label=production`、`source=langfuse`；
- 改 production label 后，最多 300s（缓存 TTL）生效；Langfuse 不可用时回退代码默认值，不阻塞对话；
- 尚未迁移：`mock_interviewer` / `resume_doctor` 等 `prompt_service` 模板，以及 Admin 自研 Prompt UI 的下线。

---

## 10. 交接计划（给接手人）

### 第 1 周：Langfuse tracing

- 已选 **Cloud Hobby（免费：50k units/月、2 users、30 天数据访问）**；
- 在 Langfuse Cloud 建项目，把 public/secret key 填进 `backend/.env`；
- 先用 SRE 非 PII 知识库跑一次 Agent 问答和一次普通问答；
- 保留 `agent_traces` fallback；
- 验收：Langfuse 能看到 `retrieval → tool → LLM → answer` 的完整 trace，`done` 事件里的 `langfuse_trace_id` 可查；
- PII：真实简历轨迹先设 `TRACE_CONTENT_MODE=metadata/redacted`，或改用自托管。

### 第 2 周：Prompt Management

- ✅ Agent prompt 已迁移：`agent.intent/system/grading/answer/chat`，v1 + production label；
- 待迁移 `mock_interviewer` / `resume_doctor` 等 `prompt_service` 模板；
- `production`/`staging` label；
- app 拉取 + cache + fallback；
- 验收：改 label 不重启生效；失败回退。

### 第 3 周：Datasets / Evals

- 上传 42 golden、10 grounding、10 agent；
- 注册 Hit@K/MRR/citation/task-success evaluator；
- 跑 experiment，和现有报告对齐；
- 验收：Langfuse 报告可复算。

### 第 4 周：清理与补强

- 下线自研 prompt/eval UI（Admin 保留业务）；
- 停双写；
- 补 PII 脱敏测试、CI；API Key scope 已完成；
- 验收：全部测试仍全绿；前端构建通过；无重复 trace。

### 接手第一天

```bash
cd /home/yang/Agentic-Multimodal-RAG
git status                 # 应为 clean
bash scripts/doctor.sh
cd backend && JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)" python3 -m pytest tests -q
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready   # PG / Redis / LLM 依赖状态
```

不要先重构；先跑通、再按第 1 周接 Langfuse。

---

## 11. 需要拍板的问题

1. Langfuse 自托管还是 cloud？简历 PII 是否允许出域？
2. 是否保留自研 `system_prompts` 作为 fallback，还是 Langfuse 唯一源？
3. 评测的 Hit@K/MRR 是否继续用本地脚本，只把结果写 Langfuse？建议是。
4. API Key scope 是否这轮一起做？
5. 是否要把 `docs/HANDOFF.md` 归档，避免接手人误读？

---

## 12. 报告依据

```bash
git log --oneline -8
git status --short
python3 -m pytest tests -q          # 128 passed
npm run build                       # 通过
curl http://127.0.0.1:8000/health    # {"status":"ok"}
curl http://127.0.0.1:8000/ready     # {"status":"ok","checks":{...}}
psql ...                           # 3 users / 8 KB / 23 files / 330 chunks / 330 embeddings / 2 traces
```

真实评测文件：

- `backend/benchmark/report.md`
- `backend/benchmark/real_resumes_eval.json`（42 条真实简历 golden 的结果）
- `backend/benchmark/personal_kb_eval.json`（38 条个人材料 golden，和 42 条不是同一套）
- `backend/benchmark/interview_grounding_eval.json`
- `backend/benchmark/agent_eval.json`

---

## 13. 最终判断

**项目主体是完整的，但“可观测/评测/提示词平台”走错了方向：这些应该用 Langfuse，而不是继续自研。**

接手人最重要的三件事：

1. 接 Langfuse tracing；
2. 把 prompt 和 datasets/evals 迁过去；
3. 保留自研 Admin 做业务权限，不再扩自研观测 UI。
