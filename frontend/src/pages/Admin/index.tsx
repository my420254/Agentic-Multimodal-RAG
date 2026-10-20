/**
 * 后台控制面：概览、用户、API Key、模型、系统提示词、审计。
 * 仅 admin 可进入；写操作由后端 audit_logs 记录。
 */
import React, { useEffect, useState } from 'react';
import {
  Alert, Button, Card, Col, Collapse, Divider, Form, Input, InputNumber, Modal, Popconfirm,
  Row, Select, Space, Statistic, Switch, Table, Tabs, Tag, Typography, message,
} from 'antd';
import { PlusOutlined, ReloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import * as api from '@/services/admin';

const { Text, Title, Paragraph } = Typography;
const { TextArea } = Input;
const fmt = (v?: string | null) => (v ? String(v).replace('T', ' ').slice(0, 19) : '-');
const copy = async (v: string) => {
  try { await navigator.clipboard.writeText(v); message.success('已复制'); }
  catch { message.warning('浏览器未授权剪贴板，请手动复制'); }
};

const Admin: React.FC = () => {
  const [overview, setOverview] = useState<any>({});
  const [users, setUsers] = useState<any[]>([]);
  const [keys, setKeys] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [prompts, setPrompts] = useState<any[]>([]);
  const [audits, setAudits] = useState<any[]>([]);
  const [obs, setObs] = useState<any>({});
  const [lfSummary, setLfSummary] = useState<any>({ enabled: false });
  const [requestLogs, setRequestLogs] = useState<any[]>([]);
  const [traces, setTraces] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const [userOpen, setUserOpen] = useState(false);
  const [userForm] = Form.useForm();
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyForm] = Form.useForm();
  const [createdKey, setCreatedKey] = useState<any>(null);
  const [tempPwd, setTempPwd] = useState<any>(null);

  const [modelOpen, setModelOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [modelForm] = Form.useForm();
  const [testing, setTesting] = useState<string | null>(null);

  const [promptOpen, setPromptOpen] = useState(false);
  const [promptKey, setPromptKey] = useState('');
  const [versions, setVersions] = useState<any[]>([]);
  const [draft, setDraft] = useState('');
  const [versionLoading, setVersionLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [o, u, k, m, p, a, s, rl, tr, lf] = await Promise.all([
        api.getAdminOverview(),
        api.getAdminUsers({ page: 1, page_size: 100 }),
        api.getAdminApiKeys({ page: 1, page_size: 100 }),
        api.getAdminModels(),
        api.getAdminPrompts(),
        api.getAdminAuditLogs({ page: 1, page_size: 50 }),
        api.getAdminObservabilitySummary(),
        api.getAdminRequestLogs({ page: 1, page_size: 50 }),
        api.getAdminTraces({ page: 1, page_size: 50 }),
        api.getAdminLangfuseSummary().catch(() => ({ enabled: false })),
      ]);
      setOverview(o || {}); setUsers(u?.items || []); setKeys(k?.items || []);
      setModels(m?.items || []); setPrompts(p?.items || []); setAudits(a?.items || []);
      setObs(s || {}); setRequestLogs(rl?.items || []); setTraces(tr?.items || []);
      setLfSummary(lf || { enabled: false });
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const updateUser = async (id: string, data: any) => {
    await api.updateAdminUser(id, data); message.success('用户已更新'); load();
  };
  const resetPwd = async (id: string) => setTempPwd(await api.resetAdminUserPassword(id));

  const createUser = async () => {
    const values = await userForm.validateFields();
    await api.createAdminUser(values);
    setUserOpen(false); userForm.resetFields(); message.success('用户已创建'); load();
  };

  const createKey = async () => {
    const values = await keyForm.validateFields();
    const res = await api.createAdminApiKey(values);
    setKeyOpen(false); keyForm.resetFields(); setCreatedKey(res); load();
  };

  const openModel = (row?: any) => {
    setEditing(row || null); modelForm.resetFields();
    modelForm.setFieldsValue(row ? {
      name: row.name, model_type: row.model_type, base_url: row.base_url,
      model_name: row.model_name, context_length: row.context_length,
      is_active: row.is_active, api_key: '',
    } : { model_type: 'llm', context_length: 4096, is_active: true, api_key: '' });
    setModelOpen(true);
  };
  const saveModel = async () => {
    const values = await modelForm.validateFields();
    if (editing?.id) {
      if (!values.api_key) delete values.api_key;
      await api.updateAdminModel(editing.id, values);
    } else await api.createAdminModel(values);
    setModelOpen(false); load();
  };
  const testModel = async (id: string) => {
    setTesting(id);
    try {
      const r = await api.testAdminModel(id);
      if (r.ok) message.success(`连接成功：${r.latency_ms}ms`); else message.error(`连接失败：${r.error}`);
    } finally { setTesting(null); }
  };

  const openPrompt = async (key: string) => {
    setPromptKey(key); setPromptOpen(true); setVersionLoading(true); setDraft('');
    try { setVersions((await api.getAdminPromptVersions(key))?.items || []); }
    finally { setVersionLoading(false); }
  };
  const reloadVersions = async () => {
    setVersions((await api.getAdminPromptVersions(promptKey))?.items || []); load();
  };
  const saveDraft = async () => {
    if (!draft.trim()) return message.warning('请填写正文');
    await api.createAdminPromptDraft({ key: promptKey, content: draft });
    setDraft(''); message.success('草稿已创建'); reloadVersions();
  };
  const publish = async (v: number, rollback = false) => {
    if (rollback) await api.rollbackAdminPrompt(promptKey, v);
    else await api.publishAdminPrompt(promptKey, v);
    message.success(rollback ? '已回滚' : '已发布'); reloadVersions();
  };

  const userCols = [
    { title: '账号', dataIndex: 'student_id' },
    { title: '邮箱', dataIndex: 'email', render: (v: string) => v || '-' },
    { title: '角色', dataIndex: 'role', render: (v: string, r: any) => (
      <Select size="small" value={v} style={{ width: 105 }} onChange={(role) => updateUser(r.id, { role })}
        options={[{ value: 'student', label: 'student' }, { value: 'admin', label: 'admin' }]} />
    ) },
    { title: '状态', dataIndex: 'status', render: (v: string, r: any) => (
      <Select size="small" value={v} style={{ width: 105 }} onChange={(status) => updateUser(r.id, { status })}
        options={[{ value: 'active', label: 'active' }, { value: 'disabled', label: 'disabled' }]} />
    ) },
    { title: '创建时间', dataIndex: 'created_at', render: fmt },
    { title: '操作', render: (_: any, r: any) => (
      <Popconfirm title="生成临时密码？旧密码立即失效" onConfirm={() => resetPwd(r.id)}>
        <Button size="small">重置密码</Button>
      </Popconfirm>
    ) },
  ];
  const keyCols = [
    { title: '名称', dataIndex: 'name' },
    { title: 'Prefix', dataIndex: 'key_prefix', render: (v: string) => <Text code>{v}</Text> },
    { title: 'Scopes', dataIndex: 'scopes', render: (v: string[]) => (v || []).map((s) => <Tag key={s}>{s}</Tag>) },
    { title: '最近使用', dataIndex: 'last_used_at', render: fmt },
    { title: '过期', dataIndex: 'expires_at', render: fmt },
    { title: '状态', dataIndex: 'revoked_at', render: (v: string) => v ? <Tag color="red">已吊销</Tag> : <Tag color="green">有效</Tag> },
    { title: '操作', render: (_: any, r: any) => r.revoked_at ? '-' : (
      <Popconfirm title="吊销？" onConfirm={async () => { await api.revokeAdminApiKey(r.id); load(); }}>
        <Button size="small" danger>吊销</Button>
      </Popconfirm>
    ) },
  ];
  const modelCols = [
    { title: '名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'model_type', render: (v: string) => <Tag>{v}</Tag> },
    { title: '模型名', dataIndex: 'model_name' },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
    { title: 'Key', dataIndex: 'api_key_masked', render: (v: string) => <Text code>{v || '-'}</Text> },
    { title: '启用', dataIndex: 'is_active', render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag>否</Tag> },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" loading={testing === r.id} onClick={() => testModel(r.id)}>测试</Button>
        <Button size="small" onClick={() => openModel(r)}>编辑</Button>
        <Popconfirm title="删除？" onConfirm={async () => { await api.deleteAdminModel(r.id); load(); }}>
          <Button size="small" danger>删除</Button>
        </Popconfirm>
      </Space>
    ) },
  ];
  const promptCols = [
    { title: 'Key', dataIndex: 'key', render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name' },
    { title: 'Active', dataIndex: 'active_version', render: (v: number) => v ? <Tag color="green">v{v}</Tag> : <Tag>代码默认</Tag> },
    { title: '版本数', dataIndex: 'versions' },
    { title: '操作', render: (_: any, r: any) => <Button size="small" onClick={() => openPrompt(r.key)}>版本管理</Button> },
  ];
  const requestCols = [
    { title: '时间', dataIndex: 'created_at', render: fmt },
    { title: '方法', dataIndex: 'method' },
    { title: '路径', dataIndex: 'path', ellipsis: true },
    { title: '状态', dataIndex: 'status_code', render: (v: number) => <Tag color={v >= 400 ? 'red' : 'green'}>{v}</Tag> },
    { title: '耗时', dataIndex: 'duration_ms', render: (v: number) => `${Number(v || 0).toFixed(1)} ms` },
    { title: '用户', dataIndex: 'user_id', ellipsis: true, render: (v: string) => v || '-' },
  ];
  const traceCols = [
    { title: '时间', dataIndex: 'created_at', render: fmt },
    { title: 'Trace ID', dataIndex: 'trace_id', render: (v: string) => <Text code>{v}</Text> },
    { title: '模式', dataIndex: 'mode', render: (v: string) => <Tag>{v}</Tag> },
    { title: 'Query', dataIndex: 'query', ellipsis: true },
    { title: 'TTFT', dataIndex: 'ttft_ms', render: (v: number) => v == null ? '-' : `${Number(v).toFixed(0)} ms` },
    { title: '总耗时', dataIndex: 'total_ms', render: (v: number) => `${Number(v || 0).toFixed(0)} ms` },
    { title: '错误', dataIndex: 'error', ellipsis: true, render: (v: string) => v ? <Tag color="red">error</Tag> : <Tag color="green">ok</Tag> },
  ];
  const auditCols = [
    { title: '时间', dataIndex: 'created_at', render: fmt },
    { title: '操作', dataIndex: 'action', render: (v: string) => <Text code>{v}</Text> },
    { title: '对象', dataIndex: 'target_type' },
    { title: '对象 ID', dataIndex: 'target_id', ellipsis: true },
    { title: '详情', dataIndex: 'detail', ellipsis: true },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1500, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={2} style={{ margin: 0 }}><SafetyCertificateOutlined /> 管理后台</Title>
          <Paragraph type="secondary">账号、API Key、模型、系统提示词、审计；写操作全部落审计。</Paragraph>
        </div>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
      </div>
      <Alert type="warning" showIcon style={{ margin: '16px 0' }} message="控制面，不是业务页"
        description="系统提示词发布全局生效；API Key/临时密码只显示一次；不能禁用/降级最后一个 active admin。" />
      <Row gutter={12} style={{ marginBottom: 16 }}>
        {[['用户', overview.users], ['知识库', overview.knowledge_bases], ['模型', overview.models],
          ['API Keys', overview.api_keys], ['系统提示词', overview.system_prompts], ['审计日志', overview.audit_logs]]
          .map(([label, value]: any) => (
            <Col xs={12} md={8} lg={4} key={label}>
              <Card size="small"><Statistic title={label} value={Number(value || 0)} /></Card>
            </Col>
          ))}
      </Row>
      <Card>
        <Tabs items={[
          { key: 'users', label: '用户管理', children: (
            <div>
              <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => setUserOpen(true)}>新增用户</Button>
              <Table rowKey="id" size="small" columns={userCols} dataSource={users} pagination={false} />
            </div>
          ) },
          { key: 'keys', label: 'API Key', children: (
            <div>
              <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => setKeyOpen(true)}>创建 API Key</Button>
              <Table rowKey="id" size="small" columns={keyCols} dataSource={keys} pagination={false} />
            </div>
          ) },
          { key: 'models', label: '模型管理', children: (
            <div>
              <Button type="primary" icon={<PlusOutlined />} style={{ marginBottom: 12 }} onClick={() => openModel()}>新增模型</Button>
              <Table rowKey="id" size="small" columns={modelCols} dataSource={models} pagination={false} />
            </div>
          ) },
          { key: 'prompts', label: '系统提示词', children: (
            <div>
              <Alert type="info" showIcon style={{ marginBottom: 12 }} message="优先级：用户覆盖 > 全局 active > 代码默认" />
              <Table rowKey="key" size="small" columns={promptCols} dataSource={prompts} pagination={false} />
            </div>
          ) },
          { key: 'audit', label: '审计日志', children: <Table rowKey="id" size="small" columns={auditCols} dataSource={audits} pagination={false} /> },
          { key: 'observability', label: '观测', children: (
            <div>
              {lfSummary?.enabled !== true ? (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="Langfuse 未配置"
                  description="设置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 后，这里显示 Agent/RAG trace 摘要；详细 trace、dataset、experiment、prompt 都在 Langfuse UI 查看。"
                />
              ) : lfSummary?.available === false ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="Langfuse 暂时不可用"
                  description={`错误类型：${lfSummary?.error || 'unknown'}；下方本地 fallback 仍可用。`}
                />
              ) : (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Tag color="blue">Langfuse · 最近 {lfSummary?.hours || 24} 小时</Tag>
                    {lfSummary?.truncated && <Tag color="orange">结果已截断（≥1000 observations）</Tag>}
                    <Text type="secondary">P95 只统计 chat.request；tokens 含实验与聊天。</Text>
                  </Space>
                  <Row gutter={12} style={{ marginBottom: 12 }}>
                    <Col span={6}><Card size="small"><Statistic title="Chat traces" value={Number(lfSummary?.trace_count || 0)} /></Card></Col>
                    <Col span={6}><Card size="small"><Statistic title="P95 延迟" value={lfSummary?.p95_latency_ms ?? '-'} suffix="ms" /></Card></Col>
                    <Col span={6}><Card size="small"><Statistic title="错误率" value={Number((lfSummary?.error_rate || 0) * 100).toFixed(2)} suffix="%" valueStyle={{ color: (lfSummary?.error_rate || 0) > 0 ? '#cf1322' : '#3f8600' }} /></Card></Col>
                    <Col span={6}><Card size="small"><Statistic title="Tokens (in / out)" value={`${lfSummary?.tokens_input || 0} / ${lfSummary?.tokens_output || 0}`} /></Card></Col>
                  </Row>
                  <Space style={{ marginBottom: 16 }} wrap>
                    {lfSummary?.links?.traces && <Button onClick={() => window.open(lfSummary.links.traces, '_blank')}>Langfuse Traces</Button>}
                    {lfSummary?.links?.experiments && <Button onClick={() => window.open(lfSummary.links.experiments, '_blank')}>Experiments</Button>}
                    {lfSummary?.links?.prompts && <Button onClick={() => window.open(lfSummary.links.prompts, '_blank')}>Prompts</Button>}
                    {lfSummary?.links?.datasets && <Button onClick={() => window.open(lfSummary.links.datasets, '_blank')}>Datasets</Button>}
                  </Space>
                </>
              )}

              <Divider orientation="left">本地 fallback / 基础设施指标</Divider>
              <Collapse
                items={[{
                  key: 'local-fallback',
                  label: 'request_logs / agent_traces / Prometheus（Langfuse 不可用时）',
                  children: (
                    <div>
                      <Row gutter={12} style={{ marginBottom: 12 }}>
                        <Col span={6}><Card size="small"><Statistic title="请求总数" value={Number(obs.total_requests || 0)} /></Card></Col>
                        <Col span={6}><Card size="small"><Statistic title="错误数" value={Number(obs.error_requests || 0)} valueStyle={{ color: '#cf1322' }} /></Card></Col>
                        <Col span={6}><Card size="small"><Statistic title="错误率" value={Number((obs.error_rate || 0) * 100).toFixed(2)} suffix="%" /></Card></Col>
                        <Col span={6}><Card size="small"><Statistic title="平均耗时" value={Number(obs.avg_latency_ms || 0).toFixed(1)} suffix="ms" /></Card></Col>
                      </Row>
                      <Space style={{ marginBottom: 12 }}>
                        <Button onClick={() => window.open('http://127.0.0.1:8000/metrics', '_blank')}>打开 /metrics</Button>
                        <Text type="secondary">Prometheus 文本指标；请求日志不含 query/response 正文。</Text>
                      </Space>
                      <Table rowKey="id" size="small" columns={requestCols} dataSource={requestLogs} pagination={false} />
                      <Title level={5} style={{ marginTop: 16 }}>Agent Trace（query/answer 预览，仅 admin）</Title>
                      <Text type="secondary">trace_id 由 /chat/completions 生成，记录 TTFT、总耗时、引用、工具步骤与错误。</Text>
                      <Table rowKey="trace_id" size="small" columns={traceCols} dataSource={traces} pagination={false} style={{ marginTop: 8 }} />
                    </div>
                  ),
                }]}
              />
            </div>
          ) },
        ]} />
      </Card>

      <Modal title="新增用户" open={userOpen} onCancel={() => setUserOpen(false)} onOk={createUser} okText="创建">
        <Form form={userForm} layout="vertical" initialValues={{ role: 'student' }}>
          <Form.Item name="student_id" label="学号/账号" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="email" label="邮箱（可选）"><Input /></Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 8 }]}><Input.Password /></Form.Item>
          <Form.Item name="role" label="角色"><Select options={[{ value: 'student', label: 'student' }, { value: 'admin', label: 'admin' }]} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="创建 API Key" open={keyOpen} onCancel={() => setKeyOpen(false)} onOk={createKey} okText="创建">
        <Form form={keyForm} layout="vertical" initialValues={{ scopes: ['chat:read', 'kb:read'] }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="scopes" label="Scopes">
            <Select mode="multiple" options={['chat:read', 'kb:read', 'eval:run', 'admin:*'].map((v) => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item name="expires_days" label="有效天数（可选）"><InputNumber min={1} max={3650} style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
      <Modal title="API Key 已创建（只显示一次）" open={!!createdKey} onCancel={() => setCreatedKey(null)} footer={<Button onClick={() => setCreatedKey(null)}>我已保存</Button>}>
        <Alert type="warning" showIcon message="关闭后无法再次查看明文" style={{ marginBottom: 12 }} />
        <Input.TextArea readOnly rows={3} value={createdKey?.key} />
        <Button style={{ marginTop: 8 }} onClick={() => copy(createdKey?.key || '')}>复制 Key</Button>
      </Modal>
      <Modal title="临时密码（只显示一次）" open={!!tempPwd} onCancel={() => setTempPwd(null)} footer={<Button onClick={() => setTempPwd(null)}>我已保存</Button>}>
        <Alert type="warning" showIcon message="旧密码已失效" style={{ marginBottom: 12 }} />
        <Input readOnly value={tempPwd?.temp_password} />
        <Button style={{ marginTop: 8 }} onClick={() => copy(tempPwd?.temp_password || '')}>复制密码</Button>
      </Modal>
      <Modal title={editing ? '编辑模型' : '新增模型'} open={modelOpen} onCancel={() => setModelOpen(false)} onOk={saveModel} okText="保存" width={700}>
        <Form form={modelForm} layout="vertical">
          <Row gutter={12}>
            <Col span={12}><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="model_type" label="类型" rules={[{ required: true }]}>
              <Select options={['llm', 'vlm', 'embedding', 'rerank'].map((v) => ({ value: v, label: v }))} />
            </Form.Item></Col>
          </Row>
          <Form.Item name="base_url" label="Base URL / 本地路径" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="model_name" label="模型名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="api_key" label={editing ? 'API Key（留空不修改）' : 'API Key'}>
            <Input.Password placeholder={editing?.api_key_masked || ''} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}><Form.Item name="context_length" label="上下文长度"><InputNumber min={256} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
      <Modal title={`系统提示词版本：${promptKey}`} open={promptOpen} onCancel={() => setPromptOpen(false)} footer={null} width={900}>
        <Alert type="info" showIcon style={{ marginBottom: 12 }} message="发布/回滚立即影响全局；用户覆盖仍然优先。" />
        <TextArea rows={4} value={draft} onChange={(e) => setDraft(e.target.value)}
          placeholder="新建草稿正文……" style={{ marginBottom: 8, fontFamily: 'Consolas, monospace' }} />
        <Button type="primary" onClick={saveDraft} style={{ marginBottom: 12 }}>保存为新草稿</Button>
        <Table rowKey="id" size="small" loading={versionLoading} dataSource={versions} pagination={false}
          columns={[
            { title: '版本', dataIndex: 'version', render: (v: number) => `v${v}` },
            { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'active' ? 'green' : v === 'draft' ? 'blue' : 'default'}>{v}</Tag> },
            { title: '创建', dataIndex: 'created_at', render: fmt },
            { title: '发布', dataIndex: 'published_at', render: fmt },
            { title: '操作', render: (_: any, r: any) => (
              <Space>
                {r.status !== 'active' && <Button size="small" onClick={() => publish(r.version)}>发布</Button>}
                {r.status === 'archived' && <Button size="small" onClick={() => publish(r.version, true)}>回滚</Button>}
              </Space>
            ) },
          ]}
          expandable={{ expandedRowRender: (r: any) => <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>{r.content}</pre> }}
        />
      </Modal>
    </div>
  );
};

export default Admin;
