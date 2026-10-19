# 后台系统 / 可观测性 / AB 评测方案

> 目标：把“能演示”变成“能运营、能定位、能迭代”。
> 前提：不把 Dify/FastGPT 这类完整应用平台硬塞进来，也不单独再起一个 admin 后端。

---

## 0. 先说结论

你需要的是三层，不是一个大后台：

| 层 | 作用 | 推荐 |
| :--- | :--- | :--- |
| **控制面** | 账号、角色、API Key、模型、系统提示词、实验配置 | 在现有 FastAPI 加 `/api/v1/admin`，React 加 `/admin` 页面 |
| **LLM 观测/评测** | trace、prompt/response、token/成本、数据集、eval、bad case | **Phoenix 自托管**（轻）或 **Langfuse 自托管**（全）；LangSmith 是 SaaS |
| **运维指标** | QPS、P95、错误率、饱和度、告警 | Prometheus + Grafana；Locust 只做压测 |

**没有一个开源项目能同时把这三层 + 你的业务语义（简历、KB owner、岗位 JD）全包。**
Dify/FastGPT/RAGFlow 是“另一个产品”，不是后台；Langfuse/LangSmith 是观测/评测，不是账号/API/模型管理后台。

---

## 0.1 当前实现状态（2026-10-19）

**P0 控制面已经落地：**

- 账号：`admin` / `Admin@123456`（本地开发账号；生产必须改密码）；
- 前端：`/admin`（仅 admin 侧边栏可见，`RequireAdmin` 路由守卫）；
- 后端：`/api/v1/admin/*`，全部要求 admin；API Key 访问 admin 还要求 `admin:*` scope；
- 用户：列表、新增、角色/状态修改、重置临时密码、最后 admin 保护；
- 密码：`POST /api/v1/auth/change-password`（旧密码校验，新密码 bcrypt）；
- API Key：创建（明文只返回一次）、列表、吊销、SHA-256 hash 存储、`last_used_at`、过期时间；
- 模型：列表（Key 掩码）、新增/编辑/删除、连接测试（LLM/embedding/rerank）；
- 系统提示词：版本化、草稿、发布/归档、回滚；优先级 `用户覆盖 > 全局 active > 代码默认`；
- 审计：`audit_logs`，记录用户/Key/模型/提示词写操作；
- 建表/账号脚本：`scripts/seed_admin.py`；
- 测试：`backend/tests/test_admin_api.py` + `test_admin_traces.py`，全量 **92 passed**（2026-10-19）。

**P1-lite 观测已落地：**

- `GET /metrics`：Prometheus 文本指标（HTTP 请求数/耗时、检索阶段耗时）；
- `request_logs`：方法/路径/状态/耗时/user_id/client_ip，不含 query/response 正文；
- `/admin` → “观测”标签：请求总数、错误率、平均耗时、最近请求；
- 请求日志可在测试环境用 `REQUEST_LOG_ENABLED=false` 关闭。

**P1-lite 本地 Agent trace 已落地：**

- `agent_traces`：`trace_id`、user/session、mode、query、answer_preview、citations、steps、tool_calls、TTFT、total_ms、error；
- `/api/v1/chat/completions` 响应头带 `X-Trace-Id`，`done` 事件带 `trace_id`；
- Admin `GET /admin/traces`、`GET /admin/traces/{trace_id}`，前端“观测”页可看最近 trace；
- 仅 admin 可查；query/answer 只存预览，避免把完整简历正文复制进日志。

**尚未实现（P1 完整版/P2，不要对外说已完成）：**

- Langfuse/Phoenix 外部 trace、bad case 工作台；本地 trace 不是 Langfuse；
- Grafana 看板/告警；
- Locust 压测；
- 线上 A/B 实验与 assignment；
- 工具只读沙箱/链路回放；
- 非 admin 路由的细粒度 scope 强制。

**API Key scope 现状：**

- `admin:*` 已对 `/admin/*` 强制校验；
- `chat:read` / `kb:read` / `eval:run` 目前只是记录在 Key 上，**尚未按业务路由逐条强制**；不要说“scope 已全链路生效”。

---

## 1. 当前项目已经有什么

- `users` 表、JWT access/refresh、`get_current_user`；
- `custom_models` 表 + `/settings/models` API（模型 CRUD/激活），但 Settings 页面已从前端路由移除；
- 每用户提示词工坊 `PromptService`（Redis `u:{uid}:prompts`），没有全局系统提示词版本；
- `retrieval_logs`（召回日志）、`agent_steps` SSE、42 条真实简历 golden、`eval_personal_kb.py`；
- 没有 `admin` 角色、没有 API Key、没有实验表、没有 trace_id、没有 `/metrics`、没有 eval run 历史。

