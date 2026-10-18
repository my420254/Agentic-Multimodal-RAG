/** 仅 admin 可进入；未登录交给外层 RequireAuth。 */
import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/auth';

const RequireAdmin: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const user = useAuthStore((state) => state.user);
  if (!user) return null;
  if (user.role !== 'admin') return <Navigate to="/career/resume" replace />;
  return <>{children}</>;
};

export default RequireAdmin;
