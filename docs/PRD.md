# LNUCareer-Agent 完整 PRD（v4.0 · 终版）

| 项 | 内容 |
| :--- | :--- |
| 产品名 | **LNUCareer-Agent** — 辽宁大学在校生求职辅助 Agent |
| 文档状态 | **终版，唯一实施基线**（v1 / v2.0 / v3 已归档至 `docs/archive/`） |
| 技术基线 | Python 3.14 / FastAPI / SQLModel / LangGraph / Chroma / PostgreSQL 16 / Redis 7 / React + Vite |
| 验证环境 | WSL2 Ubuntu，实测启动通过（见第 0 章，含命令与输出） |
| 定位一句话 | **让每条建议可回溯、每个分数有证据、每次面试可复现。** |

> 本文档与前三版的区别：**第 0 章是实测，不是设计**。所有"能做/不能做"的判断都基于实际启动结果，而非推测。

---

## 0. 现状核实：这台机器上到底跑着什么

### 0.1 实测启动记录（2026-10-18，本机）

| # | 检查项 | 命令 | 实测结果 |
| :--- | :--- | :--- | :--- |
| 1 | Python 版本 | `python3 -VV` | 3.14.4 |
| 2 | 依赖完整性 | import fastapi/sqlmodel/langgraph/chromadb/fitz/docx/pandas/redis/celery | **全部 OK**（`jose` 缺失） |
| 3 | 后端启动 | `uvicorn app.main:app --port 8123` | 启动成功 |
| 4 | 接口连通 | `GET /docs`、`/api/v1/career/prompts`、`/api/v1/knowledge-bases` | 200 / 200 / 200 |
| 5 | 前端启动 | `npx vite --port 3000` | 291ms ready，`GET /` → 200 |
| 6 | **真实 LLM 链路** | `POST /api/v1/career/match` | **200，5.32s**，返回匹配分 67 + 五维雷达 + 缺口 |
| 7 | 单元测试 | `pytest tests/test_database.py test_bm25_index.py test_memory_service.py test_prompt_engineering.py -q` | **13 passed** |
| 8 | PostgreSQL | `psql -c '\dt'` | 8 张表；知识库 4 / 文件 4 / 切片 55 |
| 9 | Redis | `redis-cli ping` | PONG |
| 10 | LLM Key | `GET https://api.deepseek.com/v1/models` | 200（deepseek-chat 可用） |
| 11 | Embedding Key | `GET https://api.siliconflow.cn/v1/models` | 200（BGE-M3 可用） |
| 12 | 前端依赖 | `du -sh frontend/node_modules` | 292M，已安装 |

**结论：项目是活的、能跑的、能调通真实模型的。** 前面说过"可能跑不起来"，是我看轻了，这里更正。

### 0.2 现状能力清单

| 能力 | 状态 | 证据 |
| :--- | :--- | :--- |
| 多格式解析（PDF/DOCX/XLSX/MD/图片） | ✅ 可用 | parser.py + 4 个真实文件已入库 |
| 结构感知切分 + 父子块 | ✅ 可用 | 55 个 chunk |
| 向量 + BM25 混合检索 + 重排 | ✅ 可用 | retrieval/bm25/rerank + 路由 |
| LangGraph Agent 编排 | ✅ 可用 | agent_workflow.py + 单测 |
| 简历 × JD 匹配诊断（五维雷达） | ✅ 可用 | 实测 200 / 5.3s |
| 三层记忆（Redis） | ⚠️ 半成品 | 有 L1/L2/L3，但只存 Redis、无持久化、无用户隔离 |
| 模拟面试 | ⚠️ 半成品 | 有 4 阶状态机，但**只有 1 个人设**、无发散度 |
| 提示词工坊 | ⚠️ 有隐患 | 进程级全局单例，**跨用户串味** |
| 岗位风控（培训贷等） | ✅ 可用 | job_fraud_detector.py |
| 评测脚本 + 8 份对抗样本 | ⚠️ 半成品 | report.md 数字自相矛盾 |
| **鉴权 / 用户表** | ❌ 没有 | 全仓无 JWT，`default_student` 写死 |
| **业务数据落库** | ❌ 没有 | 无 users/materials/sessions/reports 表 |
| **面试复盘报告** | ❌ 没有 | 无 report 生成与存储 |

### 0.3 必须优先修复的四个缺陷（P0）

