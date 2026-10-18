/**
 * 高校智能求职面试辅导与简历优化 Agent 平台
 * 研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
 * 核心支柱：
 * 1. 简历严谨诊断与 STAR 针对性优化 (精准挑刺指出痛点、能力雷达与量化重构)
 * 2. GraphRAG 技能拓扑树驱动的递进技术模拟面试 (Probing 追问与实时打分)
 * 3. 求职心理梳理与职业闲聊疏导 (情绪接纳、谈薪话术与抗压指导)
 * 4. 提示词工坊 (用户可自由查看、修改、测试与替换系统提示词)
 */

import React, { useState, useEffect } from 'react';
import {
  Card,
  Tabs,
  Form,
  Input,
  Button,
  Row,
  Col,
  Tag,
  Progress,
  Alert,
  Space,
  Typography,
  Divider,
  message,
  List,
  Spin,
  Radio,
  Statistic,
  Select,
  Tooltip
} from 'antd';
import {
  FileTextOutlined,
  CommentOutlined,
  CheckCircleOutlined,
  RocketOutlined,
  BulbOutlined,
  SendOutlined,
  BranchesOutlined,
  CodeOutlined,
  ExclamationCircleOutlined,
  UndoOutlined,
  SaveOutlined,
  RadarChartOutlined
} from '@ant-design/icons';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const CareerCenter: React.FC = () => {
  const [activeTab, setActiveTab] = useState('resume_doctor');

  // ==================== 1. 简历严谨诊断与 STAR 优化 ====================
  const [resumeText, setResumeText] = useState(
    `张梦洋 | 辽宁大学软件工程（NLP）硕士 (2024.09 - 2027.06)
【专业技能】
熟练掌握 Python, FastAPI, Go, Docker, Redis, Kafka, LangGraph 状态机, PostgreSQL + pgvector, Hybrid RAG 混合检索与 BGE-Reranker。
【实习经历】
广州省心购科技 - 大模型智能体研发实习生 (2026.07 - 2026.10)
- 基于 MCP 协议与事件总线构建主从多智能体运行时；
- 负责端云异步事件驱动链路与三级记忆架构。
【核心项目经历】
基于多模态与 GraphRAG 的高校智能求职面试辅导 Agent 平台 (辽宁大学重点实验室)
- 采用 PostgreSQL GIN 倒排 + pgvector 双路统一召回，提高检索准确度；
- 基于 Redis 7 ZSet + Lua 脚本实现滑动窗口限流，优化高并发响应。`
  );

  const [jdText, setJdText] = useState(
    `【一线大厂 · 大模型智能体与高并发后端架构师】
岗位职责：
1. 负责多智能体协同运行时与 LangGraph 分层状态机编排；
2. 深度掌握 Python, FastAPI, Redis 缓存击穿治理与分布式锁，具备 1000+ QPS 极限高并发抗压调优经验；
3. 负责企业级 Hybrid RAG 混合检索管线构建，精通 BM25/GIN 倒排与向量召回融合及重排器调优。
任职要求：计算机或软件工程相关专业硕士，具有扎实工程落地能力，要求具备死循环熔断与异常降级闭环思维。`
  );

  const [matchLoading, setMatchLoading] = useState(false);
  const [matchResult, setMatchResult] = useState<any>(null);

  const handleDiagnoseResume = async () => {
    if (!resumeText.trim() || !jdText.trim()) {
      message.warning('请先输入学生简历与目标岗位 JD');
      return;
    }
    setMatchLoading(true);
    try {
      const resp = await fetch('/api/v1/career/match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resume_text: resumeText, jd_text: jdText })
      });
      if (!resp.ok) throw new Error('简历诊断请求失败');
      const data = await resp.json();
      setMatchResult(data);
      message.success('大厂 TL 简历深度诊断与 STAR 优化完成！');
    } catch (err: any) {
      message.error(err.message || '诊断失败');
    } finally {
      setMatchLoading(false);
    }
  };

  // ==================== 2. GraphRAG 模拟面试与心理疏导 ====================
  const [interviewMode, setInterviewMode] = useState<'mock_interview' | 'casual_chat'>('mock_interview');
  const [chatMessages, setChatMessages] = useState<Array<{
    role: string;
    content: string;
    feedback?: string;
    score?: number;
    graphPath?: string;
    activeNodes?: string[];
  }>>([
    {
      role: 'interviewer',
      content: '同学你好！我是辽宁大学重点实验室技术面试官。我看你简历里写到使用 Redis + Lua 脚本实现了滑动窗口限流器并支撑 1000+ QPS。请你结合底层机制谈谈：为什么选择 ZSet 滑动窗口而不是固定窗口计数器？在高并发多实例环境下，Lua 脚本是如何保证原子性以防超买的？',
      graphPath: 'redis_basics -> cache_breakdown -> redis_lua_limiter',
      activeNodes: ['Redis 内存数据结构', 'Redis ZSet + Lua 原子滑动窗口限流']
    }
  ]);
  const [userInput, setUserInput] = useState('');
  const [interviewLoading, setInterviewLoading] = useState(false);

  const handleSendChat = async () => {
    if (!userInput.trim()) return;
    const newMsgs = [...chatMessages, { role: 'user', content: userInput }];
    setChatMessages(newMsgs);
    setUserInput('');
    setInterviewLoading(true);

    try {
      const resp = await fetch('/api/v1/career/interview/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: newMsgs.map(m => ({ role: m.role, content: m.content })),
          mode: interviewMode,
          target_role: 'AI Agent / 高并发架构工程师',
          resume_summary: '辽宁大学硕士，熟练掌握 Agent 状态机、Hybrid RAG、FastAPI 高并发与 Redis 限流'
        })
      });
      if (!resp.ok) throw new Error('面试辅导服务响应失败');
      const data = await resp.json();
      setChatMessages([
        ...newMsgs,
        {
          role: data.role,
          content: data.reply_text,
          feedback: data.feedback,
          score: data.score_for_last_answer,
          graphPath: data.graphrag_traversal_path,
          activeNodes: data.graphrag_active_nodes
        }
      ]);
    } catch (err: any) {
      message.error(err.message || '对话失败');
    } finally {
      setInterviewLoading(false);
    }
  };

  // ==================== 3. 提示词工程工坊 (用户可自由查看与手写) ====================
  const [promptTemplates, setPromptTemplates] = useState<Record<string, any>>({});
  const [selectedPromptKey, setSelectedPromptKey] = useState<string>('mock_interviewer');
  const [editingPromptText, setEditingPromptText] = useState<string>('');
  const [promptLoading, setPromptLoading] = useState<boolean>(false);

  const fetchPrompts = async () => {
    setPromptLoading(true);
    try {
      const resp = await fetch('/api/v1/career/prompts');
      if (resp.ok) {
        const data = await resp.json();
        setPromptTemplates(data);
        if (data[selectedPromptKey]) {
          setEditingPromptText(data[selectedPromptKey].system_prompt);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setPromptLoading(false);
    }
  };

  useEffect(() => {
    fetchPrompts();
  }, []);

  const handleSelectPrompt = (key: string) => {
    setSelectedPromptKey(key);
    if (promptTemplates[key]) {
      setEditingPromptText(promptTemplates[key].system_prompt);
    }
  };

  const handleSavePrompt = async () => {
    try {
      const resp = await fetch('/api/v1/career/prompts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          key: selectedPromptKey,
          system_prompt: editingPromptText
        })
      });
      if (!resp.ok) throw new Error('保存提示词失败');
      message.success(`提示词 [${promptTemplates[selectedPromptKey]?.name}] 已成功更新并生效！`);
      fetchPrompts();
    } catch (err: any) {
      message.error(err.message || '保存失败');
    }
  };

  const handleResetPrompt = async () => {
    try {
      const resp = await fetch('/api/v1/career/prompts/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: selectedPromptKey })
      });
      if (!resp.ok) throw new Error('重置失败');
      message.success(`已恢复默认提示词！`);
      fetchPrompts();
    } catch (err: any) {
      message.error(err.message || '重置失败');
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
      <div style={{ marginBottom: '20px' }}>
        <Space direction="vertical" size={2}>
          <Title level={3} style={{ margin: 0 }}>
            <RocketOutlined style={{ color: '#1890ff', marginRight: 10 }} />
            高校智能求职面试辅导与简历优化 Agent 平台
          </Title>
          <Text type="secondary">
            研发生态：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室 | 基于 GraphRAG 技能图谱推理、大厂 TL 简历诊断与自定义提示词工程
          </Text>
        </Space>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        type="card"
        items={[
          {
            key: 'resume_doctor',
            label: (
              <span>
                <FileTextOutlined /> 简历深度诊断 & STAR 量化重构
              </span>
            ),
            children: (
              <div>
                <Alert
                  message="大厂 TL 简历严谨诊断模式"
                  description="拒绝泛泛夸奖！系统将以严格的用人部门技术眼光，逐条挑刺指出学生简历中的【数据缺失】、【深度空洞】与【缺少闭环】，并基于 STAR 原则给出高质量的对比重写示范。"
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                />

                <Row gutter={20}>
                  <Col span={12}>
                    <Card title="📄 学生简历多模态文本 (教育背景/项目经历/技能列表)" size="small">
                      <TextArea
                        rows={10}
                        value={resumeText}
                        onChange={e => setResumeText(e.target.value)}
                        placeholder="粘贴学生简历内容..."
                      />
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card title="🎯 目标企业岗位 JD (任职要求/硬性门槛)" size="small">
                      <TextArea
                        rows={10}
                        value={jdText}
                        onChange={e => setJdText(e.target.value)}
                        placeholder="粘贴目标岗位招聘要求..."
                      />
                    </Card>
                  </Col>
                </Row>

                <div style={{ textAlign: 'center', marginTop: 16 }}>
                  <Button
                    type="primary"
                    size="large"
                    icon={<FileTextOutlined />}
                    onClick={handleDiagnoseResume}
                    loading={matchLoading}
                  >
                    开始大厂 TL 严谨诊断与 STAR 优化
                  </Button>
                </div>

                {matchResult && (
                  <div style={{ marginTop: 24 }}>
                    <Card title="📊 简历深度诊断与能力评估报告" size="small">
                      <Row gutter={24} align="middle">
                        <Col span={6} style={{ textAlign: 'center' }}>
                          <Statistic
                            title="综合匹配度评分"
                            value={matchResult.overall_match_score}
                            suffix="/ 100"
                            valueStyle={{ color: matchResult.overall_match_score >= 80 ? '#52c41a' : '#faad14', fontSize: 36 }}
                          />
                          <Tag color="blue" style={{ marginTop: 8 }}>
                            {matchResult.match_level}
                          </Tag>
                          {matchResult.compliance_risk_alert && (
                            <div style={{ marginTop: 8 }}>
                              <Tag color="orange">{matchResult.compliance_risk_alert}</Tag>
                            </div>
                          )}
                        </Col>
                        <Col span={18}>
                          <Row gutter={16}>
                            <Col span={6}>
                              <Text strong>技术深度</Text>
                              <Progress percent={matchResult.radar_chart.technical_depth} strokeColor="#1890ff" />
                            </Col>
                            <Col span={6}>
                              <Text strong>工程架构 (高并发)</Text>
                              <Progress percent={matchResult.radar_chart.architecture_engineering} strokeColor="#52c41a" />
                            </Col>
                            <Col span={6}>
                              <Text strong>项目实战经验</Text>
                              <Progress percent={matchResult.radar_chart.project_experience} strokeColor="#722ed1" />
                            </Col>
                            <Col span={6}>
                              <Text strong>攻坚自愈能力</Text>
                              <Progress percent={matchResult.radar_chart.problem_solving} strokeColor="#eb2f96" />
                            </Col>
                          </Row>
                        </Col>
                      </Row>

                      <Divider orientation="left" style={{ margin: '16px 0' }}>
                        <ExclamationCircleOutlined style={{ color: '#f5222d', marginRight: 8 }} />
                        大厂面试官指出的核心痛点与薄弱硬伤
                      </Divider>
                      <List
                        dataSource={matchResult.critical_weaknesses || []}
                        renderItem={(weakness: string, idx: number) => (
                          <List.Item style={{ padding: '6px 0' }}>
                            <Text type="danger" strong>
                              痛点 {idx + 1}：
                            </Text>
                            <Text style={{ marginLeft: 6 }}>{weakness}</Text>
                          </List.Item>
                        )}
                      />

                      <Divider style={{ margin: '16px 0' }} />

                      <Row gutter={16}>
                        <Col span={12}>
                          <Text strong>✅ 已具备核心技能：</Text>
                          <div style={{ marginTop: 8 }}>
                            {matchResult.matched_skills.map((s: string) => (
                              <Tag color="green" key={s}>{s}</Tag>
                            ))}
                          </div>
                        </Col>
                        <Col span={12}>
                          <Text strong>⚠️ 岗位要求技能缺口 (Skill Gaps)：</Text>
                          <div style={{ marginTop: 8 }}>
                            {matchResult.missing_skills.length > 0 ? (
                              matchResult.missing_skills.map((s: string) => (
                                <Tag color="red" key={s}>{s}</Tag>
                              ))
                            ) : (
                              <Text type="secondary">核心技术要求已基本覆盖</Text>
                            )}
                          </div>
                        </Col>
                      </Row>

                      <Divider orientation="left" style={{ margin: '16px 0' }}>
                        <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
                        基于 STAR 原则的量化对比重写示范
                      </Divider>
                      <List
                        dataSource={matchResult.star_optimizations}
                        renderItem={(opt: any, idx) => (
                          <List.Item>
                            <Card type="inner" title={`优化示范 ${idx + 1}`} style={{ width: '100%' }}>
                              <Paragraph>
                                <Text strong style={{ color: '#cf1322' }}>【原句不足诊断】</Text>
                                <Text delete style={{ marginLeft: 8 }}>{opt.original_snippet}</Text>
                              </Paragraph>
                              <Paragraph>
                                <Text type="secondary">痛点原因：{opt.weakness_analysis}</Text>
                              </Paragraph>
                              <div style={{ backgroundColor: '#f6ffed', padding: 12, border: '1px solid #b7eb8f', borderRadius: 6 }}>
                                <Text strong style={{ color: '#389e0d' }}>{opt.star_rewrite}</Text>
                                <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 8 }}>
                                  [S] {opt.situation} | [T] {opt.task} | [A] {opt.action} | [R] {opt.result}
                                </div>
                              </div>
                            </Card>
                          </List.Item>
                        )}
                      />
                    </Card>
                  </div>
                )}
              </div>
            )
          },
          {
            key: 'interview',
            label: (
              <span>
                <BranchesOutlined /> GraphRAG 技术模拟面试 & 心理疏导
              </span>
            ),
            children: (
              <div>
                <Row gutter={16} style={{ marginBottom: 16 }} align="middle">
                  <Col span={12}>
                    <Radio.Group
                      value={interviewMode}
                      onChange={e => setInterviewMode(e.target.value)}
                      buttonStyle="solid"
                    >
                      <Radio.Button value="mock_interview">
                        <BranchesOutlined /> GraphRAG 技能拓扑递进模拟面试
                      </Radio.Button>
                      <Radio.Button value="casual_chat">
                        <BulbOutlined /> 重点实验室就业导师心理梳理与闲聊
                      </Radio.Button>
                    </Radio.Group>
                  </Col>
                  <Col span={12} style={{ textAlign: 'right' }}>
                    <Tag color="cyan">
                      {interviewMode === 'mock_interview'
                        ? '依托 GraphRAG 实体链路多跳推理'
                        : '重点实验室关怀模式 · 情绪接纳与谈薪话术'}
                    </Tag>
                  </Col>
                </Row>

                <Card
                  bodyStyle={{ height: '480px', overflowY: 'auto', padding: '16px' }}
                  style={{ marginBottom: 16 }}
                >
                  {chatMessages.map((msg, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                        marginBottom: 16
                      }}
                    >
                      <div
                        style={{
                          maxWidth: '80%',
                          padding: '12px 16px',
                          borderRadius: '8px',
                          backgroundColor: msg.role === 'user' ? '#1890ff' : '#f5f5f5',
                          color: msg.role === 'user' ? '#fff' : '#000'
                        }}
                      >
                        <div style={{ fontWeight: 'bold', marginBottom: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span>{msg.role === 'user' ? '候选人 (同学)' : (interviewMode === 'mock_interview' ? '大厂技术考官' : '就业心理关怀导师')}</span>
                          {msg.score && <Tag color="green">{msg.score} 分</Tag>}
                        </div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>

                        {msg.graphPath && (
                          <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px dashed #d9d9d9', fontSize: 12, color: '#096dd9' }}>
                            <BranchesOutlined style={{ marginRight: 4 }} />
                            GraphRAG 推理路径: {msg.graphPath}
                          </div>
                        )}
                      </div>

                      {msg.feedback && (
                        <div style={{ maxWidth: '80%', marginTop: 6 }}>
                          <Alert
                            message={`考官复盘点评: ${msg.feedback}`}
                            type="info"
                            showIcon
                          />
                        </div>
                      )}
                    </div>
                  ))}
                  {interviewLoading && (
                    <div style={{ textAlign: 'center', padding: '10px' }}>
                      <Spin tip="考官正在基于 GraphRAG 技能拓扑树组织多跳追问..." />
                    </div>
                  )}
                </Card>

                <div style={{ display: 'flex', gap: 12 }}>
                  <TextArea
                    rows={2}
                    value={userInput}
                    onChange={e => setUserInput(e.target.value)}
                    onPressEnter={e => {
                      if (!e.shiftKey) {
                        e.preventDefault();
                        handleSendChat();
                      }
                    }}
                    placeholder={
                      interviewMode === 'mock_interview'
                        ? '请输入你的技术回答（可从高并发痛点、底层机制与量化指标深入阐述）...'
                        : '向导师倾诉求职中的困惑、考研调剂心路、面试失利挫折感或薪资谈判问题...'
                    }
                  />
                  <Button
                    type="primary"
                    size="large"
                    icon={<SendOutlined />}
                    onClick={handleSendChat}
                    loading={interviewLoading}
                    style={{ height: 'auto' }}
                  >
                    发送
                  </Button>
                </div>
              </div>
            )
          },
          {
            key: 'prompt_workshop',
            label: (
              <span>
                <CodeOutlined /> 提示词工坊 (用户自由查看/手写配置)
              </span>
            ),
            children: (
              <div>
                <Alert
                  message="用户自主提示词工程工坊 (Prompt Workshop)"
                  description="拒绝死板黑盒！用户可自由查看、修改并在线重写系统的 4 大黄金提示词。保存后将即刻作用于模拟面试、简历诊断与心理辅导中。"
                  type="success"
                  showIcon
                  style={{ marginBottom: 16 }}
                />

                <Row gutter={16}>
                  <Col span={7}>
                    <Card title="选择待配置的系统提示词" size="small">
                      <List
                        dataSource={Object.values(promptTemplates)}
                        renderItem={(tpl: any) => (
                          <List.Item
                            onClick={() => handleSelectPrompt(tpl.key)}
                            style={{
                              cursor: 'pointer',
                              backgroundColor: selectedPromptKey === tpl.key ? '#e6f7ff' : 'transparent',
                              padding: '10px 12px',
                              borderRadius: 6,
                              marginBottom: 6,
                              border: selectedPromptKey === tpl.key ? '1px solid #91d5ff' : '1px solid #f0f0f0'
                            }}
                          >
                            <List.Item.Meta
                              title={
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                  <Text strong>{tpl.name}</Text>
                                  {tpl.is_custom && <Tag color="orange">已自定义</Tag>}
                                </div>
                              }
                              description={
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {tpl.category}
                                </Text>
                              }
                            />
                          </List.Item>
                        )}
                      />
                    </Card>
                  </Col>

                  <Col span={17}>
                    <Card
                      title={
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span>
                            正在编辑: <Text code>{promptTemplates[selectedPromptKey]?.name || selectedPromptKey}</Text>
                          </span>
                          <Space>
                            <Button icon={<UndoOutlined />} onClick={handleResetPrompt}>
                              恢复默认提示词
                            </Button>
                            <Button type="primary" icon={<SaveOutlined />} onClick={handleSavePrompt}>
                              保存并立即生效
                            </Button>
                          </Space>
                        </div>
                      }
                      size="small"
                    >
                      <Paragraph type="secondary" style={{ marginBottom: 12 }}>
                        {promptTemplates[selectedPromptKey]?.description}
                      </Paragraph>

                      <div style={{ marginBottom: 8 }}>
                        <Text strong>可用的动态占位变量：</Text>
                        {(promptTemplates[selectedPromptKey]?.variables || []).map((v: string) => (
                          <Tag color="geekblue" key={v}>{`{${v}}`}</Tag>
                        ))}
                      </div>

                      <TextArea
                        rows={16}
                        value={editingPromptText}
                        onChange={e => setEditingPromptText(e.target.value)}
                        style={{ fontFamily: 'Consolas, monospace', fontSize: 13 }}
                      />
                    </Card>
                  </Col>
                </Row>
              </div>
            )
          }
        ]}
      />
    </div>
  );
};

export default CareerCenter;
