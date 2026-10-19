# 交接说明（给 WSL 内的执行 Agent）

> **⚠️ 2026-10-19 更新：本文是 W1 鉴权时期的历史任务书，鉴权/隔离早已完成。**  
> **当前项目状态、运行手册、Langfuse 迁移方案请看 [`docs/PROJECT_STATUS_REPORT.md`](PROJECT_STATUS_REPORT.md)。不要按本文从“加鉴权”开始做。**



> 你是接手本项目的工程师 Agent。仓库：`/home/yang/Agentic-Multimodal-RAG`。
> 本文档是**操作手册**，不是背景介绍。读完本文 + `docs/PRD.md` 的相关章节即可开工。
> 一次只推进一个 commit，每个 commit 跑完验证再进下一个，不要一口气改完。

---

## 0. 你的角色与边界

- 你负责**实现**：写代码、跑测试、修失败、提交 commit。
- 你**不负责**：改产品方向、改技术栈、扩大范围。凡涉及"要不要加中间件/要不要换框架/要不要改数据模型"之外的架构决策，先停下来问，不要自作主张。
- 判断标准：PRD 第 2.3 节的"三连测试"——不做它会怎样 / 更简单的替代是什么 / 数字哪来的。答不上来的东西不要加。

---

## 1. 30 秒背景

这是一个面向辽宁大学在校生的**求职辅助 Agent**（简历诊断、模拟面试、复盘报告）。已有能力：多模态解析、混合检索（向量+BM25+重排）、LangGraph 编排、简历×JD 匹配、三层记忆雏形、面试 4 阶状态机。

**当前唯一硬缺口：没有鉴权，所有用户数据混在一起。** 本轮任务就是把这个补上。

---

## 2. 必读（按顺序，约 15 分钟）

1. `docs/PRD.md` —— 只看这五节：
   - **§0 现状核实**（实测表 + 能力清单 + 4 个 P0 缺陷）
   - **§4.4 v2.0 裁决表**（知道什么被砍了，别再加回来）
   - **§6 F1**（鉴权与隔离的具体规则）
   - **§11 A 组**（验收判据，你的完成标准）
   - **附录 B**（缺口清单，按周对齐）
2. `backend/app/api/career.py` —— 当前所有 career 接口，全部无鉴权。
3. `backend/app/services/memory_service.py` 与 `prompt_service.py` —— 两处用户隔离缺陷所在地。
4. `backend/app/core/database.py` 与 `config.py` —— 数据库与配置入口。

---

## 3. 环境事实（已实测，不要重复摸索）

| 事实 | 说明 |
| :--- | :--- |
| Python | 3.14.4，依赖装在用户目录，**不需要建 venv** |
| 数据库 | `.env` 的 `DATABASE_URL` 指向 PostgreSQL `agent_db`（8 张表已存在） |
| `backend/local.db` | 历史遗留 SQLite，**不要混用**，也别删 |
| Redis | 6379 运行中 |
| 模型 | DeepSeek（LLM）+ SiliconFlow BGE-M3（Embedding），Key 已配且连通 |
| 启动 | `bash scripts/dev.sh`（后端 8000 + 前端 3000）；`bash scripts/stop.sh` 停止 |
| 体检 | `bash scripts/doctor.sh`（15 项，应全绿） |
| 测试 | `make test-fast`（13 个快测）；全量 `make test` |
| 日志 | `.logs/backend.log`、`.logs/frontend.log` |

开工第一件事：

```bash
cd /home/yang/Agentic-Multimodal-RAG
git status                 # 应有约 58 个未提交改动（历史工作）
bash scripts/doctor.sh     # 应 15 通过 / 0 失败
make test-fast             # 应 13 passed
```

然后**先做一次快照提交**，让后续改动可分：

```bash
git add -A
git commit -m "chore: snapshot before W1 (PRD v4 + scripts)"
```

---

## 4. 铁律（违反即回滚）

1. **不要 `git reset` / `git checkout --` / `git clean -fd`**。仓库里 `backend/storage/uploads/` 有真实简历，`git clean` 会删掉。
2. **不要改 `backend/.env`**（含 Key）。需要新配置项时，写进 `.env.example` 并在汇报里说明。
3. **不要删库、不要 drop 表**。新增表用 SQLModel `create_all` 即可；已存在的表加列必须手写 `ALTER`。
4. **不要为了"更规范"重构业务代码**。本轮只动鉴权与隔离相关文件，其他文件除非编译不过，否则不碰。
5. **不要引入新框架**：不加 Kafka、不加 Go 服务、不加 ORM、不加消息队列。Celery/Redis 已经是上限。
6. **不要编数字**。任何百分比、QPS、耗时，必须来自你实际跑出来的输出。写不进报告的就不写。
7. **不要一次提交改 20 个文件**。三个 commit 分开，每个都能单独回滚。

