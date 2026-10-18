/**
 * 智能对话页面
 */

import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Card, Select, Button, Input, Spin, Collapse, Tag, message, Segmented, Slider, Divider, Space, Tooltip, Modal, Switch, Typography, Popover } from 'antd';
import {
  SendOutlined,
  StopOutlined,
  EditOutlined,
  ReloadOutlined,
  LinkOutlined,
  RobotOutlined,
  MessageOutlined,
  SettingOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import { PageHeader, MarkdownRenderer, EmptyState } from '@/components/common';
import { getKnowledgeBaseList, getModelList, rewriteQuery, createChatStream } from '@/services';
import { useAppStore, useChatStore } from '@/stores';
import type { ChatMessage, AgentStep, Citation, KnowledgeBase, ModelInfo } from '@/types';
import styles from './Chat.module.css';

const { Panel } = Collapse;
const { Paragraph } = Typography;

interface ChatConfig {
  kbIds: string[];
  topK: number;
  scoreThreshold: number;
  rerankEnabled: boolean;
  rerankScoreThreshold: number;
  rerankModelId?: string;
  // 新增检索配置
  searchMode: 'vector' | 'fulltext' | 'hybrid';
  vectorWeight: number;
  bm25Weight: number;
  rerankTopK: number;
  contextWindow: number;
}

const Chat: React.FC = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const urlKbId = searchParams.get('kb_id');

  const { knowledgeBases, setKnowledgeBases, models, setModels } = useAppStore();
  
  // 派生模型列表
  const rerankModels = (models || []).filter((m) => m.type === 'rerank');
  const chatModels = (models || []).filter((m) => m.type === 'llm' || m.type === 'vlm');
  
  // 从 store 中只解构需要的变量，避免解构 messages 等已被本地状态替代的变量
  const {
    selectedModel,
    setSelectedModel,
    // isGenerating, // Removed: 使用新的分离状态
    // setIsGenerating, // Removed
    // abortController, // Removed
    // setAbortController, // Removed
    isAgentGenerating,
    setAgentGenerating,
    isNormalGenerating,
    setNormalGenerating,
    agentAbortController,
    setAgentAbortController,
    normalAbortController,
    setNormalAbortController,
    agentMessages,
    setAgentMessages,
    normalMessages,
    setNormalMessages,
  } = useChatStore();

  const [inputValue, setInputValue] = useState('');
  const [rewriting, setRewriting] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);
  
  // 详情弹窗状态
  const [citationModalVisible, setCitationModalVisible] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);

  // 模式状态
  const [chatMode, setChatMode] = useState<'normal' | 'agent'>('agent');
  
  // 当前模式的衍生状态
  const isGenerating = chatMode === 'normal' ? isNormalGenerating : isAgentGenerating;
  const setIsGenerating = (val: boolean) => {
    if (chatMode === 'normal') setNormalGenerating(val);
    else setAgentGenerating(val);
  };
  const abortController = chatMode === 'normal' ? normalAbortController : agentAbortController;
  const setAbortController = (ctrl: (() => void) | null) => {
    if (chatMode === 'normal') setNormalAbortController(ctrl);
    else setAgentAbortController(ctrl);
  };

  // 当前显示的 messages 引用
  const messages = chatMode === 'normal' ? normalMessages : agentMessages;
  
  // 包装 addMessage 和 updateMessage 以支持独立状态
  const addMessage = (msg: ChatMessage) => {
    if (chatMode === 'normal') {
      setNormalMessages(prev => [...prev, msg]);
    } else {
      setAgentMessages(prev => [...prev, msg]);
    }
  };
  
  const updateMessage = (id: string, updates: Partial<ChatMessage>) => {
    const setter = chatMode === 'normal' ? setNormalMessages : setAgentMessages;
    setter(prev => prev.map(msg => msg.id === id ? { ...msg, ...updates } : msg));
  };
  
  const clearMessages = () => {
    if (chatMode === 'normal') {
      setNormalMessages([]);
    } else {
      setAgentMessages([]);
    }
  };

  const [normalConfig, setNormalConfig] = useState<ChatConfig>({
    kbIds: [],
    topK: 3,
    scoreThreshold: 0.3,
    rerankEnabled: true,
    rerankScoreThreshold: 0.0,
    rerankModelId: undefined,
    // 新增检索配置
    searchMode: 'hybrid',
    vectorWeight: 0.7,
    bm25Weight: 0.3,
    rerankTopK: 20,
    contextWindow: 1,
  });

  const [agentConfig, setAgentConfig] = useState<ChatConfig>({
    kbIds: [],
    topK: 3,
    scoreThreshold: 0.3,
    rerankEnabled: true,
    rerankScoreThreshold: 0.0,
    rerankModelId: undefined,
    // 新增检索配置
    searchMode: 'hybrid',
    vectorWeight: 0.7,
    bm25Weight: 0.3,
    rerankTopK: 20,
    contextWindow: 1,
  });

  // 获取当前模式的配置
  const currentConfig = chatMode === 'normal' ? normalConfig : agentConfig;
  const setCurrentConfig = (newConfig: Partial<ChatConfig>) => {
    if (chatMode === 'normal') {
      setNormalConfig({ ...normalConfig, ...newConfig });
    } else {
      setAgentConfig({ ...agentConfig, ...newConfig });
    }
  };

  // 校验并自动选择模型
  useEffect(() => {
    if (chatModels.length > 0) {
        const exists = chatModels.some(m => m.id === selectedModel);
        // 如果当前选中的模型不存在于列表中，或者当前没有选中模型，则默认选择第一个
        if (!exists || !selectedModel) {
            console.log('Auto-selecting LLM model:', chatModels[0].name);
            setSelectedModel(chatModels[0].id);
        }
    }
  }, [models, selectedModel]); // 依赖 models (chatModels 变化) 和 selectedModel

  useEffect(() => {
      if (rerankModels.length > 0) {
          const exists = rerankModels.some(m => m.id === currentConfig.rerankModelId);
          if (!exists) {
              console.log('Auto-selecting Rerank model:', rerankModels[0].name);
              // 同时更新 normal 和 agent 配置，确保一致性 (或者仅更新当前? 为了简单，更新当前即可，但 currentConfig 是派生的)
              // 这里我们需要更新 state，而不是 currentConfig 变量
              const defaultId = rerankModels[0].id;
              setNormalConfig(prev => ({ ...prev, rerankModelId: defaultId }));
              setAgentConfig(prev => ({ ...prev, rerankModelId: defaultId }));
          }
      }
  }, [models, currentConfig.rerankModelId]);

  // 初始化加载
  useEffect(() => {
    const init = async () => {
      try {
        const [kbRes, modelRes] = await Promise.all([
          getKnowledgeBaseList(),
          getModelList(),
        ]);

        const kbData = Array.isArray(kbRes) ? kbRes : (kbRes as any).data || [];
        setKnowledgeBases(Array.isArray(kbData) ? kbData : []);

        const modelData = Array.isArray(modelRes) ? modelRes : (modelRes as any).data || [];
        
        // 适配后端数据结构 (model_type -> type)
        const adaptedModels = (modelData as any[]).map(m => ({
          ...m,
          id: m.id,
          name: m.name,
          // 优先使用 model_type，如果不存在则使用 type，并转为小写
          type: (m.model_type || m.type || 'llm').toLowerCase(),
          provider: m.provider || 'Custom',
          description: m.description || m.model_name
        }));
        
        setModels(adaptedModels);

        // 设置默认 LLM 模型
        const llmModels = adaptedModels.filter((m: ModelInfo) => m.type === 'llm' || m.type === 'vlm');
        if (llmModels.length > 0 && !selectedModel) {
          setSelectedModel(llmModels[0].id);
        }

        // 设置默认 Rerank 模型
        const rerankModels = adaptedModels.filter((m: ModelInfo) => m.type === 'rerank');
        if (rerankModels.length > 0) {
           const defaultRerankId = rerankModels[0].id;
           setNormalConfig(prev => ({ ...prev, rerankModelId: defaultRerankId }));
           setAgentConfig(prev => ({ ...prev, rerankModelId: defaultRerankId }));
        }

        // URL 参数预选知识库 (仅针对当前默认模式 - Agent)
        if (urlKbId && (Array.isArray(kbData) ? kbData : []).some((kb: KnowledgeBase) => kb.id === urlKbId)) {
          setAgentConfig(prev => ({ ...prev, kbIds: [urlKbId] }));
          setNormalConfig(prev => ({ ...prev, kbIds: [urlKbId] }));
        }
      } catch (error) {
        console.error('初始化失败:', error);
      }
    };
    init();
  }, []);

  // 处理滚动事件
  const handleScroll = () => {
    if (messagesContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = messagesContainerRef.current;
      // 如果距离底部小于 100px，则允许自动滚动
      const isBottom = scrollHeight - scrollTop - clientHeight < 100;
      shouldAutoScrollRef.current = isBottom;
    }
  };

  // 自动滚动到底部
  useEffect(() => {
    if ((isGenerating || messages.length > 0) && shouldAutoScrollRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isGenerating]);


  // 处理问题改写
  const handleRewrite = async () => {
    if (!inputValue.trim()) return;

    setRewriting(true);
    try {
      const response = await rewriteQuery({ query: inputValue.trim(), model_id: selectedModel });
      setInputValue(response.data.rewritten_query);
      message.success('问题改写成功');
    } catch (error) {
      message.error('改写失败');
    } finally {
      setRewriting(false);
    }
  };

  // 生成消息 ID
  const generateMessageId = () => `msg_${Date.now()}_${Math.random().toString(36).slice(2)}`;

  // 发送消息
  const handleSend = async () => {
    if (!inputValue.trim() || isGenerating) return;

    // 发送新消息时强制滚动到底部
    shouldAutoScrollRef.current = true;

    // 捕获当前的 chatMode，供闭包内使用
    const capturedChatMode = chatMode;

    const userMessage: ChatMessage = {
      id: generateMessageId(),
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date().toISOString(),
    };

    const assistantMessage: ChatMessage = {
      id: generateMessageId(),
      role: 'assistant',
      content: '',
      agentSteps: [],
      citations: [],
      timestamp: new Date().toISOString(),
      isStreaming: true,
    };

    addMessage(userMessage);
    addMessage(assistantMessage);
    setInputValue('');
    setIsGenerating(true);

    // 平滑输出控制
    let accumulatedContent = '';
    
    // 动画帧 ID
    let animationFrameId: number;

    const updateMessageContent = (content: string) => {
        const setter = capturedChatMode === 'normal' ? setNormalMessages : setAgentMessages;
        setter(prev => prev.map(msg => msg.id === assistantMessage.id ? { 
            ...msg, 
            content: content 
        } : msg));
    };

    const { abort } = createChatStream(
      {
        messages: [...messages, userMessage].map((m) => ({
          role: m.role,
          content: m.content,
        })),
        kb_ids: currentConfig.kbIds,
        stream: true,
        mode: chatMode,
        top_k: currentConfig.topK,
        score_threshold: currentConfig.scoreThreshold,
        model_id: selectedModel,
        rerank_enabled: currentConfig.rerankEnabled,
        rerank_score_threshold: currentConfig.rerankScoreThreshold,
        rerank_model_id: currentConfig.rerankModelId,
        // 新增检索参数
        search_mode: currentConfig.searchMode,
        vector_weight: currentConfig.vectorWeight,
        bm25_weight: currentConfig.bm25Weight,
        rerank_top_k: currentConfig.rerankTopK,
        context_window: currentConfig.contextWindow,
      },
      {
        onAgentThought: (data) => {
            const step: AgentStep = {
              type: data.step,
              content: data.content,
              timestamp: new Date().toISOString(),
              duration: data.duration, // 后端返回的耗时
              cost: data.cost, // 总耗时
            };
            
            // 获取当前最新的消息列表
            // 注意：这里不能直接用 messages 闭包，需要用 setXxx 的回调或者 ref
            // 但为了简单，我们重新实现 updateMessage 的逻辑
            // 使用 capturedChatMode 来确保回调更新的是发起请求时的模式
            const setter = capturedChatMode === 'normal' ? setNormalMessages : setAgentMessages;
            setter(prev => {
                const msgs = [...prev];
                const msgIndex = msgs.findIndex(m => m.id === assistantMessage.id);
                if (msgIndex > -1) {
                    const msg = { ...msgs[msgIndex] };
                    msg.agentSteps = [...(msg.agentSteps || []), step];
                    msgs[msgIndex] = msg;
                }
                return msgs;
            });
          },
          onRagResult: (data) => {
             // 同样的逻辑更新 citations
            const setter = capturedChatMode === 'normal' ? setNormalMessages : setAgentMessages;
            setter(prev => {
                const msgs = [...prev];
                const msgIndex = msgs.findIndex(m => m.id === assistantMessage.id);
                if (msgIndex > -1) {
                    msgs[msgIndex] = { 
                      ...msgs[msgIndex], 
                      citations: data.citations,
                      original_citations: data.original_citations
                    };
                }
                return msgs;
            });
          },
        onAnswerChunk: (data) => {
          accumulatedContent += data.content;
          
          // 使用 requestAnimationFrame 进行节流，避免过于频繁的 setState
          if (!animationFrameId) {
              animationFrameId = requestAnimationFrame(() => {
                  updateMessageContent(accumulatedContent);
                  animationFrameId = 0;
              });
          }
        },
        onDone: () => {
          if (animationFrameId) {
             cancelAnimationFrame(animationFrameId);
             animationFrameId = 0;
          }
          
          // 确保最后一次内容被更新
          updateMessageContent(accumulatedContent);

          const finish = () => {
             // 这里的 updateMessage 依赖 chatMode 状态，如果用户切换了模式，会导致更新错误的消息列表
             // 应该使用 capturedChatMode
             const setter = capturedChatMode === 'normal' ? setNormalMessages : setAgentMessages;
             setter(prev => prev.map(msg => msg.id === assistantMessage.id ? { 
                 ...msg, 
                 content: accumulatedContent,
                 isStreaming: false 
             } : msg));

             // 清理生成状态
             if (capturedChatMode === 'normal') {
                 setNormalGenerating(false);
                 setNormalAbortController(null);
             } else {
                 setAgentGenerating(false);
                 setAgentAbortController(null);
             }
          };

          finish();
        },
        onError: (error) => {
          if (animationFrameId) {
             cancelAnimationFrame(animationFrameId);
             animationFrameId = 0;
          }
          console.error('Chat Error:', error);
          
          const setter = capturedChatMode === 'normal' ? setNormalMessages : setAgentMessages;
          setter(prev => prev.map(msg => msg.id === assistantMessage.id ? { 
             ...msg, 
             content: `发生错误，请重试: ${error.message || '未知错误'}`,
             error: error.message,
             isStreaming: false 
          } : msg));

          if (capturedChatMode === 'normal') {
             setNormalGenerating(false);
             setNormalAbortController(null);
          } else {
             setAgentGenerating(false);
             setAgentAbortController(null);
          }
        },
      }
    );

    // 设置 controller
    if (chatMode === 'normal') {
        setNormalAbortController(() => abort);
    } else {
        setAgentAbortController(() => abort);
    }
  };

  // 停止生成
  const handleStop = () => {
    // 停止当前的 controller
    if (chatMode === 'normal') {
        normalAbortController?.();
        setNormalGenerating(false);
        setNormalAbortController(null);
    } else {
        agentAbortController?.();
        setAgentGenerating(false);
        setAgentAbortController(null);
    }
  };

  // 重试
  const handleRetry = () => {
    if (messages.length < 2) return;
    const lastUserMessage = [...messages].reverse().find((m) => m.role === 'user');
    if (lastUserMessage) {
      setInputValue(lastUserMessage.content);
      clearMessages();
      messages.slice(0, -2).forEach((m) => addMessage(m));
    }
  };

  // 渲染 Agent 思考步骤
  const renderAgentSteps = (steps: AgentStep[]) => {
    return (
      <Collapse ghost size="small" className={styles.agentSteps} defaultActiveKey={['steps']}>
        <Panel 
          header={
            <Space>
              <RobotOutlined />
              <span>思考过程</span>
              {steps.length > 0 && steps[steps.length - 1].cost && (
                  <span style={{ color: '#888', fontSize: '12px', marginLeft: '8px' }}>
                      总耗时: {Number(steps[steps.length - 1].cost).toFixed(2)}s
                  </span>
              )}
            </Space>
          } 
          key="steps"
        >
          <div className={styles.stepList}>
            {steps.map((step, index) => (
              <div key={index} className={styles.stepItem}>
                <Tag color={
                  step.type === 'thinking' ? 'blue' :
                  step.type === 'action' ? 'orange' :
                  step.type === 'decision' ? 'green' :
                  step.type === 'response' ? 'purple' : 
                  step.type === 'observation' ? 'cyan' :
                  step.type === 'reflection' ? 'red' : 'default'
                }>
                  {step.type === 'thinking' ? '分析意图' :
                   step.type === 'action' ? '调用工具' :
                   step.type === 'decision' ? '决策判断' :
                   step.type === 'response' ? '生成回复' : 
                   step.type === 'observation' ? '观察结果' :
                   step.type === 'reflection' ? '自我反思' : step.type}
                </Tag>
                <div className={styles.stepContent} style={{ flex: 1, minWidth: 0 }}>
                    <Paragraph 
                        ellipsis={{ 
                            rows: 2, 
                            expandable: true, 
                            symbol: '展开',
                            onExpand: (e, info) => console.log('Expand:', info)
                        }}
                        style={{ marginBottom: 0, color: 'inherit' }}
                        title={undefined} // 禁用原生 title 提示，避免重复
                    >
                        {step.content}
                    </Paragraph>
                </div>
                {step.duration && (
                    <span style={{ color: '#aaa', fontSize: '12px', marginLeft: '8px', flexShrink: 0 }}>
                        {Number(step.duration).toFixed(2)}s
                    </span>
                )}
              </div>
            ))}
          </div>
        </Panel>
      </Collapse>
    );
  };

  // 渲染引用来源
  const renderCitations = (citations: Citation[], title: string = "参考来源") => {
    if (citations.length === 0) return null;

    return (
      <Collapse ghost className={styles.citations}>
        <Panel
          header={`${title} (${citations.length})`}
          key="citations"
          extra={<LinkOutlined />}
        >
          <div className={styles.citationList}>
            {citations.map((citation, index) => (
              <div key={index} className={styles.citationItem}>
                <div className={styles.citationHeader}>
                  <Tag color="orange">{citation.kb_name || '知识库'}</Tag>
                  <Tooltip title={citation.fileId ? "点击查看文件详情" : "文件 ID 未知"}>
                      <Tag 
                        color="blue" 
                        style={{ cursor: citation.fileId ? 'pointer' : 'default' }}
                        onClick={() => {
                            if (citation.fileId && citation.kb_id) {
                                window.open(`/kb/${citation.kb_id}/preview/${citation.fileId}`, '_blank');
                            } else if (citation.fileId && currentConfig.kbIds.length === 1) {
                                window.open(`/kb/${currentConfig.kbIds[0]}/preview/${citation.fileId}`, '_blank');
                            }
                        }}
                      >
                        {citation.fileName || '未知文件'}
                      </Tag>
                  </Tooltip>
                  {citation.location && citation.location !== '未知位置' && (
                    <Tag>{citation.location}</Tag>
                  )}
                  <Tag color="green">相似度: {citation.score.toFixed(3)}</Tag>
                  {citation.rerank_score !== undefined && citation.rerank_score !== null && (
                      <Tag color="purple">Rerank: {citation.rerank_score.toFixed(3)}</Tag>
                  )}
                </div>
                {citation.content && (
                  <div 
                    className={styles.citationContent}
                    onClick={() => {
                        setSelectedCitation(citation);
                        setCitationModalVisible(true);
                    }}
                    style={{ cursor: 'pointer' }}
                    title="点击查看完整内容"
                  >
                    {(() => {
                        const imgMatch = citation.content ? citation.content.match(/\[图片:\s*([^\]]+)\]/) : null;
                        const imgPath = citation.image_path || (imgMatch ? imgMatch[1].trim() : null);

                        if (imgPath) {
                            const cleanImg = imgPath.replace(/^\/?static\/images\//, '').replace(/^\/+/, '');
                            return (
                                <div>
                                    <div style={{ textAlign: 'center', marginBottom: 6 }}>
                                        <img 
                                            src={`http://localhost:8000/static/images/${cleanImg}`} 
                                            alt="引用图片" 
                                            style={{ maxWidth: '100%', maxHeight: '160px', objectFit: 'contain', borderRadius: 4 }}
                                            onError={(e) => {
                                                (e.target as HTMLElement).style.display = 'none';
                                            }}
                                        />
                                    </div>
                                    <div style={{
                                        display: '-webkit-box',
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: 'vertical',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        wordBreak: 'break-word',
                                        fontSize: '12px'
                                    }}>
                                        {citation.content}
                                    </div>
                                </div>
                            );
                        }

                        return (
                            <div style={{
                                display: '-webkit-box',
                                WebkitLineClamp: 3,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                wordBreak: 'break-word'
                            }}>
                                {citation.content}
                            </div>
                        );
                    })()}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Panel>
      </Collapse>
    );
  };

  // 渲染消息
  const renderMessage = (msg: ChatMessage) => {
    const isUser = msg.role === 'user';

    return (
      <div
        key={msg.id}
        className={`${styles.messageWrapper} ${isUser ? styles.userMessage : styles.assistantMessage}`}
      >
        <div 
          className={styles.messageContent}
          style={!isUser ? { width: '860px', maxWidth: '100%', minWidth: 0, boxSizing: 'border-box' } : { maxWidth: '75%', minWidth: 0 }}
        >
          {!isUser && msg.agentSteps && msg.agentSteps.length > 0 && (
            <div style={{ width: '100%' }}>
              {renderAgentSteps(msg.agentSteps)}
            </div>
          )}

          <div 
            className={styles.messageBubble}
            style={!isUser ? { width: '100%', boxSizing: 'border-box' } : { boxSizing: 'border-box' }}
          >
            {msg.isStreaming && !msg.content ? (
              <div className={styles.thinking}>
                <Spin size="small" />
                <span>思考中...</span>
              </div>
            ) : msg.error ? (
              <div className={styles.error}>
                <span>{msg.content}</span>
                <Button
                  type="link"
                  size="small"
                  icon={<ReloadOutlined />}
                  onClick={handleRetry}
                >
                  重试
                </Button>
              </div>
            ) : (
              msg.content && <MarkdownRenderer content={msg.content} />
            )}
          </div>

          {!isUser && (
              <div style={{ width: '100%' }}>
                  {msg.citations && renderCitations(msg.citations, msg.original_citations?.length ? "参考来源 (Rerank)" : "参考来源")}
                  {msg.original_citations && msg.original_citations.length > 0 && renderCitations(msg.original_citations, "初排结果 (Embedding)")}
              </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={styles.container}>
      <PageHeader
        title="智能对话"
        subtitle="基于知识库的智能问答"
        onBack={() => navigate(-1)}
        extra={
          <Segmented
            value={chatMode}
            onChange={(value) => setChatMode(value as 'normal' | 'agent')}
            options={[
              { label: 'Agent 模式', value: 'agent', icon: <RobotOutlined /> },
              { label: '普通模式', value: 'normal', icon: <MessageOutlined /> },
            ]}
          />
        }
      />

      {/* 配置区 */}
      <Card className={styles.configCard} styles={{ body: { padding: '10px 18px' } }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'nowrap', gap: 16, overflowX: 'auto', width: '100%' }}>
          {/* 左侧主要资源：知识库 + 模型 + Rerank */}
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'nowrap', gap: 14, flexShrink: 0 }}>
            {/* 知识库选择 (Agent模式和普通模式均可见) */}
            <div className={styles.configItem}>
              <label>知识库</label>
              <Select
                mode="multiple"
                placeholder={chatMode === 'agent' ? "全部知识库 (默认全库)" : "选择知识库 (可多选)"}
                value={currentConfig.kbIds}
                onChange={(val) => setCurrentConfig({ kbIds: val })}
                style={{ width: 180 }}
                maxTagCount="responsive"
                allowClear
                options={knowledgeBases.map((kb) => ({
                  value: kb.id,
                  label: kb.name,
                }))}
              />
            </div>

            {/* LLM 模型 */}
            <div className={styles.configItem}>
              <label>模型</label>
              <Select
                showSearch
                optionFilterProp="label"
                placeholder="选择 LLM 模型"
                value={selectedModel}
                onChange={setSelectedModel}
                style={{ width: 160 }}
                options={(chatModels || []).map((m) => ({
                  value: m.id,
                  label: m.name,
                }))}
              />
            </div>

            {/* Rerank 配置 */}
            <div className={styles.configItem}>
              {chatMode === 'normal' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch
                    checkedChildren="Rerank"
                    unCheckedChildren="Rerank"
                    checked={currentConfig.rerankEnabled}
                    onChange={(checked) => setCurrentConfig({ rerankEnabled: checked })}
                  />
                  {currentConfig.rerankEnabled && (
                    <Select
                      showSearch
                      optionFilterProp="label"
                      placeholder="选择 Rerank 模型"
                      value={currentConfig.rerankModelId}
                      onChange={(val) => setCurrentConfig({ rerankModelId: val })}
                      style={{ width: 160 }}
                      options={rerankModels.map((m) => ({
                        value: m.id,
                        label: m.name,
                      }))}
                    />
                  )}
                </div>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label>Rerank 模型</label>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    placeholder="选择 Rerank 模型"
                    value={currentConfig.rerankModelId}
                    onChange={(val) => setCurrentConfig({ rerankModelId: val })}
                    style={{ width: 170 }}
                    options={rerankModels.map((m) => ({
                      value: m.id,
                      label: m.name,
                    }))}
                  />
                  <Tooltip title="Agent 模式下，系统将自主结合意图与上下文，按需调用混合检索并进行重排">
                    <QuestionCircleOutlined style={{ color: '#999', cursor: 'help' }} />
                  </Tooltip>
                </div>
              )}
            </div>
          </div>

          {/* 右侧检索策略与调优按钮 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            {chatMode === 'normal' ? (
              <Popover
                trigger="click"
                placement="bottomRight"
                title="检索与重排高级调优"
                content={
                  <div style={{ width: 310, padding: '4px 0' }}>
                    {/* 检索模式切换 */}
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: 6 }}>检索模式</div>
                      <Segmented
                        block
                        size="middle"
                        value={currentConfig.searchMode}
                        onChange={(val) => setCurrentConfig({ searchMode: val as 'vector' | 'fulltext' | 'hybrid' })}
                        options={[
                          { label: '混合检索', value: 'hybrid' },
                          { label: '纯向量', value: 'vector' },
                          { label: 'BM25 全文', value: 'fulltext' },
                        ]}
                      />
                    </div>

                    <Divider style={{ margin: '10px 0' }} />

                    <div style={{ marginBottom: 14 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: '13px' }}>粗筛召回 Top K</span>
                        <span style={{ color: '#1677ff', fontWeight: 600 }}>{currentConfig.topK}</span>
                      </div>
                      <Slider
                        min={1} max={50}
                        value={currentConfig.topK}
                        onChange={(val) => setCurrentConfig({ topK: val })}
                      />
                    </div>

                    <div style={{ marginBottom: 14 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: '13px' }}>相似度过滤阈值</span>
                        <span style={{ color: '#1677ff', fontWeight: 600 }}>{currentConfig.scoreThreshold}</span>
                      </div>
                      <Slider
                        min={0} max={1} step={0.05}
                        value={currentConfig.scoreThreshold}
                        onChange={(val) => setCurrentConfig({ scoreThreshold: val })}
                      />
                    </div>

                    {currentConfig.searchMode === 'hybrid' && (
                      <div style={{ marginBottom: 14 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: '13px' }}>向量权重</span>
                          <span style={{ color: '#1677ff', fontWeight: 600 }}>{(currentConfig.vectorWeight * 100).toFixed(0)}% (BM25: {((1 - currentConfig.vectorWeight) * 100).toFixed(0)}%)</span>
                        </div>
                        <Slider
                          min={0} max={1} step={0.1}
                          value={currentConfig.vectorWeight}
                          onChange={(val) => setCurrentConfig({ vectorWeight: val, bm25Weight: 1 - val })}
                        />
                      </div>
                    )}

                    {currentConfig.rerankEnabled && (
                      <>
                        <Divider style={{ margin: '10px 0' }} />
                        <div style={{ marginBottom: 14 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                            <span style={{ fontSize: '13px' }}>Rerank 过滤阈值</span>
                            <span style={{ color: '#722ed1', fontWeight: 600 }}>{currentConfig.rerankScoreThreshold}</span>
                          </div>
                          <Slider
                            min={0} max={1} step={0.01}
                            value={currentConfig.rerankScoreThreshold}
                            onChange={(val) => setCurrentConfig({ rerankScoreThreshold: val })}
                          />
                        </div>

                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                            <span style={{ fontSize: '13px' }}>Rerank 重排 Top</span>
                            <span style={{ color: '#722ed1', fontWeight: 600 }}>{currentConfig.rerankTopK}</span>
                          </div>
                          <Slider
                            min={1} max={30}
                            value={currentConfig.rerankTopK}
                            onChange={(val) => setCurrentConfig({ rerankTopK: val })}
                          />
                        </div>
                      </>
                    )}
                  </div>
                }
              >
                <Button icon={<SettingOutlined />} size="middle">
                  检索参数 ({currentConfig.searchMode === 'hybrid' ? '混合' : currentConfig.searchMode === 'vector' ? '向量' : 'BM25'} · Top {currentConfig.topK})
                </Button>
              </Popover>
            ) : (
              <Tag color="blue" style={{ fontSize: '13px', padding: '4px 10px', borderRadius: '4px' }}>
                ⚡ 自动意图分析与动态检索编排
              </Tag>
            )}
          </div>
        </div>
      </Card>

      {/* 对话区 */}
      <Card className={styles.chatCard}>
        <div 
          className={styles.messagesContainer}
          ref={messagesContainerRef}
          onScroll={handleScroll}
        >
          {messages.length === 0 ? (
            <EmptyState
              title={chatMode === 'agent' ? 'Agent 智能问答' : '知识库对话'}
              description={chatMode === 'agent' 
                ? 'Agent 将自动分析您的意图，并调用合适的知识库进行回答' 
                : '选择知识库，直接进行检索问答'}
            />
          ) : (
            <>
              {messages.map(renderMessage)}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* 输入区 */}
        <div className={styles.inputArea}>
          <div className={styles.inputWrapper}>
            <Input.TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder={chatMode === 'agent' ? "输入问题，Agent 将为您深入思考与检索... (Enter 发送，Shift+Enter 换行)" : "输入问题... (Enter 发送，Shift+Enter 换行)"}
              autoSize={{ minRows: 2, maxRows: 5 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              disabled={isGenerating}
              className={styles.inputField}
            />
            <div className={styles.inputBottomBar}>
              {/* 左侧操作：清除上下文 */}
              <div className={styles.inputLeftActions}>
                <Tooltip title="清除当前会话历史，开启全新问答（避免旧上下文干扰）">
                  <Button 
                    type="text"
                    size="small"
                    icon={<DeleteOutlined />} 
                    onClick={() => {
                      Modal.confirm({
                        title: '确认清除上下文？',
                        content: '清除后将开始新的对话，当前会话的上下文记忆将被清空。',
                        okText: '确认清除',
                        cancelText: '取消',
                        onOk: clearMessages,
                      });
                    }}
                    style={{ color: 'var(--text-secondary)' }}
                  >
                    清除上下文
                  </Button>
                </Tooltip>
                {messages.length > 0 && (
                  <span style={{ fontSize: '12px', color: '#999', marginLeft: 8 }}>
                    共 {messages.length} 条对话
                  </span>
                )}
              </div>

              {/* 右侧操作：改写 + 发送 */}
              <div className={styles.inputRightActions}>
                <Tooltip title="调用 LLM 优化输入提问，使表述更清晰、检索更精准">
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={handleRewrite}
                    loading={rewriting}
                    disabled={!inputValue.trim() || isGenerating}
                  >
                    改写
                  </Button>
                </Tooltip>
                
                {isGenerating ? (
                  <Button
                    type="primary"
                    danger
                    size="small"
                    icon={<StopOutlined />}
                    onClick={handleStop}
                  >
                    停止
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    size="small"
                    icon={<SendOutlined />}
                    onClick={handleSend}
                    disabled={!inputValue.trim()}
                  >
                    发送
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      </Card>
      {/* 引用详情弹窗 */}
      <Modal
        title="参考来源详情"
        open={citationModalVisible}
        onCancel={() => setCitationModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setCitationModalVisible(false)}>
            关闭
          </Button>
        ]}
        width={800}
      >
        {selectedCitation && (
          <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
            <div style={{ marginBottom: 16 }}>
               <Tag color="orange">{selectedCitation.kb_name || '未知知识库'}</Tag>
               <Tag color="blue">{selectedCitation.fileName || '未知文件'}</Tag>
               <Tag>{selectedCitation.location || '未知位置'}</Tag>
               <Tag color="green">
                  {selectedCitation.rerank_score 
                    ? `Rerank: ${selectedCitation.rerank_score.toFixed(3)}` 
                    : `相似度: ${selectedCitation.score.toFixed(3)}`}
               </Tag>
            </div>
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6', fontSize: '15px' }}>
                {selectedCitation.image_path ? (
                    <div style={{ textAlign: 'center' }}>
                        <img 
                            src={`http://localhost:8000/static/images/${selectedCitation.image_path}`} 
                            alt="引用图片详情" 
                            style={{ maxWidth: '100%', borderRadius: '8px' }}
                        />
                    </div>
                ) : (
                    selectedCitation.content
                )}
            </div>
            {/* 如果有图片，虽然 Citation 类型定义里暂时没有 image_path，但后端可能传过来。
                如果需要展示图片，可以在 Citation 类型中增加 image_path 字段。
                目前后端已经增加了 image_path，但前端 types/chat.ts 还没加。
                不过 JS 运行时是有的。我们先暂时忽略图片展示，或者加上。
             */}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default Chat;
