/**
 * 高校智能求职面试辅导与简历优化 Agent 平台
 * 研发单位：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室
 * 核心支柱：
 * 1. 简历严谨诊断与 STAR 针对性优化 (精准挑刺指出痛点、能力雷达与量化重构)
 * 2. 大厂技术面试官模拟面试 (逐轮打分 + 递进追问)
 * 3. 提示词工坊 (用户可自由查看、修改、测试与替换系统提示词)
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
  Statistic,
  Select,
  Tooltip
} from 'antd';
import {
  FileTextOutlined,
  CommentOutlined,
  CheckCircleOutlined,
  RocketOutlined,
  SendOutlined,
  CodeOutlined,
  ExclamationCircleOutlined,
  UndoOutlined,
  SaveOutlined,
  ReloadOutlined,
  RadarChartOutlined
} from '@ant-design/icons';
import { authFetch } from '@/services/auth';
import { getFileList, getFileText, getKnowledgeBaseList } from '@/services';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

interface CareerCenterProps {
  tab?: 'resume_doctor' | 'interview' | 'prompt_workshop';
}

export const CareerCenter: React.FC<CareerCenterProps> = ({ tab }) => {
  const [activeTab, setActiveTab] = useState(tab || 'resume_doctor');

  useEffect(() => {
    if (tab) setActiveTab(tab);
  }, [tab]);

  // ==================== 1. 简历严谨诊断与 STAR 优化 ====================
  const [resumeText, setResumeText] = useState('');

  const [jdText, setJdText] = useState(
    `【一线大厂 · 大模型智能体与高并发后端架构师】
岗位职责：
1. 负责多智能体协同运行时与 LangGraph 分层状态机编排；
2. 深度掌握 Python, FastAPI, Redis 缓存击穿治理与分布式锁，具备 1000+ QPS 极限高并发抗压调优经验；
3. 负责企业级 Hybrid RAG 混合检索管线构建，精通 jieba BM25 关键词召回、pgvector 向量召回融合及重排器调优。
任职要求：计算机或软件工程相关专业硕士，具有扎实工程落地能力，要求具备死循环熔断与异常降级闭环思维。`
  );

  const [resumeFiles, setResumeFiles] = useState<Array<{ id: string; name: string; chunks: number }>>([]);
  const [selectedResumeId, setSelectedResumeId] = useState('');
  const [resumeMeta, setResumeMeta] = useState<{ name: string; chars: number; chunks: number } | null>(null);
  const [resumeLoading, setResumeLoading] = useState(false);

  const loadResumeText = async (fileId: string) => {
    setResumeLoading(true);
    try {
      const res = await getFileText(fileId);
      const data = (res as any).data;
      setResumeText(data.text || '');
      setSelectedResumeId(fileId);
      setResumeMeta({ name: data.name, chars: data.char_count, chunks: data.chunk_count });
    } catch (err) {
      console.error('加载完整简历失败', err);
      message.error('加载完整简历失败，可手动粘贴');
    } finally {
      setResumeLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const initRealResumes = async () => {
      try {
        const kbRes = await getKnowledgeBaseList();
        const kbs = Array.isArray(kbRes) ? kbRes : (kbRes as any).data || [];
        const kb = kbs.find((item: any) => item.id === 'kb_real_resumes')
          || kbs.find((item: any) => String(item.name || '').includes('真实简历'));
        if (!kb) return;
        const fileRes = await getFileList(kb.id);
        const files = Array.isArray(fileRes) ? fileRes : (fileRes as any).data || [];
        const pdfs = files.filter((f: any) => String(f.name || '').toLowerCase().endsWith('.pdf'));
        const list = (pdfs.length ? pdfs : files).map((f: any) => ({
          id: f.id,
          name: f.name,
          chunks: f.chunk_count ?? f.chunkCount ?? 0,
        }));
        if (cancelled) return;
        setResumeFiles(list);
        if (list.length > 0) {
          await loadResumeText(list[0].id);
        }
      } catch (err) {
        console.error('初始化真实简历失败', err);
      }
    };
    initRealResumes();
    return () => { cancelled = true; };
  }, []);

  const [matchLoading, setMatchLoading] = useState(false);
  const [matchResult, setMatchResult] = useState<any>(null);

  const handleDiagnoseResume = async () => {
    if (!resumeText.trim() || !jdText.trim()) {
      message.warning('请先输入学生简历与目标岗位 JD');
      return;
    }
    setMatchLoading(true);
    try {
      const resp = await authFetch('/api/v1/career/match', {
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

  // ==================== 2. 大厂技术面试官模拟面试 ====================
  const [chatMessages, setChatMessages] = useState<Array<{
    role: string;
    content: string;
    feedback?: string;
    score?: number;
  }>>([
    {
      role: 'interviewer',
      content: '同学你好！我是辽宁大学重点实验室技术面试官。我看你简历里写到使用 Redis + Lua 脚本实现了滑动窗口限流器并支撑 1000+ QPS。请你结合底层机制谈谈：为什么选择 ZSet 滑动窗口而不是固定窗口计数器？在高并发多实例环境下，Lua 脚本是如何保证原子性以防超买的？'
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
      const resp = await authFetch('/api/v1/career/interview/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: newMsgs.map(m => ({ role: m.role, content: m.content })),
          mode: 'mock_interview',
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
          score: data.score_for_last_answer
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
      const resp = await authFetch('/api/v1/career/prompts');
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
      const resp = await authFetch('/api/v1/career/prompts', {
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
      const resp = await authFetch('/api/v1/career/prompts/reset', {
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
    <div style={{ padding: '24px', maxWidth: '1700px', margin: '0 auto' }}>
      <div style={{ marginBottom: '20px' }}>
        <Space direction="vertical" size={2}>
          <Title level={3} style={{ margin: 0 }}>
            <RocketOutlined style={{ color: '#1890ff', marginRight: 10 }} />
            高校智能求职面试辅导与简历优化 Agent 平台
          </Title>
          <Text type="secondary">
            研发生态：辽宁大学 · 辽宁省公共舆情与网络安全信息系统重点实验室 | 大厂 TL 简历诊断、模拟面试与自定义提示词工程
          </Text>
        </Space>
      </div>

      <Tabs
        activeKey={activeTab}
        type="card"
        tabBarStyle={{ display: 'none' }}
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

                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="这里加载的是整篇简历原文，不是 RAG 检索片段"
                  description="简历诊断需要完整上下文，因此系统从你上传的真实简历中按 chunk 顺序还原全文；模拟面试和知识库问答才会按 chunk 检索。"
                />

                <Row gutter={20}>
                  <Col xs={24} xl={14}>
                    <Card
                      title={
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                          <span>📄 学生简历 · 完整原文</span>
                          <Space wrap>
                            <Select
                              value={selectedResumeId || undefined}
                              onChange={(value) => loadResumeText(value)}
                              options={resumeFiles.map((f) => ({ value: f.id, label: `${f.name}（${f.chunks} chunks）` }))}
                              placeholder="选择真实简历"
                              style={{ width: 320 }}
                              showSearch
                              optionFilterProp="label"
                              loading={resumeLoading}
                            />
                            <Button
                              size="small"
                              icon={<ReloadOutlined />}
                              onClick={() => selectedResumeId && loadResumeText(selectedResumeId)}
                              loading={resumeLoading}
                            >
                              重新加载
                            </Button>
                          </Space>
                        </div>
                      }
                      size="small"
                    >
                      {resumeMeta && (
                        <Text type="secondary">
                          已加载 {resumeMeta.name} · {resumeMeta.chars} 字 · {resumeMeta.chunks} 个 chunk
                        </Text>
                      )}
                      <Spin spinning={resumeLoading}>
                        <TextArea
                          rows={26}
                          value={resumeText}
                          onChange={e => setResumeText(e.target.value)}
                          placeholder="未自动加载到简历；可在此粘贴完整简历..."
                          style={{ minHeight: 560, marginTop: 8, fontFamily: 'Consolas, monospace', fontSize: 13, lineHeight: 1.7 }}
                        />
                      </Spin>
                    </Card>
                  </Col>
                  <Col xs={24} xl={10}>
                    <Card title="🎯 目标企业岗位 JD (任职要求/硬性门槛)" size="small">
                      <TextArea
                        rows={26}
                        value={jdText}
                        onChange={e => setJdText(e.target.value)}
                        placeholder="粘贴目标岗位招聘要求..."
                        style={{ minHeight: 560, marginTop: 8, fontFamily: 'Consolas, monospace', fontSize: 13, lineHeight: 1.7 }}
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
            label: <span>模拟面试</span>,
            children: (
              <div>
                <div style={{ marginBottom: 16 }}>
                  <Tag color="cyan">大厂技术面试官 · 逐轮打分与递进追问</Tag>
                </div>

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
                          <span>{msg.role === 'user' ? '候选人 (同学)' : '大厂技术面试官'}</span>
                          {msg.score && <Tag color="green">{msg.score} 分</Tag>}
                        </div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>

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
                      <Spin tip="面试官正在点评并准备下一问..." />
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
                    placeholder="请输入你的技术回答（可从高并发痛点、底层机制与量化指标深入阐述）..."
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
                  description="拒绝死板黑盒！用户可自由查看、修改并在线重写系统的 3 大提示词：模拟面试、简历诊断、STAR 润色。保存后即刻生效。"
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