---

## 5. 本轮任务：W1（三个 commit）

### C1 — `feat(auth)`: 账号与 JWT

**目标**：有用户表、能登录、能拿到 token。

**改动**
- `backend/app/models/models.py`：新增 `User`（`id UUID pk / student_id unique / email unique / password_hash / role / status / created_at / deleted_at`）。
- 新文件 `backend/app/core/security.py`：密码哈希 + JWT 签发/校验。
- 新文件 `backend/app/api/auth.py`：`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh`、`GET /api/v1/auth/me`。
- `backend/app/api/__init__.py`：挂载 auth 路由。
- 新文件 `scripts/seed_demo_users.py`：建两个测试账号（`2023001` / `2023002`），仅 dev 用。

**要点**
- 配置项加到 `Settings` 和 `.env.example`：`JWT_SECRET`、`JWT_ALG=HS256`、`ACCESS_TTL_MIN=15`、`REFRESH_TTL_DAYS=7`。**不要写死密钥**，未配置时启动报错而不是用默认值。
- 密码哈希优先 `bcrypt`；若 `passlib` 报 `module 'bcrypt' has no attribute '__about__'`（passlib 与 bcrypt 5.x 的已知不兼容），**不要再折腾 passlib**，直接用 `bcrypt` 库封装两个函数即可。
- JWT 先试 `python-jose`；它当前**未安装**，装完 import 失败就直接换 `PyJWT`（更轻），并在 `requirements.txt` 同步。
- token 里放 `sub=user_id`、`role`、`exp`，不要放学号以外的敏感信息。

**验收**
```bash
curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"student_id":"2023001","password":"<seed 密码>"}' | head -c 200
# 期望：含 access_token / refresh_token 的 JSON，HTTP 200

curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/auth/me
# 期望：401
```

---

### C2 — `refactor(tenant)`: 强制用户上下文 + 消除全局单例

**目标**：`user_id` 只能来自 token；两处跨用户串味修掉。

**改动**
- 新文件 `backend/app/core/deps.py`：`get_current_user` 依赖，从 `Authorization: Bearer` 解析并注入。
- `backend/app/api/career.py`：整个 router 挂 `dependencies=[Depends(get_current_user)]`；删除请求体里的 `user_id` 字段与所有 `default_student` 默认值。
- `backend/app/services/prompt_service.py`：模板改为 per-user（Redis Hash `u:{uid}:prompts`，默认值仍来自代码常量）。**这是 P0 隐私缺陷**，必须真改，不能只加注释。
- `backend/app/services/memory_service.py`：所有 key 前面加 `u:{uid}:`；`user_id` 必填，去掉 `default_user`。
- 全仓搜索并清零：`grep -rn "default_user\|default_student" backend/app`。

**要点**
- 404 优先于 403：越权访问他人资源返回 **404**，避免泄露资源是否存在。
- 现有 Redis 里没有历史用户数据，key 前缀变更**不需要迁移**。
- `career.py` 里 `interview_chat` 的 `session_id` 也要校验归属：session 属于当前用户，否则 404。
- 暂不新建 `materials/sessions/reports` 表（那是 W2/W3 的事），本轮只做"上下文来自 token"这一层。

**验收**
```bash
# 无 token 访问 career 接口必须 401
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/career/prompts

# 有 token 必须 200
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"student_id":"2023001","password":"<seed 密码>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/career/prompts -H "Authorization: Bearer $TOKEN"

grep -rn "default_user\|default_student" backend/app   # 期望：无输出
```

---

### C3 — `test(security)`: 30 条越权用例

**目标**：把 A 组验收变成自动化测试。

**改动**
- 新文件 `backend/tests/test_auth_isolation.py`。
- `backend/tests/conftest.py`：加 `user_a` / `user_b` / `token_a` / `token_b` fixture（用测试库，别污染 `agent_db`）。

**用例矩阵（共 30 条，参数化实现）**

