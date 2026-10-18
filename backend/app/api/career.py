"""
高校就业辅导与反欺诈安全 API 路由
机构：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import tempfile
import os

from app.services.job_fraud_detector import job_fraud_detector, FraudDetectionResult
from app.services.career_matcher import career_matcher_service, CareerMatchResult, ResumeSection
from app.services.mock_interview import mock_interview_service, InterviewTurnResponse
from app.services.graphrag_service import graphrag_service
from app.services.prompt_service import prompt_workshop_service
from app.services.parser import FileParser
from app.core.rate_limiter import global_rate_limiter

router = APIRouter(prefix="/career", tags=["Career & Interview Agent"])


class JobFraudCheckRequest(BaseModel):
    """岗位合规与防欺诈研判请求"""
    job_title: str = Field(description="招聘岗位名称")
    company: str = Field(default="", description="招聘企业名称")
    job_description: str = Field(description="岗位职责要求及薪酬待遇描述")
    deep_audit: bool = Field(default=True, description="是否启用 LLM 深度舆情风控审计")


class CareerMatchRequest(BaseModel):
    """简历与 JD 双向匹配与诊断请求"""
    resume_text: str = Field(description="学生简历文本")
    jd_text: str = Field(description="目标岗位 JD 描述")


class ResumeParseRequest(BaseModel):
    """纯文本简历语义分块请求"""
    resume_text: str = Field(description="简历文本内容")


from app.services.memory_service import memory_service


class InterviewChatRequest(BaseModel):
    """模拟面试与求职辅导对话请求"""
    session_id: Optional[str] = Field(default=None, description="会话唯一标识(用于三层记忆上下文绑定)")
    user_id: Optional[str] = Field(default="default_student", description="用户唯一标识(用于长期偏好隔离)")
    messages: List[Dict[str, str]] = Field(description="多轮历史对话消息列表")
    mode: str = Field(default="mock_interview", description="模式: mock_interview (模拟面试) 或 casual_chat (求职闲聊)")
    target_role: str = Field(default="AI Agent / 后端研发工程师", description="目标应聘岗位")
    resume_summary: str = Field(default="", description="学生简历亮点摘要")
    custom_prompt: Optional[str] = Field(default=None, description="用户自定义生效的系统提示词")


class UpdatePromptRequest(BaseModel):
    """用户自定义更新提示词请求"""
    key: str = Field(description="模板键名: mock_interviewer, resume_doctor, star_rewriter, career_counselor")
    system_prompt: str = Field(description="用户修改后的提示词全文")


class ResetPromptRequest(BaseModel):
    """重置提示词请求"""
    key: str = Field(description="模板键名")



@router.post("/fraud-check", response_model=FraudDetectionResult)
async def check_job_fraud(req: JobFraudCheckRequest):
    """
    【反欺诈风控研判】
    检测招聘岗位是否存在培训贷、境外诱导、刷单灰产、敏感隐私套取及虚假企业风险
    """
    if not global_rate_limiter.is_allowed("fraud_check"):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试（触发滑动窗口原子限流护栏）")

    if not req.job_description.strip():
        raise HTTPException(status_code=400, detail="岗位描述内容不能为空")

    result = await job_fraud_detector.analyze(
        job_title=req.job_title,
        company=req.company,
        job_description=req.job_description,
        deep_llm_audit=req.deep_audit
    )
    return result


@router.post("/match", response_model=CareerMatchResult)
async def match_resume_and_jd(req: CareerMatchRequest):
    """
    【简历与 JD 智能双向匹配】
    输出量化得分、五维能力雷达图、技能缺口以及基于 STAR 原则的针对性润色重写方案
    """
    if not global_rate_limiter.is_allowed("career_match"):
        raise HTTPException(status_code=429, detail="请求并发超限，请稍后重试")

    if not req.resume_text.strip() or not req.jd_text.strip():
        raise HTTPException(status_code=400, detail="简历文本与岗位 JD 均不可为空")

    result = await career_matcher_service.analyze_and_optimize(
        resume_text=req.resume_text,
        jd_text=req.jd_text
    )
    return result


@router.post("/parse-resume", response_model=List[ResumeSection])
async def parse_resume_text(req: ResumeParseRequest):
    """
    【简历语义分块】
    将简历文本结构化切割为教育背景、专业技能、实习经历、核心项目、学术论文等语义块
    """
    if not req.resume_text.strip():
        raise HTTPException(status_code=400, detail="简历内容为空")

    sections = career_matcher_service.parse_resume_sections(req.resume_text)
    return sections


@router.post("/interview/chat", response_model=InterviewTurnResponse)
async def interview_chat(req: InterviewChatRequest):
    """
    【GraphRAG 智能模拟面试 / 求职心理闲聊】
    根据技能拓扑图进行由浅入深的递进式追问 (Probing)，并对上一轮回答进行实时打分与复盘
    """
    if not global_rate_limiter.is_allowed("interview_chat"):
        raise HTTPException(status_code=429, detail="请求并发超限，请稍后重试")

    if not req.messages:
        raise HTTPException(status_code=400, detail="对话消息列表不能为空")

    # 1. 挂接三层分层记忆服务 (MemoryService)
    augmented_summary = req.resume_summary
    if req.session_id:
        last_msg = req.messages[-1]["content"] if req.messages else ""
        memory_service.add_message(req.session_id, "user", last_msg)
        # 获取 L3 长期偏好与 L2 滚动摘要
        mem_ctx = memory_service.assemble_context_for_prompt(req.session_id, user_id=req.user_id)
        context_parts = [req.resume_summary]
        if mem_ctx.get("profile_text"):
            context_parts.append(mem_ctx["profile_text"])
        if mem_ctx.get("summary_text"):
            context_parts.append(mem_ctx["summary_text"])
        augmented_summary = "\n\n".join([p for p in context_parts if p.strip()])

    turn_response = await mock_interview_service.chat(
        messages=req.messages,
        mode=req.mode,
        target_role=req.target_role,
        resume_summary=augmented_summary,
        custom_prompt=req.custom_prompt
    )

    # 2. 记忆落库
    if req.session_id:
        memory_service.add_message(req.session_id, "assistant", turn_response.reply_text)

    return turn_response


@router.get("/interview/session/{session_id}/memory")
async def get_session_memory(session_id: str, user_id: str = "default_student"):
    """
    【三层分层记忆查看】
    实时读取指定会话的 L1 活跃消息、L2 滚动摘要及 L3 长期画像
    """
    return memory_service.assemble_context_for_prompt(session_id=session_id, user_id=user_id)


@router.delete("/interview/session/{session_id}")
async def clear_session_memory(session_id: str):
    """
    【清空会话记忆】
    清空指定会话的 L1 临时消息与 L2 增量摘要
    """
    memory_service.clear_session(session_id)
    return {"message": f"会话 {session_id} 的全部记忆缓存已成功清除"}


@router.get("/skill-graph")
async def get_skill_graph():
    """
    【GraphRAG 技能拓扑图谱】
    获取全量技能节点与前驱后继关系图谱
    """
    return graphrag_service.get_full_graph()


@router.get("/graphrag/subgraph")
async def get_graphrag_subgraph(query: str = "redis"):
    """
    【GraphRAG 子图多跳检索】
    根据关键词多跳遍历关联技能实体、考点与拓扑路径
    """
    subgraph = graphrag_service.search_subgraph(query, max_depth=2)
    return subgraph


@router.get("/prompts")
async def get_prompt_templates():
    """
    【提示词工坊 - 查看所有模板】
    查看当前激活的四大提示词：面试官、简历诊断、STAR润色、心理疏导
    """
    return prompt_workshop_service.get_all_templates()


@router.post("/prompts")
async def update_prompt_template(req: UpdatePromptRequest):
    """
    【提示词工坊 - 用户自定义修改】
    允许用户在线重写/定制提示词并立即生效
    """
    try:
        updated = prompt_workshop_service.update_template(req.key, req.system_prompt)
        return {"status": "ok", "template": updated}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/prompts/reset")
async def reset_prompt_template(req: ResetPromptRequest):
    """
    【提示词工坊 - 恢复默认提示词】
    """
    try:
        reset_tpl = prompt_workshop_service.reset_template(req.key)
        return {"status": "ok", "template": reset_tpl}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))



@router.post("/upload-multimodal")
async def upload_multimodal_resume(
    file: UploadFile = File(...)
):
    """
    【多模态简历多格式深度解析】
    支持 PDF, DOCX, Markdown, CSV, XLSX, 图片 (PNG/JPG)，保留排版与表格结构
    """
    ext = os.path.splitext(file.filename)[1].lower()
    allowed_exts = [".pdf", ".docx", ".txt", ".md", ".xlsx", ".csv", ".png", ".jpg", ".jpeg"]
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，支持 PDF/DOCX/MD/表格/图片")

    # 写入临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        parser = FileParser(kb_id="campus_career_temp")
        chunks = parser.parse(tmp_path, chunk_mode="structure", chunk_size=800, chunk_overlap=80)
        full_text = "\n\n".join(c.content for c in chunks)
        sections = career_matcher_service.parse_resume_sections(full_text)
        tech_tags = career_matcher_service._extract_tech_keywords(full_text)

        return {
            "filename": file.filename,
            "format": ext,
            "total_chunks": len(chunks),
            "extracted_text_length": len(full_text),
            "full_text": full_text[:4000],  # 截取前 4000 字符展示
            "sections": sections,
            "extracted_tech_stack": tech_tags,
            "lab_signature": "辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室 · 多模态解析中心"
        }
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
