"""
岗位虚假信息与网络招聘反欺诈安全研判引擎
研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
核心能力：
1. 针对应届毕业生/实习生的虚假招聘、套路转培、涉诈诱导、隐私套取深度研判
2. 基于规则库 + 舆情风控知识库 + LLM 语义推理的双引擎风控判定
3. 输出量化安全评分、风险等级、命中特征规则及维权避坑指引
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.services.llm import LLMService

logger = logging.getLogger(__name__)


class FraudRiskLevel:
    SAFE = "SAFE"                 # 安全可信 (0 - 20分)
    LOW_RISK = "LOW_RISK"         # 低风险/注意甄别 (21 - 45分)
    SUSPICIOUS = "SUSPICIOUS"     # 疑似风险/高风险预警 (46 - 75分)
    HIGH_RISK = "HIGH_RISK"       # 极度危险/涉诈套路 (76 - 100分)


class FraudDetectionResult(BaseModel):
    """反欺诈研判报告"""
    job_title: str = Field(default="", description="岗位名称")
    company_name: str = Field(default="", description="企业名称")
    risk_level: str = Field(default=FraudRiskLevel.SAFE, description="安全风险等级")
    risk_score: int = Field(default=0, ge=0, le=100, description="欺诈风险得分(0-100分，分值越高风险越大)")
    is_fraudulent: bool = Field(default=False, description="是否判定为涉诈/虚假岗位")
    detected_traps: List[str] = Field(default_factory=list, description="命中的风险欺诈类别")
    violation_points: List[str] = Field(default_factory=list, description="具体风险点剖析")
    safety_warnings: List[str] = Field(default_factory=list, description="重点实验室防诈避坑预警")
    defense_advice: List[str] = Field(default_factory=list, description="维权与合规求职建议")
    analysis_summary: str = Field(default="", description="研判综合综述")
    lab_signature: str = Field(
        default="辽宁省公共舆情与网络安全信息系统重点实验室 · 招聘反欺诈安全研判引擎",
        description="风控签发单位"
    )


class JobFraudDetector:
    """虚假岗位与网络欺诈研判器"""

    # 重点实验室反欺诈特征库
    TRAP_RULES = {
        "培训贷与套路转培陷阱": {
            "weight": 35,
            "patterns": [
                r"培训费", r"实训费", r"技能提升费", r"学费分期", r"实训贷款",
                r"入职需交费", r"定向委培.*自费", r"先垫付.*报销", r"签订实训协议",
                r"包就业.*先交", r"免试入职.*岗前实训"
            ],
            "description": "以招聘入职为由，要求求职者先缴纳高额培训费、实训费或诱导办理学费分期贷款。"
        },
        "跨境涉诈与灰产诱导": {
            "weight": 45,
            "patterns": [
                r"海外高薪", r"高薪出海", r"缅北", r"东南亚.*无门槛", r"境外客服",
                r"包机票.*落地安排", r"扣押护照", r"免签出境", r"底薪[2-9]0k.*无门槛",
                r"包吃住.*境外园区", r"带货出境"
            ],
            "description": "以海外高薪、无门槛出境为诱饵，诱导学生前往境外涉诈园区，极可能涉及跨境赌博、电信网络诈骗。"
        },
        "刷单兼职与跑分洗钱黑产": {
            "weight": 40,
            "patterns": [
                r"刷单", r"点赞返佣", r"日结[3-9]00", r"日赚上千", r"垫付本金",
                r"出租微信", r"出借收款码", r"跑分", r"转账返现", r"佣金立结",
                r"手机动动手指.*日结"
            ],
            "description": "假借兼职之名从事刷单诈骗，或诱导租借出售银行卡、微信支付宝收款码，涉及帮助信息网络犯罪活动罪（帮信罪）。"
        },
        "敏感隐私与金融信息套取": {
            "weight": 30,
            "patterns": [
                r"手持身份证", r"银行卡密码", r"支付密码", r"短信验证码",
                r"手机银行登录", r"未面试.*索要征信", r"家庭资产流水", r"担保人房产"
            ],
            "description": "在正式面试与劳动合同确立前，提前过度索取求职者银行卡密码、验证码、手持证件照，极可能用于非法开户洗钱或电信诈骗。"
        },
        "虚假挂靠与李鬼皮包企业": {
            "weight": 25,
            "patterns": [
                r"加微信详聊.*无公司", r"无固定办公地点", r"私信发简历",
                r"挂靠社保", r"租用名企资质", r"不签正规劳动合同", r"仅支持私对私转账"
            ],
            "description": "企业信息模糊不清，无法提供有效统一社会信用代码，拒绝提供真实办公地点或盗用名企名义虚假招揽。"
        },
        "薪酬待遇与岗位权责严重不对称": {
            "weight": 20,
            "patterns": [
                r"无经验.*月入[3-9]万", r"轻松月入过万.*初中学历", r"不限学历.*年薪50万",
                r"入职即送.*豪车", r"躺赚", r"随到随学.*月薪2万"
            ],
            "description": "薪资标准显著偏离正常人才市场公允水平，往往为黑灰产引流诱饵。"
        }
    }

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm = llm_service or LLMService()

    def detect_by_rules(self, job_title: str, company: str, job_description: str) -> Dict[str, Any]:
        """第一阶段：基于重点实验室风控规则库的高速特征匹配"""
        content = f"岗位名称: {job_title}\n企业: {company}\n岗位职责与要求: {job_description}"
        
        detected_traps = []
        violation_points = []
        total_risk_score = 0

        for trap_name, rule in self.TRAP_RULES.items():
            hit_patterns = []
            for pat in rule["patterns"]:
                match = re.search(pat, content, re.IGNORECASE)
                if match:
                    hit_patterns.append(match.group(0))

            if hit_patterns:
                detected_traps.append(trap_name)
                total_risk_score += rule["weight"]
                violation_points.append(
                    f"命中【{trap_name}】特征词: {', '.join(set(hit_patterns))}。特征说明：{rule['description']}"
                )

        # 归一化得分最高 100
        risk_score = min(total_risk_score, 100)

        # 判定等级
        if risk_score >= 60:
            risk_level = FraudRiskLevel.HIGH_RISK
            is_fraud = True
        elif risk_score >= 30:
            risk_level = FraudRiskLevel.SUSPICIOUS
            is_fraud = True
        elif risk_score >= 15:
            risk_level = FraudRiskLevel.LOW_RISK
            is_fraud = False
        else:
            risk_level = FraudRiskLevel.SAFE
            is_fraud = False

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "is_fraud": is_fraud,
            "detected_traps": detected_traps,
            "violation_points": violation_points
        }

    async def analyze(
        self,
        job_title: str,
        company: str,
        job_description: str,
        deep_llm_audit: bool = True
    ) -> FraudDetectionResult:
        """端到端执行虚假招聘与涉诈风险综合研判"""
        rule_result = self.detect_by_rules(job_title, company, job_description)

        risk_score = rule_result["risk_score"]
        risk_level = rule_result["risk_level"]
        is_fraud = rule_result["is_fraud"]
        detected_traps = rule_result["detected_traps"]
        violation_points = rule_result["violation_points"]

        safety_warnings = []
        defense_advice = []
        summary_text = ""

        # 生成安全警示与维权建议
        if is_fraud or risk_score >= 30:
            safety_warnings.append("⚠️ 【重点实验室安全警示】该岗位存在明显欺诈引流或套路特征，请严防财产损失与个人征信风险！")
            if "培训贷与套路转培陷阱" in detected_traps:
                safety_warnings.append("🚨 任何以‘岗前实训’、‘高薪保过’为由要求自费贷款的招聘均为转培骗局。正规企业招聘绝不收取求职者任何费用！")
                defense_advice.append("保留合同、聊天记录及缴费单据，立即向全国人社政务服务平台（12333）投诉举报。")
            if "跨境涉诈与灰产诱导" in detected_traps:
                safety_warnings.append("🚨 严禁轻信境外无门槛高薪出海招聘，警惕跨境电信诈骗与人身安全非法拘禁陷阱！")
                defense_advice.append("切勿向对方邮寄护照原件，如已被限制人身自由或遭遇诈骗，立即拨打 110 或驻外使领馆领保电话求助。")
            if "刷单兼职与跑分洗钱黑产" in detected_traps:
                safety_warnings.append("🚨 刷单兼职 100% 属于诈骗，出借个人银行账户/收款码极易触犯《刑法》帮信罪！")
                defense_advice.append("立即停止资金往来，向国家反诈中心 APP 举报涉案账号。")
            if "敏感隐私与金融信息套取" in detected_traps:
                safety_warnings.append("🚨 警惕个人身份信息泄露，正规招聘绝不会在初试前索取银行卡密码与手持证件照！")
                defense_advice.append("不要输入任何手机短信验证码，若已泄露银行信息，第一时间联系银行冻结挂失。")
        else:
            safety_warnings.append("✅ 该岗位招聘信息表述基本合规，未检索到已知典型网络黑灰产欺诈特征。")
            defense_advice.append("求职过程中请保持常态化警惕，入职务必签署正规纸质或电子劳动合同，明确试用期薪资及五险一金缴纳约定。")

        # 若为可疑/高风险且开启了深度 LLM 审核，调用 LLM 进行风控语义研判与综合阐述
        if deep_llm_audit and (risk_score >= 20 or len(job_description) > 50):
            try:
                prompt = f"""你来自【辽宁省公共舆情与网络安全信息系统重点实验室】，是网络招聘与求职反欺诈研判专家。