| 类别 | 条数 | 断言 |
| :--- | :--- | :--- |
| 无 token / 空 token / 伪造签名 / 过期 token | 8 | 401 |
| 过期 refresh token 换 access | 2 | 401 |
| A 的 token 访问 B 的资源（material/session/report/profile × 4） | 12 | 404 |
| body 里塞 `user_id=B` 被忽略 | 4 | 200 且数据属于 A |
| 删除 B 的资源 | 2 | 404，且 B 的数据仍在 |
| token 中 `sub` 被篡改为 B | 2 | 401 |

**要点**
- 用 `fastapi.testclient.TestClient`，不要起真实端口。
- 测试库用临时 SQLite 或独立 PG schema 均可，但**必须**在 `conftest.py` 里覆盖 `DATABASE_URL`，不要连 `agent_db`。
- 加一条静态断言：`grep` 不到 `default_user` / `default_student`，否则 fail。

**验收**
```bash
cd backend && python3 -m pytest tests/test_auth_isolation.py -q   # 30 passed
make test-fast                                                     # 全绿，无回归
```

---

## 6. 完成定义（DoD）

三个 commit 全部满足才算 W1 完成：

1. `make test-fast` 与 `pytest tests/test_auth_isolation.py` 全绿。
2. `bash scripts/doctor.sh` 仍 15/0。
3. 手工验证：无 token → 401；A 的 token 访问 B 的资源 → 404。
4. `grep -rn "default_user\|default_student" backend/app` 无输出。
5. `git log --oneline -3` 是三个语义清晰的 commit。
6. 汇报里贴出上面 4 条的**真实命令与输出**。

---

## 7. 汇报模板（每完成一个 commit 发一次）

```markdown
## C<n> 完成：<commit message>

**改了哪些文件**（一句话/个）
- ...

**验证**（贴命令与输出）
- `pytest ...` → ...
- `curl ...` → ...

**踩到的坑 / 偏离计划的地方**
- ...

**需要拍板的问题**
- ...

**下一步**：C<n+1>
```

---

## 8. 已知坑（别重复踩）

| 坑 | 处理 |
| :--- | :--- |
| `python-jose` 未安装 | `python3 -m pip install --user "python-jose[cryptography]"`；import 失败换 PyJWT |
| `passlib` 与 `bcrypt` 5.x 不兼容 | 直接用 `bcrypt` 库，别在 passlib 上花时间 |
| Python 3.14 太新，某些包无 wheel | 报错就换纯 Python 实现，不要为此建 3.11 venv（会重装 torch，代价太大） |
| SQLModel `create_all` 只建新表 | 改已有表必须手写 `ALTER TABLE` |
| `conftest.py` 可能覆盖 `DATABASE_URL` | 改模型前先读它，否则测试会连到 `agent_db` |
| `pytest` 里 LLM 调用会真花钱 | 跑全量测试前确认哪些用例会调模型；越权测试**不应该**调用模型 |
| 端口 8000/3000 被占 | `bash scripts/stop.sh` |

---

## 9. 不要做的事（再说一遍）

- 不写 `docker-compose`、不加 Kafka、不加 Go。
- 不改前端（W1 不涉及 UI）。
- 不动 `app/api/chat.py` 的 SSE 逻辑。
- 不删 `backend/storage/` 下任何文件（真实简历在里面）。
- 不为了跑通测试而 `pytest.skip` 掉安全用例。

---

## 10. 后续里程碑（只做索引，本轮不碰）

| 周 | 内容 | 关键交付 |
| :--- | :--- | :--- |
| W2 | 材料中心：`materials` 表、上传/版本、解析状态机、引用锚点 | 点引用跳原文 |
| W3 | 面试引擎（3 人设 × 3 发散度）+ 三层记忆落库 + 复盘报告 | 报告带逐题证据 |
| W4 | 评测平台：60 条 golden、6 组消融、一键 `make eval` | 报告数字可复算 |

细节见 `docs/PRD.md` §6 F2–F10、§11 验收、§12 里程碑。

---

## 11. 需要人拍板的问题（先问，不要自行决定）

1. 登录账号体系：学号 + 密码，还是校园邮箱验证码？（影响 C1 的登录实现）
2. `JWT_SECRET` 由谁生成、放在哪（本地 `.env` 还是部署环境变量）？
3. 测试用户密码用固定值（如 `Test@123456`）还是随机生成后打印？
4. 是否允许本轮顺手把 `career.py` 拆成 `career/` 包？（建议不做，等 W2）
