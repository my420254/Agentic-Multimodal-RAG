/**
 * 路由守卫：没有 access token 直接去登录页；有 token 但无 user 时拉一次 /auth/me。
 */

import React, { useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { getMe } from '@/services/auth';
import { clearAuth, useAuthStore } from '@/stores/auth';

const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const location = useLocation();

  useEffect(() => {
    if (!token || user) return;
    getMe()
      .then(setUser)
      .catch(() => clearAuth());
  }, [token, user, setUser]);

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
};

export default RequireAuth;
