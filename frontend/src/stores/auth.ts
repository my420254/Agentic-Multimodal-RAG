/**
 * 登录态（Zustand + localStorage）
 */

import { create } from 'zustand';
import type { AuthUser, TokenPair } from '@/types/auth';

const ACCESS_KEY = 'lnu_access_token';
const REFRESH_KEY = 'lnu_refresh_token';
const USER_KEY = 'lnu_auth_user';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: AuthUser | null;
  setSession: (pair: TokenPair) => void;
  setUser: (user: AuthUser) => void;
  clear: () => void;
}

const readUser = (): AuthUser | null => {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
};

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(ACCESS_KEY),
  refreshToken: localStorage.getItem(REFRESH_KEY),
  user: readUser(),

  setSession: (pair) => {
    localStorage.setItem(ACCESS_KEY, pair.access_token);
    localStorage.setItem(REFRESH_KEY, pair.refresh_token);
    set({ token: pair.access_token, refreshToken: pair.refresh_token });
  },

  setUser: (user) => {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    set({ user });
  },

  clear: () => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
    set({ token: null, refreshToken: null, user: null });
  },
}));

export const getAccessToken = (): string | null => localStorage.getItem(ACCESS_KEY);
export const getRefreshToken = (): string | null => localStorage.getItem(REFRESH_KEY);

export const saveTokenPair = (pair: TokenPair): void => {
  localStorage.setItem(ACCESS_KEY, pair.access_token);
  localStorage.setItem(REFRESH_KEY, pair.refresh_token);
  useAuthStore.setState({ token: pair.access_token, refreshToken: pair.refresh_token });
};

export const clearAuth = (): void => {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
  useAuthStore.setState({ token: null, refreshToken: null, user: null });
};