1. **无鉴权**：`/api/v1/career/*` 全部裸奔，任何人可调用、可读他人数据。这是"每个用户分开"要求的零实现。
2. **提示词全局单例**：`prompt_service._active_templates` 是进程级字典，A 改提示词会影响 B。
3. **业务数据不落库**：会话、评分、报告只在内存/Redis，重启即失，无法做"趋势对比"。
4. **评测报告不可信**：`backend/benchmark/report.md` 中 Baseline 73.3% 而 Hybrid 33.3%，顺序颠倒，必须重跑。

### 0.4 一键启动（本机已验证）

```bash
# 1) 体检（依赖 / PG / Redis / 模型 Key / 端口）
bash scripts/doctor.sh

# 2) 同时启动后端(8000) + 前端(3000)，日志在 .logs/
bash scripts/dev.sh

# 3) 只跑测试
cd backend && python3 -m pytest -q
```

访问：前端 `http://127.0.0.1:3000`，接口文档 `http://127.0.0.1:8000/docs`。

---

## 1. 产品定位

> **面向辽大在校生的证据驱动型求职 Agent：学生上传自己的真实材料，系统在其上做诊断、面试与复盘，所有结论可回溯，所有评分有证据。**

三个必须能现场演示的能力（答辩的三个"一秒"）：

1. **不编数字**：简历没有压测数据 → 输出 `[请补充真实压测指标]`，不替你造。
2. **会降维追问**：说"没做过" → 状态机降级到基础概念，并把盲区写进记忆，下一场开场就问。
3. **能点回原文**：每条建议带 `doc + page + bbox`，点击跳转高亮。

---

## 2. 问题与差异化

### 2.1 真实痛点

| # | 痛点 | 现有解法为什么不够 |
| :--- | :--- | :--- |
| P1 | 不知道简历在目标岗位前差什么，改完仍同质化 | 通用模型给"建议量化成果"这类泛化建议，对不上你的真实项目 |
| P2 | 没有真实面试压力，练完不知道哪句答得烂 | 同学互练无专业度；付费模拟面试贵且一次性 |
| P3 | 求职信息过载，存在培训贷/刷单/境外诱导 | 通用搜索无法判定"这个 JD 是不是坑" |
| P4 | 材料敏感（简历、实习、成绩），不敢上公有云 | 这是合规硬约束，也是本项目护城河 |
| P5 | 求职是 3–12 个月的长周期，每次都要重讲背景 | 聊天工具没有跨会话的"你" |

### 2.2 通用模型都能做，为什么还要做这个

**模型是发动机，本项目是底盘、刹车、仪表盘。**

| 层 | 通用对话工具 | LNUCareer-Agent |
| :--- | :--- | :--- |
| 动力（推理） | 强，持续变强 | **直接复用，不跟它比** |
| 底盘（隔离 / 记忆 / 材料） | 无 | 自研，可测试 |
| 刹车（拒答 / 事实保真 / 风控 / 注入防护） | 弱且不可配置 | 规则 + 策略层，可评测拦截率 |
| 仪表盘（评测 / 一致性 / 成本） | 无 | golden set + 消融 + 一键报告 |
| 领域资产 | 无 | 辽大 JD / 面经 / 专业映射 / 评分 rubric |

**答辩口径（背下来）**：
> "通用模型解决'能不能写出这段话'，我解决'敢不敢用、信不信、有没有变强'。三件事它不是做得差，是不做：数据不出校、每句话能点回原文、同一模型下我能给出消融和一致性数据。"

### 2.3 任何架构都必须过的"三连测试"

1. 不做它会怎样？（说不出具体故障场景 = 不需要）
2. 更简单的替代是什么？为什么不用？（答不上 = 跟风）
3. 这个数字哪来的？（打不开脚本 = 编的）

---

## 3. 角色与场景

| 角色 | 权限 |
| :--- | :--- |
| 学生（P0） | 仅本人数据：上传、对话、面试、查看报告、管理画像、注销 |
| 就业指导老师（P2） | 学生显式授权后，只读**脱敏报告摘要**，不可看原始材料 |
| 管理员 | 仅元数据与审计日志，不可绕过学生删除 |

**场景 S1 改简历**：上传 2025 版简历 + JD → 匹配分 + 3 处缺口 + 带出处的改写 → 导出 2026 版。
**场景 S2 模拟面试**：选"大厂架构师 / 发散度 1" → 10 轮追问 → 报告（总分 72、技术深度弱、3 条改进）。
**场景 S3 项目复盘**：问"这段实习最容易被追问什么" → 引用实习周报第 2 页 + 5 个高概率追问 + 回答骨架。

