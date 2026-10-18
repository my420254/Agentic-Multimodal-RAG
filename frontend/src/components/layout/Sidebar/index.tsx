/**
 * 侧边栏组件
 */

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Button, Menu, Typography } from 'antd';
import {
  CodeOutlined,
  CommentOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  LogoutOutlined,
  MessageOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { MenuProps } from 'antd';
import styles from './Sidebar.module.css';
import { clearAuth, useAuthStore } from '@/stores/auth';

const { Text } = Typography;

type MenuItem = Required<MenuProps>['items'][number];

const baseMenuItems: MenuItem[] = [
  {
    key: '/career/resume',
    icon: <FileTextOutlined />,
    label: '简历诊断',
  },
  {
    key: '/career/interview',
    icon: <CommentOutlined />,
    label: '模拟面试',
  },
  {
    key: '/career/prompts',
    icon: <CodeOutlined />,
    label: '提示词工坊',
  },
  {
    key: '/kb',
    icon: <DatabaseOutlined />,
    label: '知识库',
  },
  {
    key: '/chat',
    icon: <MessageOutlined />,
    label: '智能对话',
  },
];

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const menuItems: MenuItem[] = user?.role === 'admin'
    ? [...baseMenuItems, { key: '/admin', icon: <SafetyCertificateOutlined />, label: '管理后台' }]
    : baseMenuItems;

  const handleLogout = () => {
    clearAuth();
    navigate('/login', { replace: true });
  };

  // 根据当前路径获取选中的菜单项
  const getSelectedKey = () => {
    const { pathname } = location;
    if (pathname.startsWith('/career/interview')) return '/career/interview';
    if (pathname.startsWith('/career/prompts')) return '/career/prompts';
    if (pathname.startsWith('/career')) return '/career/resume';
    if (pathname.startsWith('/kb')) return '/kb';
    if (pathname.startsWith('/chat')) return '/chat';
    if (pathname.startsWith('/admin')) return '/admin';
    return '/career/resume';
  };

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  return (
    <aside className={styles.sidebar}>
      <div className={styles.logo}>
        <div className={styles.logoIcon}>
          <RocketOutlined />
        </div>
        <span className={styles.logoText}>辽大·求职Agent</span>
      </div>


      <Menu
        mode="inline"
        selectedKeys={[getSelectedKey()]}
        items={menuItems}
        onClick={handleMenuClick}
        className={styles.menu}
      />

      <div className={styles.footer}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, justifyContent: 'center' }}>
          <UserOutlined />
          <Text strong>{user?.student_id || '已登录'}</Text>
          {user?.role && <Text type="secondary">{user.role}</Text>}
        </div>
        <Button size="small" icon={<LogoutOutlined />} onClick={handleLogout} block>
          退出登录
        </Button>
        <div style={{ marginTop: 8 }}>v0.1.0</div>
      </div>
    </aside>
  );
};

export default Sidebar;
