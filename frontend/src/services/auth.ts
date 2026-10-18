/**
 * 鉴权 API 与带 token 的 fetch（SSE / 手写 fetch 用）
 */

import axios from 'axios';
import request from './request';
import type { AuthUser, LoginRequest, TokenPair } from '@/types/auth';
import { clearAuth, getAccessToken, getRefreshToken, saveTokenPair } from '@/stores/auth';

export const login = (data: LoginRequest): Promise<TokenPair> => {
  return request.post('/auth/login', data);
};

export const refreshToken = (token: string): Promise<TokenPair> => {
  return request.post('/auth/refresh', { refresh_token: token });
};

export const getMe = (): Promise<AuthUser> => {
  return request.get('/auth/me');
};

/** 用 refresh token 换新 access；供 axios 拦截器和 authFetch 共用 */
export const refreshAccessToken = async (): Promise<string | null> => {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  try {
    const response = await axios.post('/api/v1/auth/refresh', {
      refresh_token: refresh,
    });
    const pair = response.data as TokenPair;
    saveTokenPair(pair);
    return pair.access_token;
  } catch {
    clearAuth();
    return null;
  }
};

const redirectToLogin = (): void => {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
};

/**
 * 带 Authorization 的 fetch；401 时自动刷新一次并重试。
 * 用于 SSE 对话和 CareerCenter 里手写的 fetch。
 */
export const authFetch = async (
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> => {
  const doFetch = async (token: string | null): Promise<Response> => {
    const headers = new Headers(init.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return fetch(input, { ...init, headers });
  };

  let response = await doFetch(getAccessToken());
  if (response.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      response = await doFetch(newToken);
    } else {
      redirectToLogin();
    }
  }
  return response;
};