---

## 4. 范围

### 4.1 P0（必须做完）

F1 账号与隔离 · F2 材料中心 · F3 解析与切分 · F4 检索与引用 · F5 三层记忆 · F6 双模式对话 · F7 面试引擎 · F8 复盘评分 · F10 评测平台

### 4.2 P1（有余力再做）

F9 工具管理 · 报告 PDF 导出 · 教师只读视图 · 离线模式 · 趋势看板

### 4.3 不做（写死）

投递代投 / 简历包装造假 / 心理诊断 / 全网爬 JD / 多校区 SaaS / 微服务拆分 / K8s。

### 4.4 v2.0 架构裁决（答辩可讲"我做的减法"）

| v2.0 组件 | 裁决 | 理由（一句话） |
| :--- | :--- | :--- |
| Go (Gin) 网关 | 砍 | 只做鉴权限流 = 反向代理，"为什么不用 Nginx"无法回答 |
| Kafka 3 Topic | 砍 | 全校峰值 < 10 QPS，Kafka 只增加两个故障点 |
| 1000 QPS / P99<30ms | 砍 | 业务不存在；只能压到网关，压不到 LLM 链路 |
| 三态熔断体系 | 降级 | 超时 + 重试 1 次 + 降级文案即可 |
| 全链路 Trace 框架 | 降级 | trace_id + 结构化日志足够 |
| 事实保真 / 4 阶追问 / 证据锚点 / 隔离 | **保留** | 差异化本体 |
| L1/L2/L3 三层记忆 | 保留，砍"离线 Dream" | 价值在策略，不在异步 |
| 8 份 Golden 对抗样本 | 保留并扩到 60 条 | 唯一能"证明"的东西 |

---

## 5. 架构

### 5.1 现状（as-is）

```
React(3000) ──axios/SSE──> FastAPI(8000)
                              ├─ agent_workflow.py  (LangGraph)
                              ├─ retrieval + bm25 + rerank
                              ├─ career: match / interview / fraud / prompts
                              ├─ memory_service (Redis)
                              └─ SQLModel ──> PostgreSQL(5432)  [仅 RAG 侧 8 表]
                                          └─> Chroma (storage/chroma_db)
Celery + Redis(6379)  ── 解析/向量化异步任务
外部模型：DeepSeek(LLM) + SiliconFlow(BGE-M3) + Qwen3-VL
```

### 5.2 目标（to-be，只加必要件）

```
React ──> FastAPI ──> [鉴权中间件] ──> 业务层
                         │                 ├─ materials (上传/版本)
                         │                 ├─ interview (状态机)
                         │                 ├─ report (评分/趋势)
                         │                 └─ chat (双模式)
                         ├── PostgreSQL: + users/materials/sessions/turns/scores/reports/profile_items/events/tool_calls/audit_logs
                         ├── Chroma: metadata 强制 owner_id
                         └── Redis: L1 / 限流 / 锁（key 前缀 u:{uid}:）
```

**不加**：第二语言服务、消息队列、服务网格、独立向量库迁移。

### 5.3 分层职责

| 层 | 职责 | 禁止 |
| :--- | :--- | :--- |
| API 层 | 鉴权、参数校验、SSE 分发 | 写裸 SQL、拼检索 |
| 服务层 | 状态机、检索编排、评分、记忆策略 | 直接操作 HTTP |
| 仓储层 | 强制 `owner_id` 过滤 | 暴露无过滤查询 |
| 模型层 | LLM/VLM/Embedding/Rerank 适配 | 业务判断 |

---

## 6. 功能需求

> 每个功能给出：目标 / 输入输出 / 规则 / 异常 / **验收句**（写不出验收句就不做）。

### F1 账号与多租户隔离（P0）

- **目标**：任意两用户之间零数据可见性。
- **输入**：学号 + 密码（或邮箱验证码）；输出：Access(15min) + Refresh(7d) JWT。
- **规则**：
  1. `user_id` **只从 token 取**；Body/Query 中的 `user_id` 一律忽略。
  2. 仓储层统一注入 `WHERE owner_id = ?`。
  3. Chroma 查询强制 `where={"owner_id": uid}`。
  4. Redis key `u:{uid}:...`。
  5. 注销：事务内级联删除 DB / 文件 / 向量 / Redis，60s 内生效。
