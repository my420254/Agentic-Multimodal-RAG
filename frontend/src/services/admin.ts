/** 后台控制面 API */
import request from './request';

export const getAdminOverview = (): Promise<any> => request.get('/admin/overview');

export const getAdminUsers = (params?: Record<string, any>): Promise<any> =>
  request.get('/admin/users', { params });

export const createAdminUser = (data: Record<string, any>): Promise<any> =>
  request.post('/admin/users', data);

export const updateAdminUser = (id: string, data: Record<string, any>): Promise<any> =>
  request.patch(`/admin/users/${id}`, data);

export const resetAdminUserPassword = (id: string): Promise<any> =>
  request.post(`/admin/users/${id}/reset-password`);

export const getAdminApiKeys = (params?: Record<string, any>): Promise<any> =>
  request.get('/admin/api-keys', { params });

export const createAdminApiKey = (data: Record<string, any>): Promise<any> =>
  request.post('/admin/api-keys', data);

export const revokeAdminApiKey = (id: string): Promise<any> =>
  request.delete(`/admin/api-keys/${id}`);

export const getAdminModels = (): Promise<any> => request.get('/admin/models');

export const createAdminModel = (data: Record<string, any>): Promise<any> =>
  request.post('/admin/models', data);

export const updateAdminModel = (id: string, data: Record<string, any>): Promise<any> =>
  request.patch(`/admin/models/${id}`, data);

export const deleteAdminModel = (id: string): Promise<any> =>
  request.delete(`/admin/models/${id}`);

export const testAdminModel = (id: string): Promise<any> =>
  request.post(`/admin/models/${id}/test`);

export const getAdminPrompts = (): Promise<any> => request.get('/admin/prompts');

export const getAdminPromptVersions = (key: string): Promise<any> =>
  request.get(`/admin/prompts/${key}/versions`);

export const createAdminPromptDraft = (data: Record<string, any>): Promise<any> =>
  request.post('/admin/prompts', data);

export const publishAdminPrompt = (key: string, version: number): Promise<any> =>
  request.post(`/admin/prompts/${key}/publish`, { version });

export const rollbackAdminPrompt = (key: string, version: number): Promise<any> =>
  request.post(`/admin/prompts/${key}/rollback`, { version });

export const getAdminRequestLogs = (params?: Record<string, any>): Promise<any> =>
  request.get('/admin/request-logs', { params });

export const getAdminObservabilitySummary = (): Promise<any> =>
  request.get('/admin/observability/summary');

export const getAdminAuditLogs = (params?: Record<string, any>): Promise<any> =>
  request.get('/admin/audit-logs', { params });
