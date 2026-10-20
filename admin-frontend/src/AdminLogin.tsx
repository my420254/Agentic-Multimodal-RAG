import React, { useState } from 'react';
import { Button, Card, Form, Input, Typography, message } from 'antd';
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { getMe, login } from '@/services/auth';
import { clearAuth, useAuthStore } from '@/stores/auth';

const { Title, Paragraph, Text } = Typography;

const AdminLogin: React.FC = () => {
  const setSession = useAuthStore((state) => state.setSession);
  const setUser = useAuthStore((state) => state.setUser);
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: { student_id: string; password: string }) => {
    setLoading(true);
    try {
      const pair = await login(values);
      setSession(pair);
      const user = await getMe();
      if (user.role !== 'admin') {
        clearAuth();
        message.error('该账号不是管理员，无法进入观测后台');
        return;
      }
      setUser(user);
      window.history.replaceState({}, '', '/');
      message.success('已进入观测后台');
    } catch (error: any) {
      clearAuth();
      const detail = error?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '登录失败，请检查管理员账号');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #7c3aed 100%)',
        padding: 24,
      }}
    >
      <Card style={{ width: 430, borderRadius: 16, border: 'none' }} styles={{ body: { padding: 36 } }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div
            style={{
              width: 56,
              height: 56,
              margin: '0 auto 12px',
              borderRadius: 16,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: 26,
              background: 'linear-gradient(135deg, #1677ff, #722ed1)',
            }}
          >
            <SafetyCertificateOutlined />
          </div>
          <Title level={3} style={{ marginBottom: 4 }}>
            观测后台
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            仅管理员可登录；查看 Langfuse 指标、请求日志与 Agent Trace
          </Paragraph>
        </div>

        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item name="student_id" label="管理员账号" rules={[{ required: true, message: '请输入账号' }]}>
            <Input prefix={<UserOutlined />} size="large" placeholder="admin" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" placeholder="请输入密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={loading}>
            进入观测后台
          </Button>
        </Form>

        <div style={{ marginTop: 18, fontSize: 12, color: '#8c8c8c', textAlign: 'center' }}>
          <Text type="secondary">学生端入口：http://localhost:3000</Text>
        </div>
      </Card>
    </div>
  );
};

export default AdminLogin;