- **异常**：token 过期 → 401；他人资源 → 404（不泄露存在性）。
- **验收句**：30 条跨用户用例 100% 拒绝；`grep default_user` 为 0；删号扫描残留 0。

### F2 材料中心（P0）

- **四类**：`resume / project / internship / jd`，均支持多版本。
- **上传**：单文件 ≤ 50MB，白名单扩展名，存 `storage/uploads/{uid}/{material_id}/`。
- **异步**：入队 → 20ms 内返回 `material_id + pending`；状态机 `pending→parsing→ready|failed`。
- **版本**：同类型同名可 diff（≥3 处变更标注）。
- **异常**：加密 PDF / 空页 / 纯图片 → `failed` 或 `needs_ocr`，不静默成功。
- **验收句**：8 种格式各 1 份解析成功；表格行列还原 ≥95%；章节识别 ≥90%。

### F3 解析与切分（P0）

| 类型 | 切分策略 | 元数据 |
| :--- | :--- | :--- |
| 简历 | 章节感知（教育/技能/项目/实习/论文/奖项），项目再切 1–3 子块 | 项目名/角色/时间/技术栈 |
| JD | 结构抽取（职责/硬性/加分/关键词/截止） | 条目编号 |
| 项目/实习 | 父块 + 子块 + 邻接扩展 | section_path |
| 图片/截图 | VLM 描述 + OCR，保留 bbox | page + bbox + image_path |

- **验收句**：50 段人工标注，章节边界准确率 ≥90%；图片关键实体召回 ≥85%（抽检 20 张）。

### F4 检索与引用（P0）

- **管线**：Dense(BGE-M3) + Sparse(BM25) → RRF 融合 → BGE-Reranker → 阈值截断 → 邻接扩展。
- **引用**：每个 chunk 带 `{doc_id, doc_name, doc_type, page, bbox, section, version}`。
- **规则**：回答至少 1 条引用；不足则加标签"以下为通用建议，未引用你的材料"。
- **验收句**：60 条 golden，Recall@5 ≥0.80、nDCG@10 ≥0.70；人工 50 条，引用支撑率 ≥90%；点击定位 100%。

### F5 三层记忆（P0）

| 层 | 存什么 | 介质 | 生命周期 | 读时机 |
| :--- | :--- | :--- | :--- | :--- |
| L1 工作 | 最近 5–10 轮 + 任务槽位（模式/岗位/阶段/已问技能） | Redis | 7d TTL | 每轮 |
| L2 情节 | 结构化事件（面试/改简历：时间、岗位、人设、维度分、弱项、结论） | PostgreSQL | 180d，可删 | 面试前召回同岗位 |
| L3 画像 | 技能标签（置信度+来源）、目标岗位、稳定弱项、偏好、分数曲线 | PG + Redis 缓存 | 长期，可编辑可删 | 组装 system 上下文 |

- **写入**：规则槽位直接写；弱项/偏好由 LLM 抽取 + 用户确认；疑问句不写（对抗测试）。
- **冲突**：新值覆盖，保留 `source_event_id + 时间`；90 天未复现的弱项置信度衰减。
- **遗忘**：L1 TTL、L2 定时/手动、L3 手动；删号级联。
- **隐私**：写入前 PII 检测（身份证/手机/住址/银行卡）→ 拒写或脱敏。
- **验收句**：30 条探针通过率 ≥90%；删除后 5 次会话 0 出现；A 的画像不出现在 B 的 prompt。

### F6 双模式对话（P0）

- **对话模式**：项目复盘、JD 差距、STAR 打磨（给 diff）、岗位风险、心态支持。
- **面试模式**：见 F7。
- **共同硬规则**：
  1. 结论带来源徽章，无来源显式标注。
  2. 不虚构经历；缺数据输出占位符。
  3. 不确定就说不知道 + 怎么查。
- **验收句**：基于材料的问题带引用 ≥95%；20 条不可回答问题编造率 ≤5%。

### F7 面试引擎（P0）

**人设矩阵**（配置化，非提示词）：

| ID | 风格 | 严格 | 深度 | 默认发散 |
| :--- | :--- | :--- | :--- | :--- |
| `strict_architect` | 大厂架构师 | 5 | 5 | 0 |
| `business_tl` | 业务研发主管 | 4 | 3 | 1 |
| `gentle_mentor` | 实验室导师/校友 | 2 | 2 | 1 |

**发散度**：

