import { apiGet, apiPost } from './client'

export interface UserOut {
  id: string
  email: string
  display_name: string | null
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface AuthResponse {
  token: TokenResponse
  user: UserOut
}

export const register = (payload: {
  email: string
  password: string
  display_name?: string
}) => apiPost<AuthResponse>('/auth/register', payload)

export const login = (payload: { email: string; password: string }) =>
  apiPost<AuthResponse>('/auth/login', payload)

export const fetchMe = () => apiGet<UserOut>('/auth/me')
