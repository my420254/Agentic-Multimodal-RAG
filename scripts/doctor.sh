#!/usr/bin/env bash
# LNUCareer-Agent 环境体检：依赖 / 数据库 / 缓存 / 模型 Key / 端口
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PASS=0; FAIL=0
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; FAIL=$((FAIL+1)); }
info() { printf "  \033[90m·\033[0m %s\n" "$1"; }
envval() { sed -n "s/^$1=//p" backend/.env 2>/dev/null | head -1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }

echo "== 1/6 Python 依赖 =="
MISSING=$(python3 - 2>/dev/null <<'PY'
import importlib
mods = ["fastapi","uvicorn","sqlmodel","langgraph","langchain_core","chromadb",
        "pymupdf","docx","pandas","redis","celery","openai","httpx","pytest"]
miss = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        miss.append(m)
print(" ".join(miss))
PY
)
if [ -z "$MISSING" ]; then ok "核心依赖齐全（Python $(python3 -c 'import sys;print(sys.version.split()[0])')）"; else bad "缺少依赖: $MISSING"; fi

echo "== 2/6 PostgreSQL =="
if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
  ok "PostgreSQL 5432 可连接"
  CNT=$(PGPASSWORD=postgres psql -h 127.0.0.1 -U postgres -d agent_db -t -A -c \
        "select (select count(*) from knowledge_bases)||' kb / '||(select count(*) from document_chunks)||' chunks'" 2>/dev/null)
  [ -n "$CNT" ] && info "数据: $CNT"
else
  bad "PostgreSQL 5432 不可用（后端会连不上库）"
fi

echo "== 3/6 Redis =="
if [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then
  ok "Redis 6379 PONG"
else
  bad "Redis 不可用（记忆 L1 / 限流会降级为内存）"
fi

echo "== 4/6 .env 配置 =="
if [ -f backend/.env ]; then
  for k in LLM_BASE_URL LLM_API_KEY LLM_MODEL EMBEDDING_BASE_URL EMBEDDING_API_KEY DATABASE_URL REDIS_URL; do
    v="$(envval "$k")"
    if [ -n "$v" ]; then ok "$k 已配置"; else bad "$k 为空"; fi
  done
  info "LLM=$(envval LLM_MODEL) @ $(envval LLM_BASE_URL)"
else
  bad "backend/.env 不存在（cp backend/.env.example backend/.env）"
fi

echo "== 5/6 模型连通性 =="
LLM_BASE="$(envval LLM_BASE_URL)"; LLM_KEY="$(envval LLM_API_KEY)"
EMB_BASE="$(envval EMBEDDING_BASE_URL)"; EMB_KEY="$(envval EMBEDDING_API_KEY)"
if [ -n "$LLM_KEY" ]; then
  code=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "${LLM_BASE%/}/models" -H "Authorization: Bearer $LLM_KEY")
  [ "$code" = "200" ] && ok "LLM 接口 200" || bad "LLM 接口返回 $code（Key 失效或网络不通）"
else
  info "跳过 LLM（未配置 Key）"
fi
if [ -n "$EMB_KEY" ]; then
  code=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "${EMB_BASE%/}/models" -H "Authorization: Bearer $EMB_KEY")
  [ "$code" = "200" ] && ok "Embedding 接口 200" || bad "Embedding 接口返回 $code"
fi

echo "== 6/6 端口与前端 =="
for p in 8000 3000; do
  if ss -ltn 2>/dev/null | grep -q ":$p "; then info "端口 $p 已被占用（可能已在运行）"; else ok "端口 $p 空闲"; fi
done
if [ -d frontend/node_modules ]; then ok "前端依赖已安装"; else bad "前端依赖未安装（cd frontend && npm ci）"; fi

echo
printf "结果: \033[32m%d 通过\033[0m / \033[31m%d 失败\033[0m\n" "$PASS" "$FAIL"
if [ "$FAIL" -eq 0 ]; then echo "环境就绪 → bash scripts/dev.sh"; else echo "先修复上面标 ✗ 的项"; fi
exit 0