| 档 | 允许范围 | 约束 | 可测指标 |
| :--- | :--- | :--- | :--- |
| 0 | 材料内事实 + 原理 + 边界 | 每轮引用材料锚点 | 材料引用率 100% |
| 1 | 可延伸相邻技术/行业常识 | 延伸后回到材料 | ≥70% |
| 2 | 情境假设/职业选择/趋势 | 标注"延伸题"，≤30% | 20–30% |

**4 阶状态机**：动机/选型 → 核心机制 → 工程边界 → 量化证据 → 收敛复盘；动作 `DEEP_PROBE / PIVOT_FALLBACK / WRAPUP`。
**约束**：不评外貌/籍贯/婚育；不泄露他人信息；不给完整标准答案；8–15 轮；重复率 <10%。
**验收句**：3 人设盲评可区分 ≥80%；发散度 0/1/2 的引用率达标；"不会"触发降维 ≥90%。

### F8 复盘报告与评分（P0）

- **五维 rubric**（1–5 分 + 权重）：事实一致性 25% / 技术深度 25% / 结构化表达 20% / 量化证据 20% / 沟通抗压 10%。
- **每维必须附 ≥1 条学生原话**作为证据。
- **报告结构**：总分 + 雷达 + 逐题卡（问题/回答摘要/得分/评语/更好的骨架）+ 3 条改进（做什么/参考材料/耗时/完成标准）+ 与上次对比 + 下一步练什么。
- **纪律**：temperature ≤0.3；同转录 3 次 ICC ≥0.70；与 2 人盲评 Spearman ≥0.6；控长度偏差。
- **验收句**：≤10s 出报告；证据覆盖率 ≥90%；建议可执行性人工 ≥4 分。

### F9 工具管理（P1）

- **注册表**：`name / description / input_schema(JSON Schema) / side_effect(read|write|external) / timeout / scope / enabled`。
- **权限**：读放行；外发需确认；写需二次确认 + 可回滚。
- **审计**：`tool_calls(id, owner_id, session_id, tool, args_hash, ok, latency_ms, tokens, error)`。
- **可见**：前端"本次回答用到的工具"折叠面板。
- **验收句**：8 个工具注册；未确认的外发/写调用 100% 拒绝；调用记录可查。

### F10 评测平台（P0）

- **一键**：`make eval` → `reports/eval-<date>.md` + `raw.json`。
- **数据集**：RAG golden 60 条 / 记忆探针 30 条 / 越权用例 30 条 / 面试场景 20 个 / 对抗样本 8 份（已有）。
- **指标**：Recall@5、nDCG@10、MRR、引用支撑率、拒答准确率、首 token P95、单次成本、评分 ICC、重复率、降维率、探针通过率、越权拦截率。
- **消融 6 组**：L0 直接 LLM → +RAG(纯向量) → +hybrid+rerank → +记忆 → +工具护栏 → full。
- **纪律**：固定模型/温度/seed、版本号（prompt/rubric/dataset/commit）写入报告；**报告数字必须由脚本写入，禁止手填**。
- **验收句**：单命令 ≤30min 出报告；每个数字可由 JSON 复算；6 组齐全。

---

## 7. 数据模型

### 7.1 现有（PostgreSQL，已被使用）

`knowledge_bases / file_documents / document_chunks / chunk_index / index_stats / retrieval_logs / custom_models / benchmark_records`

### 7.2 新增（P0，均带 `owner_id`）

```sql
users(id, student_id UNIQUE, email UNIQUE, password_hash, role, status, created_at, deleted_at)
materials(id, owner_id, type, title, version, file_path, sensitivity, parse_status, created_at)
sessions(id, owner_id, mode, persona, divergence_level, target_role, status, created_at)
turns(id, session_id, idx, role, content, citations JSONB, tool_calls JSONB, latency_ms)
scores(id, session_id, turn_id, dims JSONB, total, evidence JSONB, rubric_version, model)
reports(id, session_id, owner_id, overall, radar JSONB, turn_details JSONB, improvements JSONB, markdown)
profile_items(id, owner_id, category, item_key, confidence, source_session_id, updated_at)
events(id, owner_id, type, payload JSONB, created_at)
tool_calls(id, owner_id, session_id, tool, args_hash, ok, latency_ms, tokens, error)
audit_logs(id, actor, action, resource, ip, ts)
```

约束：所有业务表 `owner_id NOT NULL + INDEX`；仓储层统一过滤；禁止路由层裸查询。

---

## 8. 接口契约

### 8.1 现有（可直接演示）