请对以下招聘岗位进行舆情与网络欺诈深度研判：
【岗位名称】：{job_title}
【企业名称】：{company}
【岗位描述】：{job_description}
【规则引擎初步判定】：风险评分 {risk_score} 分，风险等级 {risk_level}，命中类别：{', '.join(detected_traps) if detected_traps else '无'}

请给出一份针对在校大学生的专业研判报告，严格遵循以下 JSON 格式：
{{
  "additional_risk_points": ["风险点1", "风险点2"],
  "synthesized_summary": "一到两段专业的研判结论与综述",
  "recommended_action": "明确指出学生应该如何行动（如：果断放弃/多方核查/正常应聘）"
}}
"""
                response = await self.llm.generate([
                    {"role": "system", "content": "You are a cybersecurity and public opinion anti-fraud expert. Reply with pure JSON."},
                    {"role": "user", "content": prompt}
                ])
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    for pt in parsed.get("additional_risk_points", []):
                        if pt and pt not in violation_points:
                            violation_points.append(f"【深度舆情研判】{pt}")
                    summary_text = parsed.get("synthesized_summary", "")
                    rec_action = parsed.get("recommended_action", "")
                    if rec_action:
                        defense_advice.insert(0, f"行动建议：{rec_action}")
            except Exception as e:
                logger.warning(f"[JobFraudDetector] LLM 深度审计降级: {str(e)}")

        if not summary_text:
            if is_fraud:
                summary_text = (
                    f"经实验室反欺诈研判引擎检测，该岗位【{job_title}】存在重大求职安全隐患，"
                    f"综合风险评分达 {risk_score} 分（{risk_level}）。"
                    f"主要涉及 {', '.join(detected_traps) if detected_traps else '异常招聘特征'}，"
                    f"建议求职学生提高反诈意识，严禁转账支付或泄露核心敏感资产信息。"
                )
            else:
                summary_text = (
                    f"经实验室反欺诈研判引擎核验，该岗位【{job_title}】当前未见典型网络招聘诈骗特征，"
                    f"综合风险评分 {risk_score} 分（{risk_level}），整体处于安全受控范围。"
                )

        return FraudDetectionResult(
            job_title=job_title,
            company_name=company,
            risk_level=risk_level,
            risk_score=risk_score,
            is_fraudulent=is_fraud,
            detected_traps=detected_traps,
            violation_points=violation_points,
            safety_warnings=safety_warnings,
            defense_advice=defense_advice,
            analysis_summary=summary_text
        )


# 全局单例
job_fraud_detector = JobFraudDetector()
