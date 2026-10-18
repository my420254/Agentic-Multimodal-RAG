/**
 * Axios 实例配置
 *
 * 统一做三件事：
 * 1. 自动附加 Authorization: Bearer <access_token>
 * 2. access token 过期时用 refresh token 换一次并重试原请求
 * 3. 统一解析 FastAPI 的 detail 错误并提示
 */

import axios, { AxiosError, InternalAxiosRequestConfig, AxiosResponse } from 'axios';
import { message } from 'antd';
import {
  clearAuth,
  getAccessToken,
  getRefreshToken,
  saveTokenPair,
} from '@/stores/auth';
import type { TokenPair } from '@/types/auth';

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

const isAuthEndpoint = (url?: string): boolean =>
  Boolean(url && (url.includes('/auth/login') || url.includes('/auth/refresh')));

let refreshPromise: Promise<string | null> | null = null;

const refreshAccessTokenInternal = async (): Promise<string | null> => {
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

request.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getAccessToken();
    if (token && !isAuthEndpoint(config.url)) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

request.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = error.response?.status;

    if (status === 401 && original && !original._retry && !isAuthEndpoint(original.url)) {
      original._retry = true;
      refreshPromise = refreshPromise || refreshAccessTokenInternal();
      const newToken = await refreshPromise;
      refreshPromise = null;
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`;
        return request(original);
      }
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }

    const data = error.response?.data as { detail?: unknown; message?: string } | undefined;
    let errorMessage = data?.message || error.message || '请求失败';
    if (typeof data?.detail === 'string') {
      errorMessage = data.detail;
    } else if (data?.detail && typeof data.detail === 'object') {
      const detail = data.detail as { message?: string; code?: number };
      errorMessage = detail.message || JSON.stringify(detail);
    }
    if (!isAuthEndpoint(original?.url)) {
      message.error(errorMessage);
    }
    return Promise.reject(error);
  },
);

export default request;