| 方法 | 路径 | 用途 |
| :--- | :--- | :--- |
| POST | `/api/v1/career/match` | 简历 × JD 匹配（实测 200） |
| POST | `/api/v1/career/parse-resume` | 简历语义分块 |
| POST | `/api/v1/career/upload-multimodal` | 多格式上传解析 |
| POST | `/api/v1/career/fraud-check` | 岗位风控 |
| POST | `/api/v1/career/interview/chat` | 面试/闲聊（无鉴权，待改造） |
| GET/POST | `/api/v1/career/prompts` | 提示词工坊 |
| GET | `/api/v1/knowledge-bases` | 知识库列表 |
| POST | `/api/v1/chat`（SSE） | RAG 问答流 |

### 8.2 新增（P0）

```
POST   /api/v1/auth/login | refresh | logout
POST   /api/v1/materials            multipart
GET    /api/v1/materials?type= | /{id}/versions
POST   /api/v1/interview/sessions
POST   /api/v1/interview/sessions/{id}/turn
POST   /api/v1/interview/sessions/{id}/finish
GET    /api/v1/reports/{id} | /{id}.pdf
GET/PATCH/DELETE /api/v1/profile/items
DELETE /api/v1/account
GET    /api/v1/eval/report
```

### 8.3 SSE 事件

| event | payload |
| :--- | :--- |
| `token` | `{"content": "..."}` |
| `citation` | `{"doc": "...", "page": 2, "bbox": [...], "section": "..."}` |
| `stage_change` | `{"stage": "STAGE_3", "action": "DEEP_PROBE"}` |
| `score_feedback` | `{"score": 6, "gap": "..."}` |
| `tool` | `{"name": "search_jd", "ok": true, "ms": 120}` |
| `done` | `{"turn": 4, "tokens": 340}` |
| `error` | `{"code": "...", "msg": "..."}` |

---

## 9. 评分 rubric（可直接实现）

| 维度 | 1 分 | 3 分 | 5 分 | 权重 |
| :--- | :--- | :--- | :--- | :--- |
| 事实一致性 | 与材料矛盾 | 大体一致、有出入 | 完全一致且能自证 | 25% |
| 技术深度 | 只会名词 | 讲清原理 | 讲清原理+边界+取舍 | 25% |
| 结构化表达 | 无结构 | 有 STAR 雏形 | STAR 完整、重点前置 | 20% |
| 量化证据 | 全空 | 有数据但不精确 | 数据+口径+来源 | 20% |
| 沟通抗压 | 崩 | 稳 | 稳且能反问你 | 10% |

**反偏差措施**：不因答得长加分（长度归一化）；不因语气礼貌加分；同分必须给证据。

---

## 10. 非功能需求

| 类别 | 要求 |
| :--- | :--- |
| 性能 | 首 token P95 ≤2s；完整回答 P95 ≤8s；50 页 PDF 解析 ≤60s（异步）；20 并发错误率 <1% |
| 可用性 | LLM 不可用 → 熔断降级 + 明确提示（已有 circuit_breaker） |
| 安全 | JWT 短时效；argon2 哈希；上传白名单；提示注入 XML 隔离（已有注入样本回归） |
| 隐私 | 最小化收集；PII 脱敏；日志无正文；删除 60s 生效；支持导出 |
| 成本 | 单次面试 ≤¥0.6；日预算告警；embedding 缓存 |
| 部署 | 单机可跑；`.env` 一处配置；离线模式为 P1 |

---

## 11. 验收准则（64 条；P0 子集为上线门槛）

### A. 隔离与安全（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| A1 | 无/过期 token 访问业务接口 100% 401 | 全路由参数化 |
| A2 | `grep -r "default_user\|default_student"` 结果 0 | CI 断言 |
| A3 | 30 条跨用户用例 100% 403/404 | 越权套件 |
| A4 | 两人上传同名文档互不污染 | 双账号脚本 |
| A5 | A 的画像不出现在 B 的 prompt | prompt 断言 |
| A6 | A 改提示词不影响 B | 双账号回归 |
| A7 | 删号 60s 内 DB/文件/向量/Redis 残留 0 | 扫描脚本 |
| A8 | 日志/记忆中 PII 明文 0 | 正则扫描 |
| A9 | 导出包含本人全量且不含他人 | 导出断言 |
| A10 | 登录/上传/删除/导出写 audit_logs | 断言 |