所以后台不是从零开始，但缺的是**控制面 + 观测面**，不是再写一个聊天页。

---

## 2. 控制面：必须自己写，但可以很薄

### 2.1 账号/密码/角色

复用 `users`，增加：

- `role`: `student | admin`（已有 `role` 字段，补 RBAC 依赖 `require_admin`）；
- `status`: `active | disabled`；
- `password_changed_at`、`last_login_at`；
- `audit_logs`：谁在什么时候改了谁、改了什么。

管理能力：

- 列表/搜索/禁用/启用；
- 重置密码（管理员触发一次性临时密码，强制下次修改）；
- 不显示密码哈希；
- 不能删除最后一个 admin。

### 2.2 API Key 管理

新增 `api_keys`：

```text
id, owner_id, name, key_prefix, key_hash, scopes, last_used_at,
expires_at, revoked_at, created_by, created_at
```

- 只在创建时返回一次明文 `sk-...`，DB 存 hash；
- scope：`chat:read`、`kb:read`、`eval:run`、`admin:*`；
- 管理端可吊销、看 last_used、设过期；
- 外部调用走 `Authorization: Bearer sk-...`，与 JWT 二选一。

### 2.3 模型管理

复用 `custom_models`，但补：

- 管理端 CRUD、测试连接、设为默认；
- API Key 加密/掩码，不回传明文；
- 模型类型：llm/vlm/embedding/rerank；
- 预算/限流（可选）：按用户/模型记录 token 与成本；
- 多模型路由（可选）：主模型失败切备用；不要在没有第二把 Key 时假装 A/B。

### 2.4 系统提示词管理（区别于用户提示词工坊）

新增 `system_prompts`：

```text
id, key, version, content, status(draft|active|archived),
experiment_id, created_by, created_at, published_at
```

- `key` 例如 `mock_interviewer`、`resume_doctor`、`star_rewriter`；
- 版本化、发布/回滚、diff；
- 全局 active 版本 + 实验 variant；
- 用户级 `PromptService` 覆盖仍然保留，但优先级：用户覆盖 > 实验 variant > 全局 active > 代码默认；
- 管理端能看到“当前生效版本”和“谁覆盖了”。

### 2.5 实验/A-B

新增：

```text
experiments(id, key, name, status, metric, started_at, ended_at)
experiment_variants(id, experiment_id, name, config_json, weight)
experiment_assignments(id, experiment_id, user_id, variant, assigned_at)
```

- 按 `hash(user_id + experiment_key)` 确定性分流，避免同一用户来回跳；
- 先做**离线 A/B**：同一批 golden 跑 A/B，比较 retrieval/answer/citation；
- 线上 A/B 需要流量和样本量；没有流量就不要写“提升 30%”；
- 指标必须预先定义：任务成功率、citation 支持率、P95、token/成本、bad case 率。

---

## 3. 观测面：用现成的，不要自己写 trace UI

### 3.1 LLM trace / eval：Phoenix 或 Langfuse

| 方案 | 形态 | 优点 | 代价 |
| :--- | :--- | :--- | :--- |
| **Arize Phoenix** | 开源自托管，OpenTelemetry | 轻、适合本地/单机；trace + eval | 生态/看板不如 Langfuse 全 |
| **Langfuse** | 开源自托管（Postgres/ClickHouse/Redis/S3） | trace、prompt 管理、dataset、eval、看板全 | 自托管组件多，运维重 |
| **LangSmith** | SaaS 为主 | 和 LangChain/LangGraph 集成最顺 | 简历 PII 出域，需脱敏/合规 |

建议：

- 学生项目/单机演示：先 **Phoenix**；
- 想要“prompt 管理 + dataset + eval + 看板”一体化、且能跑 Docker：**Langfuse**；
- 不把原始简历/手机号/邮箱送 SaaS；要送先脱敏。

接入方式：

- FastAPI + LangGraph + OpenAI SDK 加 OpenTelemetry/Langfuse callback；
- 每次请求生成 `trace_id`，把 `user_id`、`kb_ids`、`prompt_version`、`model`、`retrieval_chunk_ids`、`tool_calls`、`latency`、`tokens`、`cost` 挂到 trace；
- 前端错误提示带 `trace_id`，用户报障可定位。

### 3.2 运维指标：Prometheus + Grafana

- FastAPI 加 `prometheus-fastapi-instrumentator` 或 `prometheus_client`，暴露 `/metrics`；
- 指标：
  - `http_request_duration_seconds`（P50/P95/P99）
  - `llm_ttft_seconds`、`llm_tokens_total`、`llm_cost_total`
  - `retrieval_duration_seconds{stage="embedding|sql|bm25|rerank"}`
  - `retrieval_hit_total`、`citation_count`
  - `agent_retry_total`、`tool_call_total{name,status}`
