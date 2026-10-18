/**
 * 鉴权相关类型
 */

export interface LoginRequest {
  student_id: string;
  password: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthUser {
  id: string;
  student_id: string;
  email?: string | null;
  role: string;
  status: string;
  created_at: string;
}