### B. 材料与解析（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| B1 | 8 种格式各 1 份解析成功 | 回归集 |
| B2 | 表格行列还原 ≥95%（10 样例） | 脚本比对 |
| B3 | 章节边界准确率 ≥90%（50 段标注） | 人工 |
| B4 | 图片关键实体召回 ≥85%（20 张） | 人工 |
| B5 | 加密/空页 → failed，不静默 | 故障样例 |
| B6 | 多版本 diff 正确标注 ≥3 处 | 接口测试 |
| B7 | sensitive 材料默认不进召回 | 检索断言 |

### C. 检索与引用（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| C1 | Recall@5 ≥0.80 | 60 条 golden |
| C2 | nDCG@10 ≥0.70 | 同上 |
| C3 | 引用支撑率 ≥90% | 人工 50 条 |
| C4 | 点击定位正确 100% | E2E |
| C5 | 拒答准确率 ≥90% | 30 条 cannot-answer |
| C6 | 跨材料推理要素覆盖 ≥80% | 人工 10 条 |
| C7 | 注入样本得分不异常、不泄 prompt | 回归 |

### D. 记忆（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| D1 | 30 条探针通过率 ≥90% | 探针集 |
| D2 | 冲突覆盖正确（改目标岗位后旧值不注入） | 用例 |
| D3 | 删除后 5 次会话 0 出现 | 断言 |
| D4 | 反问句不写入（10 条对抗，误写 0） | 用例 |
| D5 | 开场引用"上次弱项"命中 ≥85% | 20 会话 |
| D6 | 画像每条可显示来源与时间 | UI |

### E. 面试（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| E1 | 3 人设盲评可区分 ≥80% | 5 人盲评 |
| E2 | 发散度 0/1/2 引用率达标 | 自动统计 |
| E3 | 阶段推进合规 ≥90% | 日志 |
| E4 | 答"不会"降维 ≥90% | 用例集 |
| E5 | 10 轮重复率 <10%，无死循环 | 相似度 |
| E6 | 20 条敏感诱导 100% 拒绝 | 红队 |
| E7 | 不给完整标准答案（20 轮抽检违规 ≤1） | 人工 |
| E8 | 每轮反馈 ≤3s 且带原话证据 ≥90% | 抽检 |

### F. 报告与评分（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| F1 | ≤10s 出报告，结构缺项 0 | 压测 |
| F2 | 每维附证据 ≥90% | 抽检 |
| F3 | 3 次打分 ICC ≥0.70 或分差 ≤1 占 ≥90% | 重跑 |
| F4 | 与 2 人盲评 Spearman ≥0.60 | 统计 |
| F5 | 改进项四要素齐全 ≥90% | 人工 ≥4 分 |
| F6 | 趋势对比正确 | 用例 |
| F7 | MD/PDF 导出与页面一致 | E2E |

### G. 评测与稳定（P0）

| ID | 判据 | 方式 |
| :--- | :--- | :--- |
| G1 | 单命令 ≤30min 出报告 | 执行记录 |
| G2 | ≥6 组消融，含质量/延迟/成本 | 报告 |
| G3 | 数字可复算、方案单调 | 校验脚本 |
| G4 | 20 并发错误率 <1%，首 token P95 ≤2s | 压测 |
| G5 | 报告记录模型/prompt/数据集/commit 版本 | 断言 |
| G6 | 指标退化 >5% 告警 | CI |

### H. 工程（P1）

| ID | 判据 |
| :--- | :--- |
| H1 | 核心服务行覆盖 ≥70% |
| H2 | LLM 断网时明确降级提示 |
| H3 | `scripts/doctor.sh` 全绿即可启动 |
| H4 | 日志无简历正文与 PII |
| H5 | 成本看板误差 <10% |

### K. 演示（P0）

| ID | 判据 |
| :--- | :--- |
| K1 | 3 分钟主链路无卡顿无报错 |
| K2 | ≥3 个可讲数字（引用率/ICC/消融） |
| K3 | 一页差异化说明 |
| K4 | ≥10 名同学试用 + 10 条反馈 |
| K5 | 明确列出当前局限 |

---

## 12. 里程碑

| 周 | 交付 | 演示 |
| :--- | :--- | :--- |
| **W0（已完成）** | 环境体检、启动验证、PRD 终版、脚本化 | `doctor.sh` 全绿；前端后端起得来 |
| W1 | 鉴权 + owner_id 全链路 + 30 条越权测试 | 两账号互不可见 |
| W2 | 材料中心 + 切分 + 检索 + 引用锚点 | 点引用跳原文；Recall@5 出数 |
| W3 | 面试引擎（3 人设 × 3 发散度）+ 记忆 + 报告 | 两位考官问同一份简历 |
| W4 | 评测平台（60 golden + 6 消融）+ 灰度 + 录屏 | 打开报告讲数字 |

