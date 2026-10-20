"""
系统设置 API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import get_session
from app.core.deps import get_current_user, require_route_scope
from app.schemas.schemas import ApiResponse, CustomModelCreate, CustomModelResponse, CustomModelUpdate
from app.models import CustomModel, ModelType

router = APIRouter(
    prefix="/settings",
    tags=["Meta"],
    dependencies=[Depends(get_current_user), Depends(require_route_scope)],
)
models_router = APIRouter(
    tags=["Meta"],
    dependencies=[Depends(get_current_user), Depends(require_route_scope)],
)  # 单独的 /models 路由
settings = get_settings()


class ModelInfo(BaseModel):
    """模型信息（前端期望格式）"""
    id: str
    name: str
    type: str  # embedding, vlm, llm
    provider: str


class SystemSettings(BaseModel):
    """系统设置（前端格式）"""
    defaultEmbeddingModel: str
    defaultVlmModel: str
    defaultLlmModel: str
    maxConcurrency: int
    chunkSize: int
    chunkOverlap: int
    maxChatHistoryRounds: int


class UpdateSettingsRequest(BaseModel):
    """更新设置请求"""
    default_embedding_model: str = None
    default_vlm_model: str = None
    default_llm_model: str = None
    max_concurrency: int = None
    chunk_size: int = None
    chunk_overlap: int = None
    max_chat_history_rounds: int = None


@router.get("", response_model=ApiResponse[SystemSettings])
async def get_system_settings():
    """获取系统设置"""
    return ApiResponse(data=SystemSettings(
        defaultEmbeddingModel=settings.EMBEDDING_MODEL,
        defaultVlmModel=settings.VLM_MODEL,
        defaultLlmModel=settings.LLM_MODEL,
        maxConcurrency=settings.MAX_PARSING_WORKERS,
        chunkSize=settings.CHUNK_SIZE,
        chunkOverlap=settings.CHUNK_OVERLAP,
        maxChatHistoryRounds=settings.MAX_CHAT_HISTORY_ROUNDS,
    ))


@router.put("", response_model=ApiResponse[SystemSettings])
async def update_system_settings(data: UpdateSettingsRequest):
    """更新系统设置"""
    if data.default_embedding_model:
        settings.EMBEDDING_MODEL = data.default_embedding_model
    if data.default_vlm_model:
        settings.VLM_MODEL = data.default_vlm_model
    if data.default_llm_model:
        settings.LLM_MODEL = data.default_llm_model
    if data.max_concurrency:
        settings.MAX_PARSING_WORKERS = data.max_concurrency
    if data.chunk_size:
        settings.CHUNK_SIZE = data.chunk_size
    if data.chunk_overlap:
        settings.CHUNK_OVERLAP = data.chunk_overlap
    if data.max_chat_history_rounds:
        settings.MAX_CHAT_HISTORY_ROUNDS = data.max_chat_history_rounds
        
    return ApiResponse(data=SystemSettings(
        defaultEmbeddingModel=settings.EMBEDDING_MODEL,
        defaultVlmModel=settings.VLM_MODEL,
        defaultLlmModel=settings.LLM_MODEL,
        maxConcurrency=settings.MAX_PARSING_WORKERS,
        chunkSize=settings.CHUNK_SIZE,
        chunkOverlap=settings.CHUNK_OVERLAP,
        maxChatHistoryRounds=settings.MAX_CHAT_HISTORY_ROUNDS,
    ))


# ==================== 自定义模型管理 ====================

@router.get("/models", response_model=ApiResponse[List[CustomModelResponse]])
async def get_custom_models(session: Session = Depends(get_session)):
    """获取自定义模型列表"""
    # 1. 获取数据库自定义模型
    db_models = session.exec(select(CustomModel)).all()
    response_list = [CustomModelResponse.model_validate(m) for m in db_models]
    
    return ApiResponse(data=response_list)


from datetime import datetime, timezone

@router.post("/models", response_model=ApiResponse[CustomModelResponse])
async def create_custom_model(
    model_in: CustomModelCreate,
    session: Session = Depends(get_session)
):
    """添加自定义模型"""
    # 检查名称是否重复
    existing = session.exec(select(CustomModel).where(CustomModel.name == model_in.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="模型名称已存在")

    try:
        # 验证 model_type
        m_type = ModelType(model_in.model_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的模型类型")

    db_model = CustomModel(
        name=model_in.name,
        model_type=m_type,
        base_url=model_in.base_url,
        api_key=model_in.api_key,
        model_name=model_in.model_name,
        updated_at=datetime.now(timezone.utc), # Fix: set updated_at
    )
    session.add(db_model)
    session.commit()
    session.refresh(db_model)
    return ApiResponse(data=db_model)


@router.put("/models/{model_id}", response_model=ApiResponse[CustomModelResponse])
async def update_custom_model(
    model_id: str,
    model_in: CustomModelUpdate,
    session: Session = Depends(get_session)
):
    """更新自定义模型"""
    db_model = session.get(CustomModel, model_id)
    if not db_model:
        raise HTTPException(status_code=404, detail="模型不存在")

    if model_in.name is not None and model_in.name != db_model.name:
        # 检查名称重复 - 已移除限制
        # existing = session.exec(select(CustomModel).where(CustomModel.name == model_in.name)).first()
        # if existing:
        #     raise HTTPException(status_code=400, detail="模型名称已存在")
        db_model.name = model_in.name

    if model_in.base_url is not None:
        db_model.base_url = model_in.base_url
    if model_in.api_key is not None:
        db_model.api_key = model_in.api_key
    if model_in.model_name is not None:
        db_model.model_name = model_in.model_name
    
    if model_in.context_length is not None:
        db_model.context_length = model_in.context_length

    if model_in.model_type is not None:
        try:
            db_model.model_type = ModelType(model_in.model_type)
        except ValueError:
             raise HTTPException(status_code=400, detail="无效的模型类型")

    db_model.updated_at = datetime.now(timezone.utc)
    session.add(db_model)
    session.commit()
    session.refresh(db_model)
    return ApiResponse(data=db_model)


@router.delete("/models/{model_id}", response_model=ApiResponse)
async def delete_custom_model(
    model_id: str,
    session: Session = Depends(get_session)
):
    """删除自定义模型"""
    if model_id == "sys_embedding":

        return ApiResponse(message="系统模型已隐藏")

    db_model = session.get(CustomModel, model_id)
    if not db_model:
        raise HTTPException(status_code=404, detail="模型不存在")
    
    session.delete(db_model)
    session.commit()
    return ApiResponse(message="删除成功")


@router.post("/models/{model_id}/test", response_model=ApiResponse)
async def test_custom_model_connection(
    model_id: str,
    session: Session = Depends(get_session)
):
    """测试自定义模型连接"""
    db_model = session.get(CustomModel, model_id)
    if not db_model:
        raise HTTPException(status_code=404, detail="模型不存在")

    try:
        import requests
        # 根据模型类型进行轻量高效的连接测试
        if db_model.model_type == ModelType.EMBEDDING:
            headers = {"Authorization": f"Bearer {db_model.api_key}", "Content-Type": "application/json"}
            url = f"{db_model.base_url.rstrip('/')}/embeddings"
            resp = requests.post(url, headers=headers, json={"model": db_model.model_name, "input": ["test"]}, timeout=15)
            if resp.status_code >= 400:
                raise Exception(f"HTTP {resp.status_code}: {resp.text}")

        elif db_model.model_type in (ModelType.LLM, ModelType.VLM):
            headers = {"Authorization": f"Bearer {db_model.api_key}", "Content-Type": "application/json"}
            url = f"{db_model.base_url.rstrip('/')}/chat/completions"
            resp = requests.post(url, headers=headers, json={
                "model": db_model.model_name,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5
            }, timeout=30)
            if resp.status_code >= 400:
                raise Exception(f"HTTP {resp.status_code}: {resp.text}")

        elif db_model.model_type == ModelType.RERANK:
            from app.services.rerank import test_rerank_connection
            result = test_rerank_connection(db_model)
            if not result["success"]:
                raise Exception(result["message"])

        return ApiResponse(message="连接测试成功")

    except Exception as e:
        print(f"Test connection failed: {e}")
        # 返回 400 让前端知道测试失败
        raise HTTPException(
            status_code=400, 
            detail={"message": f"连接测试失败: {str(e)}"}
        )


# ==================== 通用模型列表 (下拉选择用) ====================

@models_router.get("/models", response_model=ApiResponse[List[ModelInfo]])
async def get_model_list(session: Session = Depends(get_session)):
    """获取模型列表（包含系统预设和自定义模型）"""
    models = []
    print("🔍 [GetModelList] 开始获取模型列表...")

    # 1. 系统预设模型 (从 .env 读取)
    if settings.LLM_MODEL:
        models.append(ModelInfo(
            id="sys_llm",
            name=f"DeepSeek ({settings.LLM_MODEL})",
            type="llm",
            provider="System"
        ))
    if settings.EMBEDDING_MODEL:
        sys_model = ModelInfo(
            id="sys_embedding",
            name=f"SiliconFlow ({settings.EMBEDDING_MODEL})",
            type="embedding",
            provider="System"
        )
        models.append(sys_model)
    if settings.VLM_MODEL:
        models.append(ModelInfo(
            id="sys_vlm",
            name=f"SiliconFlow VLM ({settings.VLM_MODEL})",
            type="vlm",
            provider="System"
        ))

    # 2. 自定义模型 (从数据库读取)
    try:
        custom_models = session.exec(select(CustomModel).where(CustomModel.is_active == True)).all()
        print(f"🔍 [GetModelList] 数据库中发现 {len(custom_models)} 个激活的自定义模型")
        for cm in custom_models:
            print(f"   - ID: {cm.id}, Name: {cm.name}, Type: {cm.model_type.value}, Provider: Custom")
            models.append(ModelInfo(
                id=cm.id, # 使用 UUID 作为 ID
                name=cm.name,
                type=cm.model_type.value,
                provider="Custom",
            ))
    except Exception as e:
        print(f"❌ [GetModelList] 查询数据库失败: {e}")

    print(f"✅ [GetModelList] 返回总模型数: {len(models)}")
    return ApiResponse(data=models)
