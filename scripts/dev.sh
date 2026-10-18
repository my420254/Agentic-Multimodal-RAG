#!/usr/bin/env bash
# 一键启动：后端(8000) + 前端(3000)，日志在 .logs/
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
LOGS="$ROOT/.logs"; mkdir -p "$LOGS"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BPID=""; FPID=""; CLEANED=0

cleanup() {
  if [ "$CLEANED" = "1" ]; then return; fi
  CLEANED=1
  echo; echo "[dev] 正在停止服务..."
  if [ -n "$BPID" ]; then kill "$BPID" 2>/dev/null; fi
  if [ -n "$FPID" ]; then kill "$FPID" 2>/dev/null; fi
  # 子进程（uvicorn worker / vite 的 node）按进程名兜底清理
  pkill -f "uvicorn app.main:app" 2>/dev/null
  pkill -f "vite --host 127.0.0.1" 2>/dev/null
  pkill -f "node.*vite" 2>/dev/null
  wait 2>/dev/null
  echo "[dev] 已停止"
}
trap cleanup INT TERM EXIT

echo "[dev] 启动后端 :$BACKEND_PORT"
( cd backend && exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" ) \
  > "$LOGS/backend.log" 2>&1 &
BPID=$!

echo "[dev] 启动前端 :$FRONTEND_PORT"
( cd frontend && exec npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" ) \
  > "$LOGS/frontend.log" 2>&1 &
FPID=$!

for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$BACKEND_PORT/docs"; then break; fi
  if ! kill -0 "$BPID" 2>/dev/null; then
    echo "[dev] 后端启动失败，见 $LOGS/backend.log"
    tail -20 "$LOGS/backend.log"
    exit 1
  fi
  sleep 0.5
done
for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/"; then break; fi
  sleep 0.5
done

echo
echo "  前端  http://127.0.0.1:$FRONTEND_PORT"
echo "  接口  http://127.0.0.1:$BACKEND_PORT/docs"
echo "  日志  $LOGS/{backend,frontend}.log"
echo "  Ctrl+C 停止"
echo
wait