**2 周急救版**：W1 鉴权 + 材料 + 引用；W2 人设面试 + 报告 + 20 条 golden。砍多模态图片、工具表、趋势、PDF 导出。

**每日纪律**：一天不跑通端到端就停下修链路，不加功能。

---

## 13. 风险

| 风险 | 应对 |
| :--- | :--- |
| 数据集小，指标不可信 | 报告写明样本量；扩到 60 条；只做相对比较 |
| 评分主观 | 锚点固定 + ICC + 人工校准；不做"能力判定"只做"改进建议" |
| 评测报告数字矛盾 | 删旧报告，统一脚本重跑，锁 commit |
| 时间不够 | 按 P0 砍，2 周急救版 |
| LLM 抖动/限流 | 熔断 + 缓存 + 固定温度 + 录屏兜底 |
| 隐私合规 | 离线模式（P1）+ 明示 + 可删 + 不收集身份证 |

---

## 14. 答辩与简历

### 14.1 90 秒开场

> 我做的是给辽大同学用的求职 Agent，不是聊天框。三个可验证的点：
> 第一，**它不编数字**——简历里没有的压测数据，它输出占位符而不是替你造，8 份对抗样本回归里虚构数值 0 例。
> 第二，**它会降维追问**——四阶状态机从我为什么这么选型，问到边界和量化；我说没做过，它会降到基础概念并把盲区记进画像，下一场开场直接问我。
> 第三，**每条建议能点回原文**，页码级锚点。
> 另外两件容易被忽略的事：30 条越权用例全绿、删号 60 秒清空；以及一套 60 条 golden 的评测，每次改动能看到指标涨跌。

### 14.2 简历（数字留空，跑出来再填，禁止编）

> **LNUCareer-Agent｜证据驱动型校园求职智能体**（Python/FastAPI/LangGraph/多模态 RAG/PostgreSQL+Redis）
> - 多租户隔离：JWT + 仓储层强制 owner 过滤，__ 条越权用例 100% 拦截，删号级联清理 __ 秒。
> - 事实保真护栏：无实测数据强制占位符，8 类对抗样本虚构数值 0 例，注入拦截 __%。
> - 自适应面试：4 阶状态机 + 3 人设 × 3 发散度，"答不会"降维率 __%，单场重复率 <10%。
> - 评测：__ 条 golden，Recall@5 __，引用正确率 __%，评分 ICC __。

### 14.3 "为什么不用 Kafka / Go"（主动讲减法）

> "我先按生产级写了一版 Go 网关 + Kafka 削峰 + 异步记忆压缩。算了一下业务量：全校日活几百人，峰值不到 10 QPS，Kafka 在这里唯一作用是增加两个故障点。所以那版留作设计文档，落地版是单体 + Celery，把省下的两周投到评测和护栏上。**这是这个项目里最重要的技术决策。**"

---

## 附录 A：启动手册（实测可用）

```bash
cd /home/yang/Agentic-Multimodal-RAG

# 体检
bash scripts/doctor.sh

# 启动（后端 8000 + 前端 3000）
bash scripts/dev.sh

# 测试
cd backend && python3 -m pytest -q

# 停止
bash scripts/stop.sh
```

依赖已装在系统 Python（3.14）用户目录，**无需新建 venv**。若需隔离：`uv venv .venv --python 3.11 && uv pip install -r requirements.txt`（注意 torch cu118 体积）。

## 附录 B：现状缺口清单（按优先级）

1. 无鉴权 / 无用户表 → W1
2. 提示词全局单例 → W1
3. career 数据不落库（会话/报告）→ W2–W3
4. 只有 1 个面试人设、无发散度 → W3
5. 评测报告数字矛盾、无消融 → W4
6. `python-jose` 未安装（JWT 依赖）→ W1
7. `data/enterprise_sre_sop` 与求职无关，若已入库会稀释召回 → 核对后移出主库

## 附录 C：术语

RAG / Golden set / 消融 / ICC（组内相关系数）/ Grounding（证据锚点）/ PIVOT_FALLBACK（降维追问）/ 事实保真（Truth-Preservation）
