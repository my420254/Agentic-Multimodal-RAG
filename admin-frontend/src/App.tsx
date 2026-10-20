import React, { useEffect, useState } from 'react';
import { Button, Result, Spin, Typography } from 'antd';
import Admin from '@/pages/Admin';
import { getMe } from '@/services/auth';
import { clearAuth, useAuthStore } from '@/stores/auth';
import AdminLogin from './AdminLogin';

const { Title, Text } = Typography;

const App: React.FC = () => {
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const [loadingUser, setLoadingUser] = useState(false);

  useEffect(() => {
    if (!token || user) return;
    setLoadingUser(true);
    getMe()
      .then((me) => setUser(me))
      .catch(() => clearAuth())
      .finally(() => setLoadingUser(false));
  }, [token, user, setUser]);

  if (!token) return <AdminLogin />;

  if (loadingUser || !user) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (user.role !== 'admin') {
    return (
      <Result
        status="403"
        title="需要管理员权限"
        subTitle="当前账号不是 admin，无法进入观测后台。"
        extra={<Button onClick={() => { clearAuth(); window.location.href = '/'; }}>退出</Button>}
      />
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <header
        style={{
          height: 64,
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#001529',
          color: '#fff',
        }}
      >
        <Title level={4} style={{ color: '#fff', margin: 0 }}>
          辽大·求职 Agent · 观测后台
        </Title>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Text style={{ color: 'rgba(255,255,255,.75)' }}>{user.student_id} · admin</Text>
          <Button size="small" onClick={() => { clearAuth(); window.location.href = '/'; }}>
            退出
          </Button>
        </div>
      </header>
      <main style={{ padding: 24, maxWidth: 1440, margin: '0 auto' }}>
        <Admin defaultTab="observability" />
      </main>
    </div>
  );
};

export default App;
