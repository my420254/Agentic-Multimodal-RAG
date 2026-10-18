#!/usr/bin/env bash
# 停止由 dev.sh 启动的服务
set -uo pipefail
pkill -f "uvicorn app.main:app" 2>/dev/null && echo "后端已停止" || echo "后端未在运行"
pkill -f "vite --host 127.0.0.1" 2>/dev/null && echo "前端已停止" || echo "前端未在运行"
pkill -f "npx vite" 2>/dev/null
exit 0
