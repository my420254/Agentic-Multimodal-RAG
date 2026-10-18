/**
 * 登录页
 */

import React, { useEffect, useState } from 'react';
import { Button, Card, Form, Input, message, Typography } from 'antd';
import { LockOutlined, RocketOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { getMe, login } from '@/services/auth';
import { useAuthStore } from '@/stores/auth';

const { Title, Paragraph, Text } = Typography;

const Login: React.FC = () => {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const setSession = useAuthStore((state) => state.setSession);
  const setUser = useAuthStore((state) => state.setUser);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (token) navigate('/career', { replace: true });
  }, [token, navigate]);

  const handleSubmit = async (values: { student_id: string; password: string }) => {
    setLoading(true);
    try {
      const pair = await login(values);
      setSession(pair);
      const user = await getMe();
      setUser(user);
      message.success(`欢迎回来，${user.student_id}`);
      navigate('/career', { replace: true });
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      message.error(typeof detail === 'string' ? detail : '登录失败，请检查学号和密码');
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
      <Card
        style={{ width: 430, borderRadius: 16, boxShadow: '0 24px 80px rgba(0,0,0,.35)', border: 'none' }}
        styles={{ body: { padding: 36 } }}
      >
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
            <RocketOutlined />
          </div>
          <Title level={3} style={{ marginBottom: 4 }}>
            辽大 · 求职 Agent
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            登录后查看你的真实简历与模拟面试记录
          </Paragraph>
        </div>

        <Form layout="vertical" onFinish={handleSubmit} initialValues={{ student_id: '2023001', password: 'Test@123456' }}>
          <Form.Item name="student_id" label="学号" rules={[{ required: true, message: '请输入学号' }]}>
            <Input prefix={<UserOutlined />} size="large" placeholder="例如 2023001" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} size="large" placeholder="请输入密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={loading}>
            登录
          </Button>
        </Form>

        <div style={{ marginTop: 18, fontSize: 12, color: '#8c8c8c', textAlign: 'center' }}>
          <Text type="secondary">本地演示账号：2023001 / 2023002，密码 Test@123456</Text>
        </div>
      </Card>
    </div>
  );
};

export default Login;