- Grafana 看板 + 告警（错误率、P95、429、成本）；
- Prometheus 不负责 prompt/response 和 bad case，它只看数值指标。

### 3.3 压测：Locust

- Locust 是**压测工具**，不是线上监控、不是链路回放；
- 用 staging 环境，对 `/chat`、`/recall`、`/interview/chat` 做 10/50/100 并发；
- 记录 P95、错误率、限流触发、下游模型 429；
- 不要把 Locust 结果写成“线上 QPS”。

---

## 4. 链路回放：先做“可检查”，不要承诺“可复现”

LLM 有随机性，工具可能有副作用，所以“完全回放”不现实。可做的是：

1. **Trace inspection**：能看到当时用的 prompt 版本、模型、参数、检索 chunk、工具调用、输出；
2. **Retrieval replay**：用同样的 query + KB + 参数重跑检索，验证是不是召回问题；
3. **Prompt replay**：同模型同参数重跑生成，结果可能不同，但可看差异；
4. **Tool replay**：工具调用必须进沙箱/只读模式，不能重放退款、发消息、写库；
5. **Bad case 回流**：把失败 trace 标成 `retrieval_miss / generation_hallucination / tool_error / permission`，补进 golden，回归。

需要的字段（`request_traces` 或 Langfuse trace metadata）：

```text
trace_id, user_id, endpoint, query, rewritten_query,
kb_ids, prompt_key, prompt_version, model, temperature, top_k,
retrieved_chunk_ids, rerank_scores, citations,
tool_calls, tool_results, ttft_ms, total_ms, tokens, cost, error, created_at
```

---

## 5. 后端 API 草案

统一前缀 `/api/v1/admin`，`require_admin`：

```text
GET/PATCH  /admin/users
POST       /admin/users/{id}/reset-password
GET/POST   /admin/api-keys
DELETE     /admin/api-keys/{id}

GET/POST   /admin/models
PATCH      /admin/models/{id}
POST       /admin/models/{id}/test

GET/POST   /admin/prompts
POST       /admin/prompts/{key}/publish
POST       /admin/prompts/{key}/rollback
GET        /admin/prompts/{key}/diff

GET/POST   /admin/experiments
PATCH      /admin/experiments/{id}
GET        /admin/experiments/{id}/metrics

GET        /admin/evals/runs
POST       /admin/evals/run
GET        /admin/evals/runs/{id}

GET        /admin/traces
GET        /admin/traces/{trace_id}
GET        /admin/bad-cases
PATCH      /admin/bad-cases/{id}
```

所有写操作进 `audit_logs`；所有列表分页；所有响应不返回密钥/密码哈希。

---

## 6. 前端后台

- 不拉 Dify/FastGPT；它们会替换你的产品；
- 在现有 React 里加 `/admin` 布局：
  - 账号、API Key、模型、系统提示词、实验、评测、trace、bad case；
- 如果只想快速 CRUD，可以用 Retool/Appsmith/Metabase 连 PostgreSQL；
  - 但账号/密钥/提示词发布这类操作建议留在自有后端做 RBAC 和审计，不要直接把 DB 暴露给低代码平台。

---

## 7. 推荐实施顺序

```text
P0  控制面最小闭环（2-3 天）
    admin 角色 + users/api_keys/models/system_prompts + audit_logs
    React /admin 基础页

P1  LLM 观测 + 离线评测（1-2 天）
    trace_id + Phoenix（或 Langfuse）
    42 条 golden 的 eval run 历史、bad case 列表

P2  运维指标 + 压测（1 天）
    Prometheus /metrics + Grafana
    Locust staging 10/50/100 并发

P3  A/B + 线上实验（有流量再做）
    experiments/assignments + 预定义指标
    没有样本量不写“提升百分比”

P4  回放沙箱（最后）
    只读工具 + 同参数检索回放 + trace diff
```

**不建议**：

- 不要单独起 admin 后端服务；
- 不要一上来拉 Langfuse 全家桶 + ClickHouse；
- 不要把 A/B、Prometheus、Locust 混成一个东西；
- 不要在没有流量时编“线上提升”。

---

## 8. 面试时怎么讲

> “后台分控制面和观测面。控制面是我们自己写的 `/admin`，管账号、API Key、模型和系统提示词版本；观测面用 Phoenix/Langfuse 做 trace 和 eval，用 Prometheus/Grafana 做指标，Locust 只做压测。Langfuse 不是账号后台，Prometheus 也不是链路回放，它们解决的是不同层的问题。”

这比“我接了一个 Langfuse”更能说明你理解系统边界。
