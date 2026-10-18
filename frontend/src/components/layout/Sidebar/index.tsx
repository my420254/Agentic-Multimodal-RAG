/**
 * 侧边栏组件
 */

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import {
  DatabaseOutlined,
  MessageOutlined,
  SettingOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import type { MenuProps } from 'antd';
import styles from './Sidebar.module.css';

type MenuItem = Required<MenuProps>['items'][number];

const menuItems: MenuItem[] = [
  {
    key: '/career',
    icon: <RocketOutlined />,
    label: '智能求职与模拟面试',
  },
  {
    key: '/kb',
    icon: <DatabaseOutlined />,
    label: '学生与岗位知识库',
  },
  {
    key: '/chat',
    icon: <MessageOutlined />,
    label: '智能对话',
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: '系统设置',
  },
];

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  // 根据当前路径获取选中的菜单项
  const getSelectedKey = () => {
    const { pathname } = location;
    if (pathname.startsWith('/career')) return '/career';
    if (pathname.startsWith('/kb')) return '/kb';
    if (pathname.startsWith('/chat')) return '/chat';
    if (pathname.startsWith('/settings')) return '/settings';
    return '/career';
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
        <span>v0.1.0</span>
      </div>
    </aside>
  );
};

export default Sidebar;
