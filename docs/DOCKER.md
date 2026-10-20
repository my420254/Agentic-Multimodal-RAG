# Docker Compose 运行手册

## 组成

- `db`：`pgvector/pgvector:pg16`
- `redis`：`redis:7`
- `backend`：FastAPI + Alembic（启动时 `AUTO_MIGRATE=true` 自动 upgrade）
- `frontend`：学生端 Vite 构建产物 + Nginx；`/api/` 反向代理到 backend，SSE 关闭 buffering
- `admin-frontend`：独立观测后台（3001），复用 `frontend/src/pages/Admin` 源码，单独构建/部署

## 启动

```bash
cd /home/yang/Agentic-Multimodal-RAG

# 必填：JWT_SECRET（至少 32 字符）
export JWT_SECRET="$(cat /tmp/lnu_dev_jwt_secret)"

# 可选：如果你用宿主机上的 Ollama，把 backend/.env 改成
#   LLM_BASE_URL=http://host.docker.internal:11434/v1
#   EMBEDDING_BASE_URL=http://host.docker.internal:11434/v1
# 如果使用 DeepSeek/SiliconFlow，保持原 URL 即可。

docker compose build
docker compose up -d
curl http://127.0.0.1:8000/ready
```

学生端：`http://127.0.0.1:3000`  
观测后台：`http://127.0.0.1:3001`  
后端：`http://127.0.0.1:8000`

> 观测后台是独立的 `admin-frontend` 服务，不在学生端导航中，也没有 `/admin` 路由。

## 迁移

- 容器启动时 `init_db()` 会执行 `alembic upgrade head`；
- 生产多实例建议在 compose 里设置 `AUTO_MIGRATE=false`，由发布流程先跑：

```bash
docker compose run --rm backend alembic upgrade head
```

## 数据

- PostgreSQL 数据：`pgdata` volume；
- 上传文件：`./backend/storage` bind mount；
- `.env` 不打进镜像（`.dockerignore` 排除），由 compose `env_file` 注入。

## 常见问题

1. **容器连不上 Ollama**  
   Linux 下 `host.docker.internal` 已通过 `extra_hosts: host-gateway` 映射；把 `LLM_BASE_URL`/`EMBEDDING_BASE_URL` 改成 `http://host.docker.internal:11434/v1`。

2. **JWT_SECRET 未设置**  
   compose 会直接报错，这是故意的；不要使用默认密钥。

3. **前端刷新 404**  
   Nginx 已配置 `try_files $uri $uri/ /index.html`，如果仍 404，确认使用的是本仓库的 `frontend/nginx.conf` 或 `admin-frontend/nginx.conf`。

4. **SSE 不流式**  
   `nginx.conf` 已设置 `proxy_buffering off`；如果前面还有一层网关，也需要关闭 buffering。
