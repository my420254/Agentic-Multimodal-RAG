"""
FastAPI 应用入口
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from contextlib import asynccontextmanager
import logging
import os
import time
import uuid

import httpx
import redis
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import get_settings, ensure_directories
from app.core.database import engine, init_db
from app.core.metrics import metrics_payload, observe_http
from app.core.tracing import tracer
from app.models import RequestLog
from app.api import api_router

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    ensure_directories()
    init_db()
    print("数据库初始化完成")

    # 调试：打印所有路由
    print("🚀 [Startup] Registered Routes:")
    for route in app.routes:
        if isinstance(route, APIRoute):
            print(f"   {route.methods} {route.path}")

    yield
    # 关闭时执行：把 Langfuse 缓冲区中的 trace 发出去
    tracer.shutdown()
    print("应用关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="Local Multimodal Agent RAG API",
    description="本地化多模态 Agent RAG 系统接口",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/metrics", include_in_schema=False)
async def metrics():
    payload, media_type = metrics_payload()
    return Response(content=payload, media_type=media_type)


# 注册 API 路由
app.include_router(api_router)

# 调试：中间件记录请求
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex}"
    request.state.request_id = request_id
    start = time.perf_counter()
    print(f"[Request] {request_id} {request.method} {request.url.path}")
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-Id"] = request_id
        return response
    finally:
        duration = time.perf_counter() - start
        try:
            observe_http(request.method, request.url.path, status_code, duration)
        except Exception:
            pass
        # 不记录 metrics/静态文件/文档；请求日志默认开启，测试环境关闭
        if settings.REQUEST_LOG_ENABLED and request.url.path.startswith("/api/v1/"):
            try:
                with Session(engine) as session:
                    session.add(RequestLog(
                        method=request.method,
                        path=request.url.path[:255],
                        status_code=status_code,
                        duration_ms=round(duration * 1000, 2),
                        user_id=getattr(request.state, "user_id", None),
                        client_ip=request.client.host if request.client else None,
                    ))
                    session.commit()
            except Exception as e:
                print(f"[RequestLog] skip: {e}")
        print(
            f"[Response] {request_id} {status_code} {request.url.path} "
            f"({duration * 1000:.1f}ms)"
        )

# 静态文件服务（图片预览）
if os.path.exists(settings.IMAGE_DIR):
    app.mount(
        "/static/images",
        StaticFiles(directory=settings.IMAGE_DIR),
        name="images",
    )


# 全局异常处理：不把内部异常文本返回给客户端，只返回 request_id 供日志排查。
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled exception request_id=%s method=%s path=%s",
        request_id,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    content = {
        "code": 50000,
        "message": "服务器内部错误，请稍后重试",
        "request_id": request_id,
    }
    headers = {"X-Request-Id": request_id} if request_id else None
    return JSONResponse(status_code=500, content=content, headers=headers)


# 健康检查（liveness）：只表示进程活着
@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


async def _check_postgres() -> tuple[str, str | None]:
    try:
        with Session(engine) as session:
            session.connection().execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:
        return "error", type(exc).__name__


async def _check_redis() -> tuple[str, str | None]:
    client = None
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        client.ping()
        return "ok", None
    except Exception as exc:
        return "error", type(exc).__name__
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


async def _check_llm() -> tuple[str, str | None]:
    if not settings.READY_CHECK_LLM:
        return "skipped", None
    try:
        base = settings.LLM_BASE_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=2.0, trust_env=True) as client:
            response = await client.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            )
            response.raise_for_status()
        return "ok", None
    except Exception as exc:
        return "error", type(exc).__name__


# 就绪检查（readiness）：PG / Redis 是硬依赖；LLM 默认只标记 degraded
@app.get("/ready")
async def readiness_check():
    checks: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name, checker in (
        ("postgres", _check_postgres),
        ("redis", _check_redis),
        ("llm", _check_llm),
    ):
        status, error = await checker()
        checks[name] = status
        if error:
            errors[name] = error

    critical_ok = checks["postgres"] == "ok" and checks["redis"] == "ok"
    if settings.READY_REQUIRE_LLM:
        critical_ok = critical_ok and checks["llm"] == "ok"
    if not critical_ok:
        overall = "unavailable"
    elif any(value == "error" for value in checks.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return JSONResponse(
        status_code=200 if critical_ok else 503,
        content={"status": overall, "checks": checks, "errors": errors},
    )


# 根路径
@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Local Multimodal Agent RAG API",
        "version": "1.0.0",
        "docs": "/docs",
    }
