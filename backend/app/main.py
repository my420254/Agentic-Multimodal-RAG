"""
FastAPI 应用入口
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from contextlib import asynccontextmanager
import os
import time
from sqlmodel import Session

from app.core.config import get_settings, ensure_directories
from app.core.database import engine, init_db
from app.core.metrics import metrics_payload, observe_http
from app.models import RequestLog
from app.api import api_router

settings = get_settings()


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
    # 关闭时执行
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
    allow_origins=["*"],  # 生产环境应限制具体域名
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
    import sys
    import uuid

    sys.stdout.flush()
    start = time.perf_counter()
    print(f"[Request] {request.method} {request.url.path}")
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
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
        print(f"[Response] {status_code} {request.url.path} ({duration * 1000:.1f}ms)")
        sys.stdout.flush()

# 静态文件服务（图片预览）
if os.path.exists(settings.IMAGE_DIR):
    app.mount(
        "/static/images",
        StaticFiles(directory=settings.IMAGE_DIR),
        name="images",
    )


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    return JSONResponse(
        status_code=500,
        content={
            "code": 50000,
            "message": f"服务器内部错误: {str(exc)}",
        },
    )


# 健康检查
@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


# 根路径
@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Local Multimodal Agent RAG API",
        "version": "1.0.0",
        "docs": "/docs",
    }
